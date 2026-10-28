"""A production UI manages workspaces and business keys against the real API.

Optional-extension management is driven through the browser's authenticated UI
proxy. Memory operations use the published SDK. Each Worker mode owns its PG/API
processes, and this story starts and stops only its own UI on a free local port.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime

import httpx
import pytest
from contextbase_client import ContextBase
from contextbase_client_api.exceptions import ForbiddenException, UnauthorizedException
from hindsight_system_tests import reflect_loop, wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact
from pydantic import BaseModel

from .support.clients import workspace_condition_headers
from .support.deployment import ContextDBDeployment
from .support.ui import AdminUI


class UiUsageItem(BaseModel):
    object_id: str
    recall_count: int
    last_recalled_at: datetime | None


@pytest.mark.asyncio
async def test_ui_workspace_user_key_and_native_permission_flow(
    contextdb_admin_ui: AdminUI, contextdb_deployment: ContextDBDeployment, llm
) -> None:
    ui_settings = contextdb_admin_ui
    async with httpx.AsyncClient(base_url=ui_settings.url, timeout=100) as anonymous:
        denied = await anonymous.get("/api/contextdb/users")
        assert denied.status_code == 401
        wrong = await anonymous.post(
            "/api/auth/login", headers={"Origin": ui_settings.url}, json={"key": "member-key-is-not-ui-password"}
        )
        assert wrong.status_code == 401
    async with httpx.AsyncClient(base_url=ui_settings.url, headers={"Origin": ui_settings.url}, timeout=100) as ui:
        login = await ui.post("/api/auth/login", json={"key": ui_settings.password})
        assert login.status_code == 200
        assert "HttpOnly" in login.headers["set-cookie"]
        assert ui_settings.admin_key not in login.text
        rejected = await ui.post(
            "/api/contextdb/users", headers={"Origin": "http://other.example"}, json={"name": "Bad"}
        )
        assert rejected.status_code == 403
        page = await ui.get("/users", headers={"Accept-Language": "zh-CN"})
        assert page.status_code == 200
        assert "用户管理" in page.text
        assert ui_settings.admin_key not in page.text

        capability = await ui.get("/api/contextdb/admin/identity")
        assert capability.status_code == 200
        assert capability.json()["capabilities"]["recall_usage"] is True
        assert ui_settings.admin_key not in capability.text

        async def workspace(label: str) -> str:
            name = label.lower() + "_" + secrets.token_hex(4)
            response = await ui.post(
                "/api/contextdb/workspaces", json={"name": name, "description": "Created through authenticated UI"}
            )
            assert response.status_code == 201, response.text
            resource = response.json()
            assert resource["bank_id"] == name and resource["state"] == "active"
            assert resource["description"] == "Created through authenticated UI"
            assert "operation_id" not in resource
            duplicate = await ui.post("/api/contextdb/workspaces", json={"name": name})
            assert duplicate.status_code == 409
            assert ui_settings.admin_key not in response.text
            return resource["bank_id"]

        a, b, c = await workspace("MySQL"), await workspace("PG"), await workspace("Other")
        # A shared deployment may already have more than the default 20 spaces.
        # Force multiple pages even when this story runs alone in the strict CI job.
        observed: set[str] = set()
        offset = 0
        while True:
            spaces = await ui.get("/api/contextdb/workspaces", params={"limit": 2, "offset": offset})
            assert spaces.status_code == 200
            directory = spaces.json()
            assert directory["offset"] == offset
            items = directory["items"]
            observed.update(item["bank_id"] for item in items)
            if offset + len(items) >= directory["total"]:
                break
            assert items, "Workspace pagination must make progress"
            offset += len(items)
        assert {a, b, c}.issubset(observed)
        # Business-field validation belongs to the real backend, while this UI
        # proxy still supplies only its configured administrator credential.
        invalid_member = "Cannot elevate " + secrets.token_hex(4)
        rejected = await ui.post("/api/contextdb/users", json={"name": invalid_member, "role": "admin"})
        assert rejected.status_code == 400
        members = await ui.get("/api/contextdb/users", params={"q": invalid_member})
        assert members.status_code == 200 and members.json()["items"] == []
        rejected = await ui.post(
            "/api/contextdb/workspaces", json={"name": "invalid_" + secrets.token_hex(4), "unsupported": True}
        )
        assert rejected.status_code == 400
        response = await ui.post("/api/contextdb/users", json={"name": "Application owner"})
        assert response.status_code == 201, response.text
        user = response.json()
        assert "workspace_ids" not in user
        assert "role" not in user
        uid = user["user_id"]

        async def key(name: str, permission: str, access_mode: str = "selected") -> dict:
            response = await ui.post(
                f"/api/contextdb/users/{uid}/keys",
                json={
                    "name": name,
                    "authorization": (
                        {
                            "mode": "selected",
                            "workspaces": [
                                {"bank_id": workspace_id, "permission": permission} for workspace_id in [a, b]
                            ],
                        }
                        if access_mode == "selected"
                        else {"mode": "all", "permission": permission}
                    ),
                },
            )
            assert response.status_code == 201, response.text
            assert ui_settings.admin_key not in response.text
            return response.json()

        reader_key = await key("Search application", "read")
        writer_key = await key("Writer", "read_write")
        all_key = await key("All workspaces", "read", "all")
        rejected = await ui.post(
            f"/api/contextdb/users/{uid}/keys",
            json={
                "name": "Cannot elevate",
                "authorization": {"mode": "all", "permission": "admin"},
            },
        )
        assert rejected.status_code == 400
        # UI no longer probes each grant before editing. Even with a current
        # Key version, the backend must reject a replaced workspace's old UUID.
        original_c = (await ui.get(f"/api/contextdb/workspaces/{c}")).json()
        removed = await ui.delete(f"/api/contextdb/workspaces/{c}", headers={"If-Match": original_c["etag"]})
        assert removed.status_code == 204
        recreated = await ui.post("/api/contextdb/workspaces", json={"name": c})
        assert recreated.status_code == 201
        assert recreated.json()["workspace_id"] != original_c["workspace_id"]
        rejected = await ui.patch(
            f"/api/contextdb/users/{uid}/keys/{writer_key['key_id']}",
            headers={"If-Match": f'"{writer_key["version"]}"'},
            json={
                "authorization": {
                    "mode": "selected",
                    "workspaces": [
                        {"bank_id": c, "workspace_id": original_c["workspace_id"], "permission": "read_write"}
                    ],
                }
            },
        )
        assert rejected.status_code == 409
        current_keys = (await ui.get(f"/api/contextdb/users/{uid}/keys")).json()["items"]
        current_writer = next(item for item in current_keys if item["key_id"] == writer_key["key_id"])
        assert {grant["bank_id"] for grant in current_writer["authorization"]["workspaces"]} == {a, b}

        listed = await ui.get(f"/api/contextdb/users/{uid}/keys")
        assert listed.status_code == 200
        assert "secret" not in listed.text
        assert reader_key["secret"] not in listed.text
        assert writer_key["secret"] not in listed.text
        assert ui_settings.admin_key not in listed.text
        base = contextdb_deployment.server.url
        reader = ContextBase(base_url=base, api_key=reader_key["secret"])
        writer = ContextBase(base_url=base, api_key=writer_key["secret"])
        all_spaces = ContextBase(base_url=base, api_key=all_key["secret"])
        try:
            assert (await reader.arecall(bank_id=a, query="Lighthouse")).results == []
            with pytest.raises(ForbiddenException):
                await reader.aretain(bank_id=a, content="This write is forbidden")
            with pytest.raises(ForbiddenException):
                await reader.arecall(bank_id=c, query="Forbidden workspace")
            llm.on_step("extract_facts", contains="Lighthouse").returns(
                extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
            )
            llm.on_step("consolidate").returns(consolidation())
            await writer.aretain(bank_id=a, content="Alice builds Lighthouse.", retain_async=True)
            await wait_until_settled(writer, a)
            assert [
                item.text for item in (await reader.arecall(bank_id=a, query="What does Alice build?")).results
            ] == ["Alice builds Lighthouse | Involving: Alice"]
            # The UI's fixed proxy supplies its server-only administrator Key.
            # Native content reads do not wait for these asynchronous statistics.
            memories = await reader.memory.list_memories(a, limit=10)
            assert memories.items
            memory_id = memories.items[0].id

            async def usage(kind: str, object_id: str) -> UiUsageItem:
                params = [("object_type", kind), ("ids", object_id)]
                for _ in range(100):
                    response = await ui.get(f"/api/contextdb/workspaces/{a}/usage", params=params)
                    assert response.status_code == 200, response.text
                    assert "no-store" in response.headers["cache-control"]
                    assert ui_settings.admin_key not in response.text
                    assert "workspace_id" not in response.json()
                    items = response.json()["items"]
                    if items:
                        item = UiUsageItem.model_validate(items[0])
                        if item.recall_count >= 1:
                            assert item.last_recalled_at is not None and item.last_recalled_at.tzinfo is not None
                            return item
                    await asyncio.sleep(0.1)
                raise AssertionError("UI usage proxy did not expose the recorded hit")

            memory_usage = await usage("memory", memory_id)
            assert memory_usage.recall_count == 1
            reflect_loop(llm, answer="Alice builds Lighthouse.")
            knowledge = await writer.acreate_knowledge_page(
                a, name="Lighthouse team", source_query="What does Alice build?", trigger={"mode": "full"}
            )
            await wait_until_settled(writer, a)
            assert (await writer.asearch_knowledge_base(a, "Lighthouse")).results
            page_usage = await usage("knowledge_page", knowledge.page_id)
            assert page_usage.recall_count == 1
            await writer.aget_knowledge_page(a, knowledge.page_id)
            assert (await usage("knowledge_page", knowledge.page_id)).recall_count == 1
            async with httpx.AsyncClient(base_url=base) as raw:
                path = f"/ext/contextdb/v1/workspaces/{a}/usage"
                params = {"object_type": "memory", "ids": memory_id}
                assert (await raw.get(path, params=params)).status_code == 401
                allowed = await raw.get(
                    path, params=params, headers={"Authorization": "Bearer " + reader_key["secret"]}
                )
                assert allowed.status_code == 200
                assert allowed.json()["items"][0]["recall_count"] == memory_usage.recall_count
            assert (await reader.arecall(bank_id=b, query="Lighthouse")).results == []
            future = await workspace("Future")
            assert (await all_spaces.arecall(bank_id=future, query="Future memory")).results == []
            with pytest.raises(ForbiddenException):
                await reader.arecall(bank_id=future, query="Future memory")
            updated = await ui.patch(
                f"/api/contextdb/users/{uid}/keys/{writer_key['key_id']}",
                headers={"If-Match": f'"{writer_key["version"]}"'},
                json={
                    "authorization": {
                        "mode": "selected",
                        "workspaces": [{"bank_id": workspace_id, "permission": "read"} for workspace_id in [a]],
                    }
                },
            )
            assert updated.status_code == 200, updated.text
            assert "secret" not in updated.text
            with pytest.raises(ForbiddenException):
                await writer.aretain(bank_id=a, content="Write permission was removed")
            revoked = await ui.delete(f"/api/contextdb/users/{uid}/keys/{writer_key['key_id']}")
            assert revoked.status_code == 204
            with pytest.raises(UnauthorizedException):
                await writer.arecall(bank_id=a, query="Lighthouse")
            deleted = await ui.delete(
                "/api/contextdb/workspaces/" + b,
                headers=await workspace_condition_headers(ui, "/api/contextdb/workspaces/" + b),
            )
            assert deleted.status_code == 204, deleted.text
            assert deleted.content == b""
            with pytest.raises(ForbiddenException):
                await reader.arecall(bank_id=b, query="Lighthouse")
            assert (await reader.arecall(bank_id=a, query="Lighthouse")).results
            removed = await ui.delete(f"/api/contextdb/users/{uid}")
            assert removed.status_code == 204
            with pytest.raises(UnauthorizedException):
                await reader.arecall(bank_id=a, query="Lighthouse")
        finally:
            await reader.aclose()
            await writer.aclose()
            await all_spaces.aclose()

        # Logout must revoke the durable session, not only clear this browser's
        # cookie. Replaying its old value must not authorize management again.
        old_cookie = ui.cookies.jar
        replay = "; ".join(f"{cookie.name}={cookie.value}" for cookie in old_cookie)
        assert replay
        assert (await ui.post("/api/auth/logout")).status_code == 200
        denied = await ui.get("/api/contextdb/users", headers={"Cookie": replay})
        assert denied.status_code == 401
