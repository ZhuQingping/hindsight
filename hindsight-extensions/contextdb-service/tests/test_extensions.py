"""Engine-hook policy tests over PG metadata, including internal worker contexts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import asyncpg
import pytest
from hindsight_api import MemoryEngine
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
from hindsight_ext_contextdb.models import ApiKeyCreate, UserCreate
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.routing import bank_target
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .test_repository import ADMIN, ADMIN_SECRET, admin_actor, ready_workspace, space_user


@dataclass
class PoolHost:
    pool: asyncpg.Pool
    _operation_validator: object | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@pytest.fixture
def configured(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN", raising=False)
    return Settings.from_environment()


async def test_rest_and_mcp_auth_resolve_same_member_space_and_key(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await repository.create_user(await admin_actor(repository), UserCreate(name="User"), "create")
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Read",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "key",
    )
    extension = ContextDBTenantExtension({})
    extension.transport_guard_installed = True
    extension.set_context(
        DefaultExtensionContext(
            "", memory_engine=cast(MemoryEngine, PoolHost(repository.pool, ContextDBOperationValidator({})))
        )
    )
    rest = RequestContext(api_key=key.secret)
    mcp = RequestContext(api_key=key.secret)
    with bank_target(workspace.bank_id):
        assert await extension.authenticate(rest) == await extension.authenticate_mcp(mcp)
    assert rest.tenant_id == workspace.workspace_id
    assert mcp.tenant_id == repository.cloud_tenant_id
    assert rest.api_key_id == mcp.api_key_id == key.metadata.key_id
    assert rest.allowed_bank_ids == [workspace.bank_id]
    assert [tenant.schema for tenant in await extension.list_tenants()] == [workspace.schema_name]


async def test_read_scope_blocks_retain_cross_bank_and_bank_mutations(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Read",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "key",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    context = RequestContext(api_key=key.secret)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert (await validator.validate_recall(RecallContext(workspace.bank_id, "query", context))).allowed
        assert not (await validator.validate_retain(RetainContext(workspace.bank_id, [], context))).allowed
        assert not (await validator.validate_recall(RecallContext("another-bank", "query", context))).allowed
        assert not (await validator.validate_create_bank(CreateBankContext(workspace.bank_id, context))).allowed
        for operation in BankWriteOperation:
            assert not (
                await validator.validate_bank_write(BankWriteContext(workspace.bank_id, operation, context))
            ).allowed
    finally:
        _current_schema.reset(token)


async def test_read_key_covers_knowledge_memory_and_reflect(repository: Repository, configured: Settings) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Knowledge",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "key",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    context = RequestContext(api_key=key.secret)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert (await validator.validate_recall(RecallContext(workspace.bank_id, "query", context))).allowed
        for operation in BankReadOperation:
            result = await validator.validate_bank_read(BankReadContext(workspace.bank_id, operation, context))
            operator_read = operation in {BankReadOperation.LIST_WEBHOOKS, BankReadOperation.LIST_WEBHOOK_DELIVERIES}
            assert result.allowed is (not operator_read)
            if operator_read:
                assert result.status_code == 403
                assert (
                    await validator.validate_bank_read(
                        BankReadContext(
                            workspace.bank_id,
                            operation,
                            RequestContext(api_key=ADMIN_SECRET),
                        )
                    )
                ).allowed
        assert (
            await validator.validate_mental_model_get(MentalModelGetContext(workspace.bank_id, "model", context))
        ).allowed
        assert not (
            await validator.validate_mental_model_get(MentalModelGetContext("another-bank", "model", context))
        ).allowed
        tools = frozenset(
            {"recall", "reflect", "get_bank", "get_knowledge_page", "create_knowledge_page", "get_mental_model"}
        )
        assert await validator.filter_mcp_tools(workspace.bank_id, context, tools) == tools - {"create_knowledge_page"}
    finally:
        _current_schema.reset(token)


async def test_memory_write_allows_knowledge_crud_but_not_bank_management(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Writer",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read_write"}],
            },
        ),
        "writer",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
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
            BankWriteOperation.IMPORT_DOCUMENTS,
        }:
            assert (
                await validator.validate_bank_write(BankWriteContext(workspace.bank_id, operation, context))
            ).allowed
        for operation in {BankWriteOperation.DELETE_BANK, BankWriteOperation.UPDATE_BANK_CONFIG}:
            assert not (
                await validator.validate_bank_write(BankWriteContext(workspace.bank_id, operation, context))
            ).allowed
    finally:
        _current_schema.reset(token)


async def test_internal_worker_is_scoped_but_cannot_create_delete_bank(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    context = RequestContext(internal=True, tenant_id=workspace.workspace_id)
    token = _current_schema.set(workspace.schema_name)
    try:
        assert (await validator.validate_retain(RetainContext(workspace.bank_id, [], context))).allowed
        assert not (await validator.validate_retain(RetainContext("another-bank", [], context))).allowed
        assert not (await validator.validate_create_bank(CreateBankContext(workspace.bank_id, context))).allowed
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.bank_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        context.extra_headers["ctxdb-internal-purpose"] = "delete_workspace"
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.bank_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        await repository.delete_workspace(
            ADMIN,
            workspace.bank_id,
            "lease-delete",
            "request",
            expected_id=workspace.workspace_id,
            expected_version=workspace.version,
        )
        operation = await repository.claim_operation()
        assert operation is not None and operation.lease_token is not None
        context.extra_headers.update(
            {"ctxdb-operation-id": operation.operation_id, "ctxdb-lease-token": operation.lease_token}
        )
        assert (
            await validator.validate_bank_write(
                BankWriteContext(workspace.bank_id, BankWriteOperation.DELETE_BANK, context)
            )
        ).allowed
        await repository.complete_operation(operation)
        assert not (
            await validator.validate_bank_write(
                BankWriteContext(workspace.bank_id, BankWriteOperation.DELETE_BANK, context)
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
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", "invalid-synthetic-json-secret")
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
    repository: Repository, configured: Settings, database_url: str
) -> None:
    workspace = await ready_workspace(repository)
    extension = ContextDBTenantExtension({})
    extension.set_context(
        DefaultExtensionContext(
            "",
            memory_engine=cast(
                MemoryEngine, InitializingHost(database_url, _operation_validator=ContextDBOperationValidator({}))
            ),
        )
    )
    assert [tenant.schema for tenant in await extension.list_tenants()] == [workspace.schema_name]


async def test_missing_validator_never_becomes_unrestricted_tenant_routing(
    repository: Repository, configured: Settings
) -> None:
    extension = ContextDBTenantExtension({})
    extension.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    with pytest.raises(RuntimeError, match="operation validator"):
        await extension.list_tenants()
    with pytest.raises(RuntimeError, match="operation validator"):
        await extension.authenticate(RequestContext(api_key="ignored"))


async def test_missing_admission_extension_fails_closed(repository: Repository, configured: Settings) -> None:
    extension = ContextDBTenantExtension({})
    extension.set_context(
        DefaultExtensionContext(
            "", memory_engine=cast(MemoryEngine, PoolHost(repository.pool, ContextDBOperationValidator({})))
        )
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


async def test_mcp_discovery_union_never_becomes_target_write_authorization(repository, configured):
    from hindsight_ext_contextdb.routing import multi_bank_discovery

    first = await ready_workspace(repository, "read_space")
    second = await ready_workspace(repository, "write_space")
    user = await space_user(repository, first.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        user.user_id,
        ApiKeyCreate(
            name="Mixed",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": first.bank_id, "permission": "read"},
                    {"bank_id": second.bank_id, "permission": "read_write"},
                ],
            },
        ),
        "mixed",
    )
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    context = RequestContext(api_key=key.secret)
    tools = frozenset({"recall", "retain", "create_bank"})
    with multi_bank_discovery(True):
        assert await validator.filter_mcp_tools(first.bank_id, context, tools) == {"recall", "retain"}
    assert await validator.filter_mcp_tools(first.bank_id, context, tools) == {"recall"}
    assert await validator.filter_mcp_tools(second.bank_id, context, tools) == {"recall", "retain"}
    for workspace, allowed in ((first, False), (second, True)):
        token = _current_schema.set(workspace.schema_name)
        try:
            assert (await validator.validate_retain(RetainContext(workspace.bank_id, [], context))).allowed is allowed
        finally:
            _current_schema.reset(token)


async def test_native_outer_tools_filter_uses_current_message_after_context_restore(
    repository, configured, monkeypatch
):
    import fastmcp.server.dependencies
    from starlette.requests import Request

    read = await ready_workspace(repository, "Reader")
    write = await ready_workspace(repository, "Writer")
    user = await space_user(repository, read.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        user.user_id,
        ApiKeyCreate(
            name="Mixed",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": read.bank_id, "permission": "read"},
                    {"bank_id": write.bank_id, "permission": "read_write"},
                ],
            },
        ),
        "key",
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", ("Bearer " + key.secret).encode())],
            "contextdb.mcp_discovery": True,
        }
    )
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    validator = ContextDBOperationValidator({})
    validator.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, PoolHost(repository.pool))))
    tools = frozenset({"recall", "retain", "create_bank"})
    # The outer native wrapper is back in the initialized default-bank context;
    # a deliberately stale key argument must never override the actual message.
    stale_context = RequestContext(api_key="stale-initialization-key")
    assert await validator.filter_mcp_tools("default", stale_context, tools) == {"recall", "retain"}
    request.scope["contextdb.mcp_path_bank"] = read.bank_id
    assert await validator.filter_mcp_tools("default", stale_context, tools) == {"recall"}
    request.scope.pop("contextdb.mcp_path_bank")
    request.scope["contextdb.mcp_discovery"] = False
    assert await validator.filter_mcp_tools(read.bank_id, stale_context, tools) == {"recall"}
    assert await validator.filter_mcp_tools(write.bank_id, stale_context, tools) == {"recall", "retain"}


async def test_contextdb_refuses_unfenced_native_startup_migrations(repository, configured):
    host = PoolHost(repository.pool, ContextDBOperationValidator({}))
    host._run_migrations = True
    extension = ContextDBTenantExtension({})
    extension.set_context(DefaultExtensionContext("", memory_engine=cast(MemoryEngine, host)))
    with pytest.raises(RuntimeError, match="RUN_MIGRATIONS_ON_STARTUP=false"):
        await extension.list_tenants()
    host._run_migrations = False
    assert await extension.list_tenants() == []
