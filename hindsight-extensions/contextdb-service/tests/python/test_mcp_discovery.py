"""Discovery SQL stays bounded by messages, while tool execution keeps target auth."""

from unittest.mock import AsyncMock, Mock

import pytest
from hindsight_api.models import RequestContext

from hindsight_ext_contextdb.models import ApiKeyCreate, ApiKeyPatch, ServiceError, UserCreate
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.identities import ADMIN, ready_workspace


@pytest.mark.parametrize("space_count", [1, 10, 1000])
@pytest.mark.parametrize("access_mode", ["all", "selected"])
async def test_discovery_uses_three_metadata_queries_without_per_space_lookups(
    repository, configured, monkeypatch, space_count, access_mode
):
    import fastmcp.server.dependencies
    from starlette.requests import Request

    import hindsight_ext_contextdb.validator as validator_module

    await repository.pool.execute(
        "INSERT INTO ctxdb_meta.workspaces(workspace_id,bank_id,schema_name,state) "
        "SELECT lpad(to_hex(i),32,'0'),'ws_'||i,'ctxdb_ws_ws_'||i,'active' "
        "FROM generate_series(1,$1::integer) AS i",
        space_count,
    )
    user = await repository.create_user(ADMIN, UserCreate(name="MCP"), "user")
    authorization = (
        {"mode": "all", "permission": "read_write"}
        if access_mode == "all"
        else {
            "mode": "selected",
            "workspaces": [
                {"bank_id": f"ws_{i}", "permission": "read" if i < space_count else "read_write"}
                for i in range(1, space_count + 1)
            ],
        }
    )
    issued = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="mixed", authorization=authorization), "key"
    )
    pool = repository.pool
    proxy = Mock(wraps=pool)
    for name in ("fetchrow", "fetchval", "fetch", "execute"):
        setattr(proxy, name, AsyncMock(wraps=getattr(pool, name)))
    repository.pool = proxy
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {issued.secret}".encode())],
            "contextdb.mcp_discovery": True,
        }
    )
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    available = frozenset({"recall", "retain", "create_bank"})
    # The outer native filter may run after context reset, using stale init data.
    assert await validator.filter_mcp_tools("default", RequestContext(api_key="stale"), available) == {
        "recall",
        "retain",
    }
    assert proxy.fetchrow.await_count == 1  # authentication, record_use=False
    assert proxy.fetchval.await_count == 1  # directory binding
    assert proxy.fetch.await_count == 1  # active visible directory
    proxy.execute.assert_not_called()  # no telemetry update in this entry
    if access_mode == "selected":
        unscoped = await repository.authenticate(issued.secret)
        assert len(unscoped.workspace_permissions) == space_count
        targeted = await repository.authenticate(issued.secret, "ws_1")
        assert len(targeted.workspace_permissions) == 1


async def test_directory_union_is_not_execution_authority_and_rechecks_current_key(repository, configured, monkeypatch):
    import fastmcp.server.dependencies
    from starlette.requests import Request

    import hindsight_ext_contextdb.validator as validator_module

    first = await ready_workspace(repository, "first")
    second = await ready_workspace(repository, "second")
    user = await repository.create_user(ADMIN, UserCreate(name="MCP"), "user")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="mixed",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": first.bank_id, "permission": "read"},
                    {"bank_id": second.bank_id, "permission": "read_write"},
                ],
            },
        ),
        "key",
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {issued.secret}".encode())],
            "contextdb.mcp_discovery": True,
        }
    )
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    tools = frozenset({"recall", "retain"})
    context = RequestContext(api_key=issued.secret)
    assert await validator.filter_mcp_tools("default", context, tools) == tools
    request.scope["contextdb.mcp_path_bank"] = first.bank_id
    assert await validator.filter_mcp_tools("default", context, tools) == {"recall"}
    request.scope.pop("contextdb.mcp_path_bank")
    await repository.update_key(
        ADMIN,
        user.user_id,
        issued.metadata.key_id,
        ApiKeyPatch(
            authorization={"mode": "selected", "workspaces": [{"bank_id": first.bank_id, "permission": "read"}]}
        ),
        issued.metadata.version,
        "change",
    )
    assert await validator.filter_mcp_tools("default", context, tools) == {"recall"}
    with pytest.raises(ServiceError):
        await repository.authenticate(issued.secret, second.bank_id)
    await repository.revoke_key(ADMIN, user.user_id, issued.metadata.key_id, "revoke")
    assert await validator.filter_mcp_tools("default", context, tools) == frozenset()


async def test_empty_active_directory_advertises_no_scopes(repository, configured, monkeypatch):
    import fastmcp.server.dependencies
    from starlette.requests import Request

    import hindsight_ext_contextdb.validator as validator_module

    user = await repository.create_user(ADMIN, UserCreate(name="Empty"), "user")
    issued = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="all", authorization={"mode": "all"}), "key"
    )
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {issued.secret}".encode())],
            "contextdb.mcp_discovery": True,
        }
    )
    monkeypatch.setattr(fastmcp.server.dependencies, "get_http_request", lambda: request)
    monkeypatch.setattr(validator_module, "repository_for", AsyncMock(return_value=repository))
    validator = ContextDBOperationValidator({})
    validator.set_context(Mock())
    assert (
        await validator.filter_mcp_tools(
            "default", RequestContext(api_key=issued.secret), frozenset({"recall", "retain"})
        )
        == frozenset()
    )
