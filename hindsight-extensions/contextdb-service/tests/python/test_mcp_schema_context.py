"""The native MCP configuration filter must share the authorized Bank schema."""

import asyncio
from contextvars import ContextVar
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp import Client, FastMCP
from hindsight_api.engine.audit import AuditLogger
from hindsight_api.engine.memory_engine import get_current_schema
from hindsight_api.mcp_tools import MCPToolsConfig, _apply_audit_logging, _apply_bank_tool_filtering
from hindsight_api.models import RequestContext
from mcp.shared.exceptions import McpError
from starlette.requests import Request

from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.mcp import ContextDBMCPExtension
from hindsight_ext_contextdb.models import ApiKeyCreate, UserCreate, Workspace
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace


@pytest.mark.parametrize("operation", ["list", "call"])
@pytest.mark.parametrize("permission", ["read", "read_write", "admin"])
@pytest.mark.parametrize("failure", [False, True])
async def test_native_tool_filter_reads_the_authorized_schema(
    repository: Repository,
    configured: Settings,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    permission: str,
    failure: bool,
) -> None:
    import fastmcp.server.dependencies

    import hindsight_ext_contextdb.mcp as module
    import hindsight_ext_contextdb.validator as validator_module

    workspace = await ready_workspace(repository, "schema_probe")
    user = await repository.create_user(ADMIN, UserCreate(name="Schema probe"), "user")
    key = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="probe",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": workspace.bank_id, "permission": "read" if permission == "read" else "read_write"}
                ],
            },
        ),
        "key",
    )
    credential = ADMIN_SECRET if permission == "admin" else key.secret
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {credential}".encode())],
            "contextdb.mcp_path_bank": workspace.bank_id,
        }
    )
    monkeypatch.setattr(module, "get_http_request", lambda: request)
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    observed: list[str] = []

    async def read_config(*args: Any, **kwargs: Any) -> dict[str, list[str]]:
        observed.append(get_current_schema())
        if failure:
            raise RuntimeError("synthetic-config-failure")
        return {"mcp_enabled_tools": ["recall"]}

    memory = Mock(
        tenant_extension=Mock(spec=ContextDBTenantExtension),
        _operation_validator=validator,
        _config_resolver=Mock(get_bank_config=AsyncMock(side_effect=read_config)),
    )

    async def read_audit(bank: str, context: RequestContext | None) -> bool:
        observed.append(get_current_schema())
        return False

    memory.audit_logger = AuditLogger(lambda: None, get_current_schema, False, [], read_audit)
    server = FastMCP("schema-context-regression")

    @server.tool
    async def recall() -> str:
        return get_current_schema()

    config = MCPToolsConfig(bank_id_resolver=lambda: workspace.bank_id)
    _apply_bank_tool_filtering(server, memory, config)
    _apply_audit_logging(server, memory, config)
    ContextDBMCPExtension({}).register_tools(server, memory)
    async with Client(server) as client:
        if operation == "list":
            if failure:
                with pytest.raises(McpError, match="synthetic-config-failure"):
                    await client.list_tools()
            else:
                assert [tool.name for tool in await client.list_tools()] == ["recall"]
        else:
            result = await client.call_tool("recall", raise_on_error=False)
            if failure:
                assert result.is_error
            else:
                assert result.data == workspace.schema_name
    assert observed and set(observed) == {workspace.schema_name}
    assert get_current_schema() == "public"


@pytest.mark.parametrize("crossed_permissions", [False, True])
async def test_root_union_and_concurrent_requests_use_each_spaces_config_and_scopes(
    repository: Repository, configured: Settings, monkeypatch: pytest.MonkeyPatch, crossed_permissions: bool
) -> None:
    import fastmcp.server.dependencies
    from hindsight_api.api.mcp import get_current_bank_id

    import hindsight_ext_contextdb.mcp as module
    import hindsight_ext_contextdb.validator as validator_module

    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    user = await repository.create_user(ADMIN, UserCreate(name="Mixed probe"), "user")
    key = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="mixed",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": first.bank_id, "permission": "read" if crossed_permissions else "read_write"},
                    {"bank_id": second.bank_id, "permission": "read_write"},
                ],
            },
        ),
        "key",
    )
    request_var: ContextVar[Request] = ContextVar("test_current_request")
    request_var.set(Request({"type": "http", "headers": [(b"authorization", f"Bearer {key.secret}".encode())]}))
    monkeypatch.setattr(module, "get_http_request", request_var.get)
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", request_var.get)
    monkeypatch.setattr(module, "repository_for", AsyncMock(return_value=repository))
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    spaces = {first.bank_id: first, second.bank_id: second}

    async def read_config(bank_id: str, context: RequestContext) -> dict[str, list[str]]:
        await asyncio.sleep(0)  # Deliberately interleave different target contexts.
        assert get_current_schema() == spaces[bank_id].schema_name
        return {"mcp_enabled_tools": ["retain" if bank_id == first.bank_id else "recall"]}

    memory = Mock(
        tenant_extension=Mock(spec=ContextDBTenantExtension),
        _operation_validator=validator,
        _config_resolver=Mock(get_bank_config=AsyncMock(side_effect=read_config)),
    )
    server = FastMCP("root-union-regression")

    @server.tool
    async def recall() -> str:
        return get_current_schema()

    @server.tool
    async def retain() -> str:
        return get_current_schema()

    _apply_bank_tool_filtering(server, memory, MCPToolsConfig(bank_id_resolver=get_current_bank_id))
    ContextDBMCPExtension({}).register_tools(server, memory)
    async with Client(server) as client:
        assert {tool.name for tool in await client.list_tools()} == (
            {"recall"} if crossed_permissions else {"retain", "recall"}
        )

    async def probe(workspace: Workspace, expected: set[str]) -> None:
        request_var.set(
            Request(
                {
                    "type": "http",
                    "headers": [(b"authorization", f"Bearer {key.secret}".encode())],
                    "contextdb.mcp_path_bank": workspace.bank_id,
                }
            )
        )
        async with Client(server) as client:
            assert {tool.name for tool in await client.list_tools()} == expected
            if expected:
                result = await client.call_tool(next(iter(expected)))
                assert result.data == workspace.schema_name
        assert get_current_schema() == "public"
        assert get_current_bank_id() is None

    await asyncio.gather(probe(first, set() if crossed_permissions else {"retain"}), probe(second, {"recall"}))
    assert get_current_schema() == "public"
    assert get_current_bank_id() is None
