"""One credential has different per-workspace permissions across REST and MCP.

Optional management APIs provision resources; native memory and operation reads
go through the published SDK. Each Worker mode uses its own temporary database.
"""

from __future__ import annotations

import json
import secrets

import httpx
import pytest
from fastmcp import Client
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException

from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import ContextDBDeployment
from .test_110_contextdb_tenant_admin import operation_done

contextdb_deployment = service_story.contextdb_deployment
pytestmark = pytest.mark.asyncio


async def test_mixed_workspace_authorization_editing_and_native_clients(
    contextdb_deployment: ContextDBDeployment, llm
) -> None:
    base = contextdb_deployment.server.url
    async with httpx.AsyncClient(
        base_url=base + "/ext/contextdb/v1", headers=contextdb_deployment.headers, timeout=100
    ) as management:

        async def workspace(label: str) -> str:
            name = label + secrets.token_hex(5)
            response = await management.post(
                "/workspaces",
                json={"name": name},
                headers={"Idempotency-Key": secrets.token_hex(16)},
            )
            assert response.status_code == 202, response.text
            operation = response.json()
            assert response.headers["location"].endswith("/operations/" + operation["operation_id"])
            await operation_done(management, operation)
            detail = await management.get("/workspaces/" + name)
            assert detail.json()["latest_operation_id"] == operation["operation_id"]
            return await service_story.operation_bank_id(management, operation["workspace_id"])

        a, b = await workspace("read_space_"), await workspace("write_space_")
        response = await management.post("/users", json={"name": "Mixed-permission application"})
        assert response.status_code == 201, response.text
        user = response.json()
        assert "instance_id" not in user
        uid = user["user_id"]
        response = await management.post(
            f"/users/{uid}/keys",
            json={
                "name": "Mixed key",
                "authorization": {
                    "mode": "selected",
                    "workspaces": [
                        {"bank_id": a, "permission": "read"},
                        {"bank_id": b},
                    ],
                },
            },
        )
        assert response.status_code == 201, response.text
        key = response.json()
        expected = {
            "mode": "selected",
            "workspaces": [
                {"bank_id": a, "permission": "read"},
                {"bank_id": b, "permission": "read_write"},
            ],
        }
        assert key["authorization"]["mode"] == "selected"
        assert {item["bank_id"]: item["permission"] for item in key["authorization"]["workspaces"]} == {
            a: "read",
            b: "read_write",
        }
        expected = key["authorization"]
        assert key["display_key"] == "ctx_live_***" + key["secret"][-6:]
        assert {"access_mode", "workspace_ids", "permission", "revoked_at", "status"}.isdisjoint(key)
        llm.on_step("extract_facts", contains="MixedSentinel").returns(
            extracted(fact("Alice builds MixedSentinel", who="Alice", entities=["Alice", "MixedSentinel"]))
        )
        llm.on_step("consolidate").returns(consolidation())
        client = Hindsight(base_url=base, api_key=key["secret"])
        try:
            assert (await client.arecall(bank_id=a, query="Empty read space")).results == []
            with pytest.raises(ForbiddenException):
                await client.aretain(bank_id=a, content="Must not write to the read space")
            accepted = await client.aretain(bank_id=b, content="Alice builds MixedSentinel.", retain_async=True)
            assert accepted.operation_id
            await wait_until_settled(client, b)
            assert [
                item.text for item in (await client.arecall(bank_id=b, query="What does Alice build?")).results
            ] == ["Alice builds MixedSentinel | Involving: Alice"]
            with pytest.raises(ForbiddenException):
                await client.operations.get_operation_status(b, accepted.operation_id, include_payload=True)
            assert (await client.operations.get_operation_status(b, accepted.operation_id)).status == "completed"
            async with Client(base + "/mcp/", auth=key["secret"]) as mcp:
                assert "retain" in {tool.name for tool in await mcp.list_tools()}
                denied = await mcp.call_tool(
                    "retain", {"bank_id": a, "content": "A write remains forbidden"}, raise_on_error=False
                )
                assert denied.is_error
                recalled = await mcp.call_tool("recall", {"bank_id": b, "query": "What does Alice build?"})
                assert not recalled.is_error
                assert [item["text"] for item in json.loads(recalled.content[0].text)["results"]] == [
                    "Alice builds MixedSentinel | Involving: Alice"
                ]
            async with Client(base + f"/mcp/{a}/", auth=key["secret"]) as single:
                assert "retain" not in {tool.name for tool in await single.list_tools()}

            path = f"/users/{uid}/keys/{key['key_id']}"
            renamed = await management.patch(path, headers={"If-Match": '"1"'}, json={"name": "Renamed key"})
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["authorization"] == expected
            assert "secret" not in renamed.json()
            version = renamed.json()["version"]
            incomplete = await management.patch(
                path,
                headers={"If-Match": f'"{version}"'},
                json={"authorization": {"mode": "selected", "workspaces": [{"bank_id": b}]}},
            )
            assert incomplete.status_code == 400

            # Deletion removes old grants and invalidates a stale editor. A fresh
            # name-only edit keeps the surviving grant and cannot resurrect it.
            deletion = await management.delete(
                "/workspaces/" + a,
                headers=await service_story.workspace_condition_headers(
                    management, "/workspaces/" + a, {"Idempotency-Key": secrets.token_hex(16)}
                ),
            )
            assert deletion.status_code == 202, deletion.text
            await operation_done(management, deletion.json())
            renamed = await management.patch(
                path, headers={"If-Match": f'"{version}"'}, json={"name": "Name after space deletion"}
            )
            assert renamed.status_code == 412, renamed.text
            current = (await management.get(f"/users/{uid}/keys")).json()["items"][0]
            assert [grant["bank_id"] for grant in current["authorization"]["workspaces"]] == [b]
            renamed = await management.patch(
                path, headers={"If-Match": f'"{current["version"]}"'}, json={"name": "Fresh name"}
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["authorization"] == current["authorization"]
            assert (await client.arecall(bank_id=b, query="What does Alice build?")).results
            with pytest.raises(ForbiddenException):
                await client.arecall(bank_id=a, query="Deleted space")
            assert (await management.delete(path)).status_code == 204
            listed = await management.get(f"/users/{uid}/keys")
            assert listed.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
        finally:
            await client.aclose()
