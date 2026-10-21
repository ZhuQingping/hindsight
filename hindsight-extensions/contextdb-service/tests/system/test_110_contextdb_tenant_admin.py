"""One unchanged Key crosses authorized schemas; live changes affect REST and old MCP sessions."""

from __future__ import annotations

import json
import secrets

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException, UnauthorizedException
from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact

from .support.clients import workspace_condition_headers
from .support.deployment import ContextDBDeployment

# Register the fixture explicitly so combined collection keeps both Worker modes.

pytestmark = pytest.mark.asyncio


async def test_multi_space_live_keys_admin_and_lifecycle(contextdb_deployment: ContextDBDeployment, llm):
    base = contextdb_deployment.server.url
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as control:
        admin_key = contextdb_deployment.headers["Authorization"].removeprefix("Bearer ")
        async with httpx.AsyncClient(
            base_url=base + "/ext/contextdb/v1", headers={"Authorization": "Bearer " + admin_key}
        ) as management:
            assert (await management.get("/admin/identity")).json()["role"] == "admin"
            banks = []
            for letter in "ABC":
                created = await control.post(
                    "/workspaces",
                    json={"name": letter + secrets.token_hex(4)},
                )
                assert created.status_code == 201, created.text
                operation = created.json()

                banks.append(operation["bank_id"])
            a, b, c = banks
            user_response = await management.post("/users", json={"name": "Tenant application"})
            assert user_response.status_code == 201, user_response.text
            user = user_response.json()
            issued = await management.post(
                f"/users/{user['user_id']}/keys",
                json={
                    "name": "Multi-Bank",
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [
                            {"bank_id": workspace_id, "permission": "read_write"} for workspace_id in [a, b]
                        ],
                    },
                },
            )
            assert issued.status_code == 201, issued.text
            key = issued.json()
            llm.on_step("extract_facts", contains="SchemaSentinel").returns(
                extracted(fact("Alice builds SchemaSentinel", who="Alice", entities=["Alice", "SchemaSentinel"]))
            )
            llm.on_step("extract_facts", contains="OtherSentinel").returns(
                extracted(fact("Bob builds OtherSentinel", who="Bob", entities=["Bob", "OtherSentinel"]))
            )
            llm.on_step("consolidate").returns(consolidation())
            client = Hindsight(base_url=base, api_key=key["secret"])
            administrator = Hindsight(base_url=base, api_key=admin_key)
            try:
                await administrator.aretain(bank_id=b, content="Bob builds OtherSentinel.", retain_async=True)
                await wait_until_settled(administrator, b)
                accepted = await client.aretain(bank_id=a, content="Alice builds SchemaSentinel.", retain_async=True)
                assert accepted.operation_id
                await wait_until_settled(client, a)
                assert (await client.arecall(bank_id=a, query="What does Alice build?")).results
                other_results = (await client.arecall(bank_id=b, query="What does Alice build?")).results
                assert other_results and all("SchemaSentinel" not in item.text for item in other_results)
                accepted_b = await client.aretain(bank_id=b, content="Bob builds OtherSentinel.", retain_async=True)
                assert accepted_b.operation_id
                await wait_until_settled(client, b)
                with pytest.raises(ForbiddenException):
                    await client.arecall(bank_id=c, query="Forbidden")
                page = await administrator.banks.list_banks(limit=100)
                assert set(banks).issubset({bank.bank_id for bank in page.banks})
                async with httpx.AsyncClient(
                    base_url=base, headers={"Authorization": "Bearer " + key["secret"]}
                ) as raw:
                    assert (await raw.get("/ext/contextdb/v1/users")).status_code == 403
                    visible = (await raw.get("/v1/default/banks")).json()
                    assert {bank["bank_id"] for bank in visible["banks"]} == {a, b}
                    assert (
                        await raw.patch(
                            f"/v1/default/banks/{a}/config", json={"updates": {"reflect_mission": "Unauthorized"}}
                        )
                    ).status_code == 403
                    assert (
                        await raw.get(f"/v1/default/files/download/tenants/ctxdb_ws_{c}/banks/{c}/fake.zip")
                    ).status_code == 403
                    # A client-provided schema hint is ignored; the real Bank
                    # path is the only routing target for native REST.
                    response = await raw.post(
                        f"/v1/default/banks/{b}/memories/recall",
                        headers={"X-ContextDB-Schema": "ctxdb_ws_" + a},
                        json={"query": "What does Alice build?"},
                    )
                    assert response.status_code == 200 and response.json()["results"]
                    assert all("SchemaSentinel" not in item["text"] for item in response.json()["results"])
                    assert (await raw.delete(f"/v1/default/banks/{a}/memories")).status_code == 403
                header_transport = StreamableHttpTransport(
                    base + "/mcp/", headers={"Authorization": "Bearer " + key["secret"], "X-Bank-Id": b}
                )
                async with Client(header_transport) as header_mcp:
                    defaulted = await header_mcp.call_tool("recall", {"query": "What does Bob build?"})
                    results = json.loads(defaulted.content[0].text)["results"]
                    assert results and all("SchemaSentinel" not in item["text"] for item in results)
                transport = StreamableHttpTransport(
                    base + "/mcp/", headers={"Authorization": "Bearer " + key["secret"]}
                )
                disabled_proved = False
                try:
                    async with Client(transport) as mcp:
                        session = transport.get_session_id()
                        assert session
                        recalled = await mcp.call_tool("recall", {"bank_id": a, "query": "What does Alice build?"})
                        assert json.loads(recalled.content[0].text)["results"]
                        recalled_b = await mcp.call_tool("recall", {"bank_id": b, "query": "What does Alice build?"})
                        assert json.loads(recalled_b.content[0].text)["results"]
                        assert all(
                            "SchemaSentinel" not in item["text"]
                            for item in json.loads(recalled_b.content[0].text)["results"]
                        )
                        before_a = await administrator.alist_memories(a, limit=1000)
                        before_b = await administrator.alist_memories(b, limit=1000)
                        before_c = await administrator.alist_memories(c, limit=1000)
                        queued_b = (await administrator.operations.list_operations(b)).total
                        queued_c = (await administrator.operations.list_operations(c)).total
                        denied_clear = await mcp.call_tool("clear_memories", {"bank_id": a}, raise_on_error=False)
                        assert denied_clear.is_error
                        denied = await mcp.call_tool(
                            "retain", {"bank_id": c, "content": "Forbidden MCP write"}, raise_on_error=False
                        )
                        assert denied.is_error or json.loads(denied.content[0].text).get("status") == "error"
                        # Denial must leave both memory and the native queue intact,
                        # not merely return an error after accepting a write.
                        assert await administrator.alist_memories(a, limit=1000) == before_a
                        assert await administrator.alist_memories(c, limit=1000) == before_c
                        assert (await administrator.operations.list_operations(c)).total == queued_c
                        listed = await mcp.call_tool("list_banks", {})
                        assert {bank["bank_id"] for bank in json.loads(listed.content[0].text)["banks"]} == {a, b}
                        changed = await management.patch(
                            f"/users/{user['user_id']}/keys/{key['key_id']}",
                            headers={"If-Match": '"1"'},
                            json={
                                "authorization": {
                                    "mode": "selected",
                                    "workspaces": [
                                        {"bank_id": workspace_id, "permission": "read"} for workspace_id in [b]
                                    ],
                                }
                            },
                        )
                        assert changed.status_code == 200, changed.text
                        denied = await mcp.call_tool(
                            "recall", {"bank_id": a, "query": "Forbidden after shrink"}, raise_on_error=False
                        )
                        assert denied.is_error
                        with pytest.raises(ForbiddenException):
                            await client.arecall(bank_id=a, query="Forbidden after shrink")
                        with pytest.raises(ForbiddenException):
                            await client.aretain(bank_id=b, content="Forbidden after read downgrade")
                        denied_write = await mcp.call_tool(
                            "retain", {"bank_id": b, "content": "Forbidden after read downgrade"}, raise_on_error=False
                        )
                        assert denied_write.is_error
                        assert await administrator.alist_memories(b, limit=1000) == before_b
                        assert (await administrator.operations.list_operations(b)).total == queued_b
                        assert "retain" not in {tool.name for tool in await mcp.list_tools()}
                        disabled = await management.patch(
                            f"/users/{user['user_id']}", headers={"If-Match": '"1"'}, json={"status": "disabled"}
                        )
                        assert disabled.status_code == 200, disabled.text
                        with pytest.raises(UnauthorizedException):
                            await client.arecall(bank_id=b, query="Forbidden after disable")
                        with pytest.raises(httpx.HTTPStatusError) as unauthorized:
                            await mcp.call_tool("recall", {"bank_id": b, "query": "Forbidden after disable"})
                        assert unauthorized.value.response.status_code == 401
                        assert transport.get_session_id() == session
                        disabled_proved = True
                        async with httpx.AsyncClient(base_url=base) as unauthenticated:
                            response = await unauthenticated.delete(
                                "/mcp/", headers={"Authorization": "Bearer " + key["secret"], "Mcp-Session-Id": session}
                            )
                            assert response.status_code == 401
                        # FastMCP sends DELETE during __aexit__. Restore the owner
                        # after proving the old session was refused, so client cleanup
                        # can authenticate rather than replace the assertion with a
                        # predictable 401 from the shutdown protocol.
                        restored = await management.patch(
                            f"/users/{user['user_id']}", headers={"If-Match": '"2"'}, json={"status": "active"}
                        )
                        assert restored.status_code == 200, restored.text
                except httpx.HTTPStatusError as error:
                    # A 401 can terminate the client's session runner; FastMCP
                    # then rethrows that same denial at context-manager exit.
                    assert disabled_proved and error.response.status_code == 401
                # Admin all access does not bypass lifecycle ownership.
                async with httpx.AsyncClient(base_url=base, headers={"Authorization": "Bearer " + admin_key}) as raw:
                    assert (await raw.delete(f"/v1/default/banks/{a}")).status_code == 403
                    config = await raw.patch(
                        f"/v1/default/banks/{b}/config",
                        json={"updates": {"reflect_mission": "Authorized administrator mission"}},
                    )
                    assert config.status_code == 200, config.text
                    p1 = (await raw.get("/v1/default/banks", params={"limit": 1, "offset": 0})).json()
                    p2 = (await raw.get("/v1/default/banks", params={"limit": 1, "offset": 1})).json()
                    assert p1["total"] == p2["total"] and p1["total"] >= 3
                    assert p1["banks"][0]["bank_id"] != p2["banks"][0]["bank_id"]
                    assert (await raw.put(f"/v1/default/banks/{a}", json={"name": "Renamed"})).status_code in {403, 405}
                    assert (
                        await raw.post(f"/v1/default/banks/{a}/clone", params={"target_bank_id": secrets.token_hex(16)})
                    ).status_code == 403
                    assert (
                        await raw.post(
                            f"/v1/default/banks/{a}/import", json={"version": "1", "bank": {"name": "Unexpected"}}
                        )
                    ).status_code == 403
                    assert (
                        await raw.post(
                            f"/v1/default/banks/{a}/transfer/import", files={"file": ("fake.zip", b"fake archive")}
                        )
                    ).status_code == 403
                    assert (
                        await raw.post(f"/v1/default/banks/{a}/aliases", json={"alias": "unexpected-alias"})
                    ).status_code == 403
                    assert (await administrator.memory.list_memories(a, limit=100)).total > 0
                    assert (await administrator.memory.list_memories(b, limit=100)).total > 0
                    cleared = await raw.delete(f"/v1/default/banks/{a}/memories")
                    assert cleared.status_code == 200, cleared.text
                    assert (await administrator.memory.list_memories(a, limit=100)).total == 0
                    assert (await raw.get(f"/v1/default/banks/{a}/config")).status_code == 200
                    assert a in {bank["bank_id"] for bank in (await raw.get("/v1/default/banks")).json()["banks"]}
                    assert (await administrator.memory.list_memories(b, limit=100)).total > 0
                    assert (
                        await raw.delete(f"/v1/default/banks/{a}", headers={"X-ContextDB-Content-Clear": "true"})
                    ).status_code == 403
                await administrator.aretain(bank_id=a, content="Alice builds SchemaSentinel.", retain_async=True)
                await wait_until_settled(administrator, a)
                admin_transport = StreamableHttpTransport(
                    base + f"/mcp/{a}/", headers={"Authorization": "Bearer " + admin_key}
                )
                async with Client(admin_transport) as admin_mcp:
                    cleared = await admin_mcp.call_tool("clear_memories", {})
                    assert json.loads(cleared.content[0].text)["status"] == "cleared"
                    refused_delete = await admin_mcp.call_tool("delete_bank", {}, raise_on_error=False)
                    assert refused_delete.is_error
                assert (await administrator.memory.list_memories(a, limit=100)).total == 0
                async with httpx.AsyncClient(base_url=base, headers={"Authorization": "Bearer " + admin_key}) as raw:
                    assert (await raw.get(f"/v1/default/banks/{a}/config")).status_code == 200
                    assert a in {bank["bank_id"] for bank in (await raw.get("/v1/default/banks")).json()["banks"]}
                assert (await administrator.memory.list_memories(b, limit=100)).total > 0
                deleting = await control.delete(
                    "/workspaces/" + a,
                    headers=await workspace_condition_headers(control, "/workspaces/" + a),
                )
                assert deleting.status_code == 204, deleting.text

                with pytest.raises(ForbiddenException):
                    await administrator.arecall(bank_id=a, query="Deleted")
                assert (await administrator.memory.list_memories(b, limit=100)).total > 0
            finally:
                await client.aclose()
                await administrator.aclose()
