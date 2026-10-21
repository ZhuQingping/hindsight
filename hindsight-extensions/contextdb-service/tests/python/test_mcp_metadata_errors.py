"""MCP metadata failures are safe at the actual protocol boundary, not just HTTP."""

from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest
from fastmcp import Client, FastMCP
from mcp.shared.exceptions import McpError
from starlette.requests import Request

from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.mcp import ContextDBMCPRouting
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension

from .support.identities import ADMIN, ADMIN_SECRET

SENTINEL = "synthetic-private-pg-diagnostic-for-regression"


@pytest.mark.parametrize(
    "operation,stage",
    [
        ("list", "repository"),
        ("list", "authenticate"),
        ("list", "visible"),
        ("call", "repository"),
        ("call", "authenticate"),
        ("banks", "directory"),
    ],
)
async def test_mcp_metadata_failures_hide_details_without_falling_through(monkeypatch, operation, stage):
    import hindsight_ext_contextdb.mcp as module

    settings = Settings(instance_id="test", cloud_tenant_id="test", pepper="synthetic-test-pepper-32-bytes-long")
    repository = Mock(authenticate=AsyncMock(return_value=ADMIN), visible_workspaces=AsyncMock(return_value=[]))
    provider = AsyncMock(return_value=repository)
    if stage == "repository":
        provider.side_effect = asyncpg.PostgresError(SENTINEL)
    elif stage == "authenticate":
        repository.authenticate.side_effect = asyncpg.PostgresError(SENTINEL)
    elif stage == "visible":
        repository.visible_workspaces.side_effect = asyncpg.PostgresError(SENTINEL)
    monkeypatch.setattr(module, "repository_for", provider)
    if stage == "directory":
        repository.visible_workspaces.side_effect = asyncpg.PostgresError(SENTINEL)
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {ADMIN_SECRET}".encode())],
            "contextdb.mcp_path_bank": "test",
        }
    )
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    server = FastMCP("metadata-failure-regression")
    reached = Mock()

    @server.tool
    async def recall() -> str:
        reached()
        return "unreachable"

    @server.tool
    async def list_banks() -> str:
        reached()
        return "unreachable"

    server.add_middleware(ContextDBMCPRouting(Mock(tenant_extension=Mock(spec=ContextDBTenantExtension)), settings))
    async with Client(server) as client:
        if operation == "list":
            with pytest.raises(McpError) as error:
                await client.list_tools()
            message = str(error.value)
        else:
            result = await client.call_tool(
                "list_banks" if operation == "banks" else "recall", {}, raise_on_error=False
            )
            assert result.is_error
            message = str(result.content)
    assert SENTINEL not in message
    assert "Management metadata unavailable" in message
    reached.assert_not_called()


@pytest.mark.parametrize("hook", ["tenant", "tenant_mcp", "config", "validator", "filter", "list_scope"])
@pytest.mark.parametrize("failure", [asyncpg.PostgresError, asyncpg.InterfaceError, ConnectionError, TimeoutError])
async def test_metadata_hook_failures_remain_closed_and_do_not_expose_diagnostics(monkeypatch, hook, failure):
    from hindsight_api.extensions.tenant import AuthenticationError
    from hindsight_api.models import RequestContext

    import hindsight_ext_contextdb.tenant as tenant_module
    import hindsight_ext_contextdb.validator as validator_module
    from hindsight_ext_contextdb.models import ServiceError
    from hindsight_ext_contextdb.routing import bank_target
    from hindsight_ext_contextdb.validator import ContextDBOperationValidator

    for name, value in {
        "CONTEXTDB_INSTANCE_ID": "test",
        "CONTEXTDB_CLOUD_TENANT_ID": "test",
        "CONTEXTDB_KEY_PEPPER": "synthetic-test-pepper-32-bytes-long",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(tenant_module, "repository_for", AsyncMock(side_effect=failure(SENTINEL)))
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(side_effect=failure(SENTINEL)))
    tenant = ContextDBTenantExtension({})
    tenant.transport_authorization_installed = True
    monkeypatch.setattr(tenant, "_engine", Mock(return_value=Mock()))
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    context = RequestContext(api_key=ADMIN_SECRET)
    with bank_target("test"):
        if hook in {"tenant", "tenant_mcp"}:
            with pytest.raises(AuthenticationError, match="Management metadata unavailable") as error:
                await (tenant.authenticate(context) if hook == "tenant" else tenant.authenticate_mcp(context))
            assert SENTINEL not in str(error.value)
        elif hook == "config":
            assert await tenant.get_allowed_config_fields(context, "test") == set()
        elif hook == "validator":
            result = await validator._authorize(context, "test", None)
            assert not result.allowed and result.status_code == 503
            assert SENTINEL not in result.reason
        elif hook == "filter":
            assert await validator.filter_mcp_tools("test", context, frozenset({"recall"})) == frozenset()
        else:
            with pytest.raises(ServiceError) as error:
                await validator.bank_list_scope(context)
            assert error.value.status == 503 and SENTINEL not in error.value.message


