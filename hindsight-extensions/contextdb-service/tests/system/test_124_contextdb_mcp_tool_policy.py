"""Bank tool policy is enforced independently of business config visibility."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field

import httpx
import pytest
from contextbase_client import ContextBase
from contextbase_client_api.models.bank_config_update import BankConfigUpdate
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment
from .support.mcp import MutableBearer

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def restore_bank_policies(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> AsyncIterator[None]:
    # The deployment is session-scoped and its directory retains earlier Banks.
    # Restore these freshly created Banks even when an assertion fails, so later
    # directory stories do not inherit this test's restrictive tool policies.
    async with aclosing(
        ContextBase(
            base_url=contextdb_deployment.server.url,
            api_key=contextdb_deployment.headers["Authorization"].removeprefix("Bearer "),
        )
    ) as admin:
        try:
            yield
        finally:
            # The convenience method omits None; the generated public SDK
            # preserves an explicit null inside the updates dictionary.
            restored = await asyncio.gather(
                admin.banks.update_bank_config(
                    contextdb_clients.bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": None})
                ),
                admin.banks.update_bank_config(
                    contextdb_clients.other_bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": None})
                ),
            )
            assert all(config.overrides.get("mcp_enabled_tools") is None for config in restored)


@dataclass
class IssuedKey:
    user_id: str
    key_id: str
    secret: str = field(repr=False)


async def issue_key(deployment: ContextDBDeployment, banks: list[str]) -> IssuedKey:
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
    ) as management:
        user = await management.post("/users", json={"name": "Policy " + secrets.token_hex(5)})
        assert user.status_code == 201, user.text
        user_id = user.json()["user_id"]
        issued = await management.post(
            f"/users/{user_id}/keys",
            json={
                "name": "Policy probe",
                "authorization": {
                    "mode": "selected",
                    "workspaces": [{"bank_id": bank, "permission": "read_write"} for bank in banks],
                },
            },
        )
        assert issued.status_code == 201, issued.text
        return IssuedKey(user_id, issued.json()["key_id"], issued.json()["secret"])


@pytest.mark.parametrize("role", ["read", "read_write", "admin"])
@pytest.mark.parametrize("endpoint", ["single", "root"])
async def test_bank_policy_limits_discovery_and_calls_without_exposing_config(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    role: str,
    endpoint: str,
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    admin_key = deployment.headers["Authorization"].removeprefix("Bearer ")
    credential = {"admin": admin_key, "read": clients.read_only_key, "read_write": clients.own_key}[role]
    async with aclosing(ContextBase(base_url=deployment.server.url, api_key=admin_key)) as admin:
        await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=["get_bank", "list_directives"])
        # Admin sees both spaces on the root endpoint, so constrain the second
        # space too instead of mistaking a legitimate union for a policy leak.
        await admin.aupdate_bank_config(clients.other_bank_id, mcp_enabled_tools=[])
        suffix = f"/mcp/{clients.bank_id}/" if endpoint == "single" else "/mcp/"
        target = {} if endpoint == "single" else {"bank_id": clients.bank_id}
        async with Client(deployment.server.url + suffix, auth=credential) as mcp:
            names = {tool.name for tool in await mcp.list_tools()}
            if role == "admin" and endpoint == "root":
                # This session fixture may contain earlier stories' Banks; root
                # Admin discovery legitimately includes their allowed tools too.
                assert {"get_bank", "list_directives"} <= names
            else:
                assert names == {"get_bank", "list_directives"}
            assert not (await mcp.call_tool("get_bank", target)).is_error
            assert not (await mcp.call_tool("list_directives", target)).is_error
            for tool, arguments in (
                ("list_memories", target),
                ("create_directive", {**target, "name": "Forbidden", "content": "Synthetic forbidden write"}),
            ):
                assert (await mcp.call_tool(tool, arguments, raise_on_error=False)).is_error
        directives = await admin.alist_directives(clients.bank_id)
        assert directives.total == 0 and directives.items == []
        if role != "admin":
            async with aclosing(ContextBase(base_url=deployment.server.url, api_key=credential)) as business:
                config = await business.aget_bank_config(clients.bank_id)
                assert config["config"] == {} and config["overrides"] == {}


async def test_root_union_and_bank_listing_apply_the_actual_target_policy(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    key = await issue_key(deployment, [clients.bank_id, clients.other_bank_id])
    async with aclosing(
        ContextBase(base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer "))
    ) as admin:
        await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=["get_bank", "list_banks"])
        await admin.aupdate_bank_config(clients.other_bank_id, mcp_enabled_tools=["list_directives"])
        async with Client(deployment.server.url + f"/mcp/{clients.bank_id}/", auth=key.secret) as single:
            assert {tool.name for tool in await single.list_tools()} == {"get_bank"}
            assert (await single.call_tool("list_banks", {}, raise_on_error=False)).is_error
        async with Client(deployment.server.url + "/mcp/", auth=key.secret) as mcp:
            assert {tool.name for tool in await mcp.list_tools()} == {"get_bank", "list_banks", "list_directives"}

            async def target(bank: str, allowed: str, forbidden: str) -> None:
                assert not (await mcp.call_tool(allowed, {"bank_id": bank})).is_error
                assert (await mcp.call_tool(forbidden, {"bank_id": bank}, raise_on_error=False)).is_error

            await asyncio.gather(
                target(clients.bank_id, "get_bank", "list_directives"),
                target(clients.other_bank_id, "list_directives", "get_bank"),
            )
            # The extension's custom list_banks branch must not bypass policy;
            # counts and pagination describe only Banks enabling this tool.
            listed = json.loads((await mcp.call_tool("list_banks", {})).content[0].text)
            assert listed["total"] == 1 and [bank["bank_id"] for bank in listed["banks"]] == [clients.bank_id]
            second_page = json.loads((await mcp.call_tool("list_banks", {"limit": 1, "offset": 1})).content[0].text)
            assert second_page == {"banks": [], "total": 1, "limit": 1, "offset": 1}
            await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=[])
            assert (await mcp.call_tool("list_banks", {}, raise_on_error=False)).is_error
            assert {tool.name for tool in await mcp.list_tools()} == {"list_directives"}


@pytest.mark.parametrize("endpoint", ["single", "root"])
@pytest.mark.parametrize("role", ["read", "read_write"])
async def test_empty_unset_and_write_policies_preserve_operation_permissions(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    endpoint: str,
    role: str,
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    credential = clients.read_only_key if role == "read" else clients.own_key
    suffix = f"/mcp/{clients.bank_id}/" if endpoint == "single" else "/mcp/"
    target = {} if endpoint == "single" else {"bank_id": clients.bank_id}
    async with (
        aclosing(
            ContextBase(
                base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
            )
        ) as admin,
        Client(deployment.server.url + suffix, auth=credential) as mcp,
    ):
        await admin.banks.update_bank_config(clients.bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": None}))
        assert "get_bank" in {tool.name for tool in await mcp.list_tools()}
        assert not (await mcp.call_tool("get_bank", target)).is_error
        await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=[])
        assert await mcp.list_tools() == []
        assert (await mcp.call_tool("get_bank", target, raise_on_error=False)).is_error
        await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=["create_directive"])
        assert {tool.name for tool in await mcp.list_tools()} == (
            {"create_directive"} if role == "read_write" else set()
        )
        created = await mcp.call_tool(
            "create_directive",
            {**target, "name": "Allowed writer", "content": "Synthetic allowed write"},
            raise_on_error=False,
        )
        assert created.is_error is (role == "read")
        directives = await admin.alist_directives(clients.bank_id)
        assert directives.total == (1 if role == "read_write" else 0)


async def test_existing_session_rechecks_policy_current_key_and_revocation(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    key = await issue_key(deployment, [clients.bank_id])
    auth = MutableBearer(key.secret)
    transport = StreamableHttpTransport(deployment.server.url + f"/mcp/{clients.bank_id}/", auth=auth)
    revocation_proved = False
    try:
        async with (
            aclosing(
                ContextBase(
                    base_url=deployment.server.url, api_key=deployment.headers["Authorization"].removeprefix("Bearer ")
                )
            ) as admin,
            httpx.AsyncClient(
                base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers
            ) as management,
            Client(transport) as mcp,
        ):
            await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=["get_bank", "create_directive"])
            assert {tool.name for tool in await mcp.list_tools()} == {"get_bank", "create_directive"}
            session = transport.get_session_id()
            assert session
            auth.credential = clients.read_only_key
            assert {tool.name for tool in await mcp.list_tools()} == {"get_bank"}
            assert (
                await mcp.call_tool("create_directive", {"name": "Denied", "content": "No write"}, raise_on_error=False)
            ).is_error
            auth.credential = clients.other_key
            assert (await mcp.call_tool("get_bank", {}, raise_on_error=False)).is_error
            auth.credential = key.secret
            assert not (await mcp.call_tool("get_bank", {})).is_error
            assert (await admin.alist_directives(clients.bank_id)).total == 0
            revoked = await management.delete(f"/users/{key.user_id}/keys/{key.key_id}")
            assert revoked.status_code == 204
            with pytest.raises(httpx.HTTPStatusError) as denied:
                await mcp.call_tool("get_bank", {})
            assert denied.value.response.status_code == 401
            assert transport.get_session_id() == session
            revocation_proved = True
    except httpx.HTTPStatusError as error:
        # A rejected POST also terminates the client's background transport;
        # teardown may repeat that same 401. Never suppress a pre-proof error.
        assert revocation_proved and error.response.status_code == 401
    logs = deployment.server.logs()
    assert "Failed to load bank config" not in logs
    assert "Audit config resolution failed" not in logs
