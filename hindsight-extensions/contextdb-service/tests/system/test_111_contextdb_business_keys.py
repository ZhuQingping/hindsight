"""All-workspace business access never becomes administrator authority.

The administrator stays deployment configuration. Two business keys belonging
to one user can be independently revoked while an all-workspace key sees newly
created spaces. Native memory reads use only the published Hindsight SDK/MCP.
"""

from __future__ import annotations

import json
import secrets

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException, UnauthorizedException

from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


async def test_all_workspace_business_key_covers_future_spaces_without_management(
    contextdb_deployment: ContextDBDeployment,
) -> None:
    base = contextdb_deployment.server.url
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as management:
        user_response = await management.post("/users", json={"name": "All-space application"})
        assert user_response.status_code == 201, user_response.text
        user = user_response.json()
        assert not {"role", "workspace_access", "workspace_ids"} & user.keys()
        issued = await management.post(
            f"/users/{user['user_id']}/keys",
            json={"name": "All reader", "authorization": {"mode": "all", "permission": "read"}},
        )
        assert issued.status_code == 201, issued.text
        key = issued.json()
        client = Hindsight(base_url=base, api_key=key["secret"])
        try:
            old_spaces = {bank.bank_id for bank in (await client.banks.list_banks(limit=1000)).banks}
            created = await management.post(
                "/workspaces",
                json={"name": "future_" + secrets.token_hex(8)},
            )
            assert created.status_code == 201, created.text

            bank = created.json()["bank_id"]
            assert bank not in old_spaces
            assert bank in {item.bank_id for item in (await client.banks.list_banks(limit=1000)).banks}
            assert (await client.arecall(bank_id=bank, query="An empty future workspace")).results == []
            with pytest.raises(ForbiddenException):
                await client.aretain(bank_id=bank, content="All reader cannot write")
            async with httpx.AsyncClient(base_url=base, headers={"Authorization": "Bearer " + key["secret"]}) as raw:
                for path in ("/admin/identity", "/users", "/workspaces", "/workspaces/" + bank):
                    assert (await raw.get("/ext/contextdb/v1" + path)).status_code == 403
                for path, body in (
                    ("/workspaces", {"name": "Forbidden"}),
                    ("/users", {"name": "Forbidden"}),
                    (f"/users/{user['user_id']}/keys", {"name": "Forbidden", "access_mode": "all"}),
                ):
                    assert (await raw.post("/ext/contextdb/v1" + path, json=body)).status_code == 403
                assert (await raw.delete("/ext/contextdb/v1/workspaces/" + bank)).status_code == 403
                assert (await raw.delete(f"/v1/default/banks/{bank}")).status_code == 403
                # all expands data visibility, never operational credentials
                # carried in native archives or webhook delivery configuration.
                assert (await raw.get(f"/v1/default/banks/{bank}/webhooks")).status_code == 403
                assert (await raw.post(f"/v1/default/banks/{bank}/transfer/export")).status_code == 403
                assert (await raw.post(f"/v1/default/banks/{bank}/document-transfer/export")).status_code == 403
                assert (await raw.get(f"/v1/default/files/download/banks/{bank}/known-export.zip")).status_code == 403
                assert (await raw.put(f"/v1/default/banks/{bank}", json={"name": "Forbidden"})).status_code in {
                    403,
                    405,
                }
            async with Client(base + f"/mcp/{bank}/", auth=key["secret"]) as mcp:
                names = {tool.name for tool in await mcp.list_tools()}
                assert {"recall", "reflect", "get_bank", "get_knowledge_base_tree"} <= names
                assert {
                    "retain",
                    "sync_retain",
                    "create_bank",
                    "delete_bank",
                    "clear_memories",
                    "update_bank",
                    "list_banks",
                }.isdisjoint(names)
                recalled = await mcp.call_tool("recall", {"query": "Empty future workspace"})
                assert not recalled.is_error
                assert json.loads(recalled.content[0].text)["results"] == []
            # Native single-bank MCP intentionally excludes list_banks. Its
            # multi-bank counterpart must expose exactly the current visible
            # spaces, including the space created after this same Key was issued.
            async with Client(base + "/mcp/", auth=key["secret"]) as multi:
                assert "list_banks" in {tool.name for tool in await multi.list_tools()}
                listed = await multi.call_tool("list_banks", {})
                assert not listed.is_error
                visible = json.loads(listed.content[0].text)
                assert bank in {item["bank_id"] for item in visible["banks"]}
                assert visible["total"] >= len(old_spaces) + 1
        finally:
            await client.aclose()


async def test_revoke_one_key_preserves_sibling_and_old_mcp_session_cannot_reuse_it(
    contextdb_deployment: ContextDBDeployment,
) -> None:
    base = contextdb_deployment.server.url
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as management:
        created = await management.post(
            "/workspaces",
            json={"name": "key_rotation_" + secrets.token_hex(8)},
        )
        assert created.status_code == 201, created.text

        bank = created.json()["bank_id"]
        user_response = await management.post("/users", json={"name": "Rotating application"})
        assert user_response.status_code == 201, user_response.text
        user_id = user_response.json()["user_id"]
        keys = []
        for name in ("Old", "Replacement"):
            issued = await management.post(
                f"/users/{user_id}/keys",
                json={
                    "name": name,
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [{"bank_id": workspace_id, "permission": "read"} for workspace_id in [bank]],
                    },
                },
            )
            assert issued.status_code == 201, issued.text
            keys.append(issued.json())
        listed = await management.get(f"/users/{user_id}/keys")
        assert listed.status_code == 200, listed.text
        assert "secret" not in listed.json() and all("secret" not in item for item in listed.json()["items"])
        old = Hindsight(base_url=base, api_key=keys[0]["secret"])
        replacement = Hindsight(base_url=base, api_key=keys[1]["secret"])
        try:
            transport = StreamableHttpTransport(
                base + f"/mcp/{bank}/", headers={"Authorization": "Bearer " + keys[0]["secret"]}
            )
            revoked_proved = False
            try:
                async with Client(transport) as mcp:
                    assert not (await mcp.call_tool("recall", {"query": "Before revocation"})).is_error
                    session = transport.get_session_id()
                    assert session
                    revoked = await management.delete(f"/users/{user_id}/keys/{keys[0]['key_id']}")
                    assert revoked.status_code in {200, 204}, revoked.text
                    with pytest.raises(UnauthorizedException):
                        await old.arecall(bank_id=bank, query="Revoked key")
                    assert (await replacement.arecall(bank_id=bank, query="Sibling key survives")).results == []
                    with pytest.raises(httpx.HTTPStatusError) as unauthorized:
                        await mcp.call_tool("recall", {"query": "Old session cannot retain authority"})
                    assert unauthorized.value.response.status_code == 401
                    revoked_proved = True
                    assert transport.get_session_id() == session
            except httpx.HTTPStatusError as error:
                # The transport also rejects DELETE on exit with the revoked
                # credential; it must not obscure the earlier denial proof.
                assert revoked_proved and error.response.status_code == 401
        finally:
            await old.aclose()
            await replacement.aclose()
