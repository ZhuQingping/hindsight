"""Engine-hook policy tests over PG metadata, including internal worker contexts."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
from hindsight_api.engine.memory_engine import _current_schema
from hindsight_api.extensions.context import DefaultExtensionContext
from hindsight_api.extensions.operation_validator import (
    BankReadContext,
    BankReadOperation,
    BankWriteContext,
    BankWriteOperation,
    CreateBankContext,
    MentalModelGetContext,
    RecallContext,
    RetainContext,
)
from hindsight_api.models import RequestContext
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import ApiKeyCreate, MemberCreate, Scope
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .test_repository import ADMIN, ready_workspace


@dataclass
class PoolHost:
    pool: asyncpg.Pool
    _operation_validator: object | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@pytest.fixture
def configured(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> Settings:
    key_id = secrets.token_hex(16)
    secret = f"ctx_ctrl_{key_id}_{secrets.token_urlsafe(32)}"
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    monkeypatch.setenv(
        "CONTEXTDB_CONTROL_KEYS",
        json.dumps([{"key_id": key_id, "sha256": hashlib.sha256(secret.encode()).hexdigest()}]),
    )
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN", raising=False)
    return Settings.from_environment()


async def test_rest_and_mcp_auth_resolve_same_member_space_and_key(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await repository.create_member(ADMIN, workspace.workspace_id, MemberCreate(member_name="User"), "create")
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Read", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "key",
    )
    extension = ContextDBTenantExtension({})
    extension.transport_guard_installed = True  # This test exercises the engine adapter, not ASGI wiring.
    extension.set_context(
        DefaultExtensionContext("", memory_engine=PoolHost(repository.pool, ContextDBOperationValidator({})))
    )
    rest = RequestContext(api_key=key.secret)
    mcp = RequestContext(api_key=key.secret)
    assert await extension.authenticate(rest) == await extension.authenticate_mcp(mcp)
    assert rest.tenant_id == mcp.tenant_id == workspace.workspace_id
    assert rest.api_key_id == mcp.api_key_id == key.metadata.key_id
    assert rest.allowed_bank_ids == [workspace.workspace_id]
    assert [tenant.schema for tenant in await extension.list_tenants()] == [workspace.schema_name]


async def test_read_scope_blocks_retain_cross_bank_and_bank_mutations(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Read", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "key",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=PoolHost(repository.pool)))
    context = RequestContext(api_key=key.secret)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert (await validator.validate_recall(RecallContext(workspace.workspace_id, "query", context))).allowed
        assert not (await validator.validate_retain(RetainContext(workspace.workspace_id, [], context))).allowed
        assert not (await validator.validate_recall(RecallContext("another-bank", "query", context))).allowed
        assert not (await validator.validate_create_bank(CreateBankContext(workspace.workspace_id, context))).allowed
        for operation in BankWriteOperation:
            assert not (
                await validator.validate_bank_write(BankWriteContext(workspace.workspace_id, operation, context))
            ).allowed
    finally:
        _current_schema.reset(token)


async def test_knowledge_only_key_is_not_a_memory_recall_filter(repository: Repository, configured: Settings) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Knowledge", scopes=[Scope.KNOWLEDGE_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "key",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=PoolHost(repository.pool)))
    context = RequestContext(api_key=key.secret)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert not (await validator.validate_recall(RecallContext(workspace.workspace_id, "query", context))).allowed
        for operation in BankReadOperation:
            result = await validator.validate_bank_read(BankReadContext(workspace.workspace_id, operation, context))
            assert result.allowed == (
                operation
                in {
                    BankReadOperation.GET_KNOWLEDGE_BASE_TREE,
                    BankReadOperation.GET_KNOWLEDGE_PAGE,
                    BankReadOperation.SEARCH_KNOWLEDGE_BASE,
                    BankReadOperation.EXPORT_KNOWLEDGE_BASE,
                }
            )
        # A client-controlled header is not a trusted engine read origin.
        context.extra_headers["read_origin"] = "knowledge_page"
        assert not (
            await validator.validate_mental_model_get(MentalModelGetContext(workspace.workspace_id, "model", context))
        ).allowed
        assert (
            await validator.validate_mental_model_get(
                MentalModelGetContext(workspace.workspace_id, "model", context, read_origin="knowledge_page")
            )
        ).allowed
        assert not (
            await validator.validate_mental_model_get(
                MentalModelGetContext("another-bank", "model", context, read_origin="knowledge_page")
            )
        ).allowed
        tools = frozenset(
            {"recall", "get_bank_profile", "get_knowledge_page", "create_knowledge_page", "get_mental_model"}
        )
        assert await validator.filter_mcp_tools(workspace.workspace_id, context, tools) == frozenset(
            {"get_knowledge_page"}
        )
    finally:
        _current_schema.reset(token)


async def test_memory_write_allows_knowledge_crud_but_not_bank_management(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Writer",
            scopes=[Scope.MEMORY_READ, Scope.MEMORY_WRITE],
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        ),
        "writer",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=PoolHost(repository.pool)))
    context = RequestContext(api_key=key.secret)
    token = _current_schema.set(workspace.schema_name)
    try:
        for operation in {
            BankWriteOperation.CREATE_KNOWLEDGE_FOLDER,
            BankWriteOperation.CREATE_KNOWLEDGE_PAGE,
            BankWriteOperation.UPDATE_KNOWLEDGE_PAGE,
            BankWriteOperation.RENAME_KNOWLEDGE_NODE,
            BankWriteOperation.MOVE_KNOWLEDGE_NODE,
            BankWriteOperation.DELETE_KNOWLEDGE_NODE,
        }:
            assert (
                await validator.validate_bank_write(BankWriteContext(workspace.workspace_id, operation, context))
            ).allowed
        for operation in {
            BankWriteOperation.DELETE_BANK,
            BankWriteOperation.UPDATE_BANK_CONFIG,
            BankWriteOperation.IMPORT_DOCUMENTS,
        }:
            assert not (
                await validator.validate_bank_write(BankWriteContext(workspace.workspace_id, operation, context))
            ).allowed
    finally:
        _current_schema.reset(token)


async def test_internal_worker_is_scoped_but_cannot_create_delete_bank(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=PoolHost(repository.pool)))
    context = RequestContext(internal=True, tenant_id=workspace.workspace_id)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert (await validator.validate_retain(RetainContext(workspace.workspace_id, [], context))).allowed
        assert not (await validator.validate_retain(RetainContext("another-bank", [], context))).allowed
        assert not (await validator.validate_create_bank(CreateBankContext(workspace.workspace_id, context))).allowed
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.workspace_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        context.extra_headers["ctxdb-internal-purpose"] = "delete_workspace"
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.workspace_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        # A purpose name alone is not authority: it must match the durable,
        # currently leased operation generated by management.
        await repository.delete_workspace(ADMIN, workspace.workspace_id, "lease-delete", "request")
        operation = await repository.claim_operation()
        assert operation is not None
        context.extra_headers.update(
            {"ctxdb-operation-id": operation.operation_id, "ctxdb-lease-token": operation.lease_token}
        )
        assert (
            await validator.validate_bank_write(
                BankWriteContext(workspace.workspace_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        await repository.complete_operation(operation)
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.workspace_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
    finally:
        _current_schema.reset(token)


def test_legacy_mcp_shared_token_and_invalid_configuration_fail_closed(
    configured: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HINDSIGHT_API_MCP_AUTH_TOKEN", "synthetic-shared-token")
    with pytest.raises(ValueError, match="dynamic MCP"):
        Settings.from_environment()
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN")
    monkeypatch.setenv("CONTEXTDB_CONTROL_KEYS", "invalid-synthetic-json-secret")
    with pytest.raises(ValueError) as error:
        Settings.from_environment()
    assert "invalid-synthetic-json-secret" not in str(error.value)


@dataclass
class InitializingHost:
    db_url: str
    _initialized: bool = False
    _operation_validator: object | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        raise AssertionError("Tenant discovery must not re-enter engine initialization")


async def test_discovery_before_pool_exists_does_not_reenter_initialize(
    repository: Repository,
    configured: Settings,
    database_url: str,
) -> None:
    workspace = await ready_workspace(repository)
    extension = ContextDBTenantExtension({})
    extension.set_context(
        DefaultExtensionContext(
            "", memory_engine=InitializingHost(database_url, _operation_validator=ContextDBOperationValidator({}))
        )
    )
    assert [tenant.schema for tenant in await extension.list_tenants()] == [workspace.schema_name]


async def test_missing_validator_never_becomes_unrestricted_tenant_routing(
    repository: Repository, configured: Settings
) -> None:
    extension = ContextDBTenantExtension({})
    extension.set_context(DefaultExtensionContext("", memory_engine=PoolHost(repository.pool)))
    with pytest.raises(RuntimeError, match="operation validator"):
        await extension.list_tenants()
    with pytest.raises(RuntimeError, match="operation validator"):
        await extension.authenticate(RequestContext(api_key="ignored"))


async def test_missing_admission_extension_fails_closed(repository: Repository, configured: Settings) -> None:
    extension = ContextDBTenantExtension({})
    extension.set_context(
        DefaultExtensionContext("", memory_engine=PoolHost(repository.pool, ContextDBOperationValidator({})))
    )
    with pytest.raises(RuntimeError, match="admission extension"):
        await extension.on_startup()
    with pytest.raises(RuntimeError, match="admission extension"):
        await extension.authenticate(RequestContext(api_key="ignored"))


@pytest.mark.parametrize("value", ["true", "TRUE", " true "])
def test_migration_isolation_parser_matches_native_rejection(
    configured: Settings, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("HINDSIGHT_API_MIGRATION_ISOLATION", value)
    with pytest.raises(ValueError, match="MIGRATION_ISOLATION=false"):
        Settings.from_environment()
