"""Strict policy reads distinguish unavailable storage from an unset whitelist."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from starlette.requests import Request

from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.mcp import ContextDBMCPRouting
from hindsight_ext_contextdb.models import ApiKeyCreate, MCPToolPolicy, UserCreate, Workspace
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.routing import bank_target
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace


@pytest.fixture
async def policy_workspace(repository):
    workspace = await ready_workspace(repository, "policy")
    # Only these native columns form the read boundary. Real full migrations
    # and published MCP/SDK operations are covered by the system stories.
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    await repository.pool.execute(
        f'CREATE TABLE "{workspace.schema_name}".banks(bank_id text PRIMARY KEY, config jsonb)'
    )
    await repository.pool.execute(
        f'INSERT INTO "{workspace.schema_name}".banks VALUES($1,$2::jsonb)', workspace.bank_id, "{}"
    )
    return workspace


@pytest.mark.parametrize(
    "stored,expected",
    [
        ({}, None),
        ({"mcp_enabled_tools": None}, None),
        ({"mcp_enabled_tools": []}, frozenset()),
        ({"mcp_enabled_tools": ["get_bank"]}, frozenset({"get_bank"})),
        ({"HINDSIGHT_API_MCP_ENABLED_TOOLS": ["recall"]}, frozenset({"recall"})),
    ],
)
async def test_strict_policy_reads_are_fresh_and_preserve_null_and_empty(
    repository, configured, policy_workspace, monkeypatch, stored, expected
):
    import hindsight_ext_contextdb.mcp as module

    memory = Mock()
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    monkeypatch.setattr(module, "_get_raw_config", lambda: SimpleNamespace(mcp_enabled_tools=None))
    routing = ContextDBMCPRouting(memory, configured)
    with bank_target(policy_workspace.bank_id, schema_name=policy_workspace.schema_name):
        assert await routing._enabled_tools(policy_workspace.bank_id) is None
        await repository.pool.execute(
            f'UPDATE "{policy_workspace.schema_name}".banks SET config=$2::jsonb WHERE bank_id=$1',
            policy_workspace.bank_id,
            json.dumps(stored),
        )
        assert await routing._enabled_tools(policy_workspace.bank_id) == expected
    memory._config_resolver.resolve_full_config.assert_not_called()
    memory._config_resolver.get_bank_config.assert_not_called()


@pytest.mark.parametrize("error", [asyncpg.CannotConnectNowError, OSError, TimeoutError])
async def test_real_repository_policy_query_failure_does_not_become_unrestricted(
    repository, configured, policy_workspace, monkeypatch, error
):
    import hindsight_ext_contextdb.mcp as module

    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    routing = ContextDBMCPRouting(Mock(), configured)
    await repository.pool.execute(
        f'UPDATE "{policy_workspace.schema_name}".banks SET config=$2::jsonb WHERE bank_id=$1',
        policy_workspace.bank_id,
        json.dumps({"mcp_enabled_tools": []}),
    )

    @asynccontextmanager
    async def failed_connection():
        raise error("synthetic-private-policy-diagnostic")
        yield  # pragma: no cover - retain the real pool's async context contract

    with bank_target(policy_workspace.bank_id, schema_name=policy_workspace.schema_name):
        assert await routing._enabled_tools(policy_workspace.bank_id) == frozenset()
        # Exercise the actual Repository read, not a top-level resolver mock:
        # the original resolver swallows exactly this kind of pool failure.
        monkeypatch.setattr(repository, "pool", Mock(acquire=failed_connection))
        with pytest.raises(ToolError, match="MCP tool policy unavailable") as denied:
            await routing._enabled_tools(policy_workspace.bank_id)
        assert "synthetic-private-policy-diagnostic" not in str(denied.value)


@pytest.mark.parametrize("stored", [{"mcp_enabled_tools": "recall"}, {"mcp_enabled_tools": [1]}, []])
async def test_malformed_stored_policy_fails_closed(repository, configured, policy_workspace, monkeypatch, stored):
    import hindsight_ext_contextdb.mcp as module

    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    await repository.pool.execute(
        f'UPDATE "{policy_workspace.schema_name}".banks SET config=$2::jsonb WHERE bank_id=$1',
        policy_workspace.bank_id,
        json.dumps(stored),
    )
    with bank_target(policy_workspace.bank_id, schema_name=policy_workspace.schema_name):
        with pytest.raises(ToolError, match="MCP tool policy unavailable"):
            await ContextDBMCPRouting(Mock(), configured)._enabled_tools(policy_workspace.bank_id)


async def test_missing_bank_policy_is_not_an_unset_policy(repository, configured, policy_workspace, monkeypatch):
    import hindsight_ext_contextdb.mcp as module

    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    with bank_target("missing", schema_name=policy_workspace.schema_name):
        with pytest.raises(ToolError, match="MCP tool policy unavailable"):
            await ContextDBMCPRouting(Mock(), configured)._enabled_tools("missing")


@pytest.mark.parametrize("registered", [False, True])
async def test_custom_bank_listing_cannot_exceed_global_registration(configured, monkeypatch, registered):
    import hindsight_ext_contextdb.mcp as module

    server = FastMCP("global-ceiling-regression")

    @server.tool
    async def get_bank() -> str:
        return "bank"

    if registered:

        @server.tool
        async def list_banks() -> str:
            pytest.fail("Native catalog must not run for a disabled tool")

    workspace = SimpleNamespace(bank_id="test", schema_name="ctxdb_ws_test")
    repository = Mock(
        authenticate=AsyncMock(return_value=ADMIN),
        visible_workspaces=AsyncMock(return_value=[workspace]),
        bank_mcp_policy=AsyncMock(return_value=MCPToolPolicy(mcp_enabled_tools=["list_banks"])),
    )
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {ADMIN_SECRET}".encode())]})
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    monkeypatch.setattr(module, "_get_raw_config", lambda: SimpleNamespace(mcp_enabled_tools=["get_bank"]))
    catalog = AsyncMock()
    monkeypatch.setattr(module, "bank_list", catalog)
    ContextDBMCPRouting(Mock(), configured).install(server)
    async with Client(server) as client:
        assert await client.list_tools() == []
        assert (await client.call_tool("list_banks", {}, raise_on_error=False)).is_error
    catalog.assert_not_awaited()


@pytest.mark.parametrize("multi_bank", [False, True], ids=["single", "root"])
@pytest.mark.parametrize("bank_policy", [None, ["list_banks"]], ids=["inherit", "catalog"])
@pytest.mark.parametrize(
    "global_tools",
    [None, [], ["get_bank"], ["list_banks"], ["list_banks", "create_bank"]],
    ids=["default", "empty", "bank", "catalog", "management"],
)
async def test_native_factory_catalog_discovery_matches_endpoint_and_policy(
    repository: Repository,
    configured: Settings,
    policy_workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    multi_bank: bool,
    bank_policy: list[str] | None,
    global_tools: list[str] | None,
) -> None:
    import fastmcp.server.dependencies
    import hindsight_api.api.mcp as native
    from hindsight_api.api.http import BankListResponse

    import hindsight_ext_contextdb.mcp as module
    import hindsight_ext_contextdb.validator as validator_module

    user = await repository.create_user(ADMIN, UserCreate(name="Catalog reader"), "user")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="Read only",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": policy_workspace.bank_id, "permission": "read"}],
            },
        ),
        "key",
    )
    await repository.pool.execute(
        f'UPDATE "{policy_workspace.schema_name}".banks SET config=$2::jsonb WHERE bank_id=$1',
        policy_workspace.bank_id,
        json.dumps({"mcp_enabled_tools": bank_policy}),
    )
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {issued.secret}".encode())]})
    if not multi_bank:
        request.scope["contextdb.mcp_path_bank"] = policy_workspace.bank_id
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    config = SimpleNamespace(mcp_enabled_tools=global_tools)
    monkeypatch.setattr(native, "_get_raw_config", lambda: config)
    monkeypatch.setattr(module, "_get_raw_config", lambda: config)
    monkeypatch.setattr(native, "load_extension", lambda *args: module.ContextDBMCPExtension({}))
    catalog = AsyncMock(return_value=BankListResponse(banks=[], total=0, limit=100, offset=0))
    monkeypatch.setattr(module, "bank_list", catalog)
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    memory = Mock(
        tenant_extension=Mock(spec=ContextDBTenantExtension),
        _operation_validator=validator,
        _config_resolver=Mock(get_bank_config=AsyncMock(return_value={})),
    )
    # Use the real factory and extension installation: a hand-built registry
    # misses the native empty-intersection fallback to the default tool set.
    server = native.create_mcp_server(memory, multi_bank=multi_bank)
    catalog_allowed = multi_bank and (global_tools is None or "list_banks" in global_tools)
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert ("list_banks" in names) is catalog_allowed
        assert "create_bank" not in names  # A global ceiling never grants write/management authority.
        if global_tools == [] or (bank_policy is not None and not catalog_allowed):
            assert names == set()
        if global_tools == ["get_bank"] and bank_policy is None:
            assert names == {"get_bank"}
        result = await client.call_tool("list_banks", {}, raise_on_error=False)
        assert result.is_error is not catalog_allowed
    if catalog_allowed:
        catalog.assert_awaited_once()
        assert catalog.await_args.kwargs["mcp_tool_bank_ids"] == frozenset({policy_workspace.bank_id})
    else:
        catalog.assert_not_awaited()