async def test_native_tool_failure_is_not_rewritten_as_a_metadata_error(monkeypatch):
    import hindsight_ext_contextdb.mcp as module

    settings = Settings(instance_id="test", cloud_tenant_id="test", pepper="synthetic-test-pepper-32-bytes-long")
    monkeypatch.setattr(
        module,
        "repository_for",
        AsyncMock(
            return_value=Mock(
                authenticate=AsyncMock(return_value=ADMIN),
                visible_workspaces=AsyncMock(return_value=[Mock(bank_id="test")]),
            )
        ),
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {ADMIN_SECRET}".encode())],
            "contextdb.mcp_path_bank": "test",
        }
    )
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    server = FastMCP("native-error-boundary")

    @server.tool
    async def recall() -> str:
        raise OSError("synthetic-native-tool-failure")

    server.add_middleware(ContextDBMCPRouting(Mock(tenant_extension=Mock(spec=ContextDBTenantExtension)), settings))
    async with Client(server) as client:
        result = await client.call_tool("recall", {}, raise_on_error=False)
    assert result.is_error
    assert "synthetic-native-tool-failure" in str(result.content)
    assert "Management metadata unavailable" not in str(result.content)


@pytest.mark.parametrize("stage", ["backend", "catalog", "hydrate"])
@pytest.mark.parametrize("failure", [OSError, asyncpg.PostgresError])
async def test_native_bank_listing_failure_keeps_its_original_error(monkeypatch, stage, failure):
    from hindsight_api.engine.retain import bank_utils

    import hindsight_ext_contextdb.mcp as module

    native_message = "synthetic-native-bank-list-failure"
    settings = Settings(instance_id="test", cloud_tenant_id="test", pepper="synthetic-test-pepper-32-bytes-long")
    repository = Mock(
        authenticate=AsyncMock(return_value=ADMIN),
        visible_workspaces=AsyncMock(return_value=[Mock(bank_id="test")]),
    )
    memory = Mock(
        _get_backend=AsyncMock(return_value=Mock()),
        _authenticate_tenant=AsyncMock(),
        list_banks=AsyncMock(),
        tenant_extension=Mock(spec=ContextDBTenantExtension),
    )
    catalog = AsyncMock(
        return_value=[
            {"bank_id": "test", "name": "test", "disposition": {"skepticism": 3, "literalism": 3, "empathy": 3}}
        ]
    )
    if stage == "backend":
        memory._get_backend.side_effect = failure(native_message)
    elif stage == "catalog":
        catalog.side_effect = failure(native_message)
    else:
        memory.list_banks.side_effect = failure(native_message)
    monkeypatch.setattr(bank_utils, "list_banks_among", catalog)
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {ADMIN_SECRET}".encode())]})
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    server = FastMCP("native-bank-list-boundary")

    @server.tool
    async def list_banks() -> str:
        return "unreachable"

    server.add_middleware(ContextDBMCPRouting(memory, settings))
    async with Client(server) as client:
        result = await client.call_tool("list_banks", {}, raise_on_error=False)
    assert result.is_error
    assert native_message in str(result.content)
    assert "Management metadata unavailable" not in str(result.content)
