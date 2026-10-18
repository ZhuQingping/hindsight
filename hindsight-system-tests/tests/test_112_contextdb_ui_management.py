"""A production UI manages workspaces and business keys against the real API.

Optional-extension management is driven through the browser's authenticated UI
proxy. Memory operations use the published SDK. Each Worker mode owns its PG/API
processes, and this story starts and stops only its own UI on a free local port.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from hindsight_client import Hindsight
from hindsight_client_api.exceptions import ForbiddenException, UnauthorizedException

from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact
from hindsight_system_tests.server import free_port

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import ContextDBDeployment

contextdb_deployment = service_story.contextdb_deployment
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AdminUI:
    url: str
    password: str = field(repr=False)
    admin_key: str = field(repr=False)


@pytest.fixture(scope="session")
def contextdb_admin_ui(
    contextdb_deployment: ContextDBDeployment, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AdminUI]:
    server = Path(os.environ.get("CONTEXTDB_UI_SERVER", ROOT / "hindsight-control-plane/standalone/server.js"))
    node = os.environ.get("CONTEXTDB_TEST_NODE_BIN") or shutil.which("node")
    if not server.is_file() or not node:
        pytest.skip("Build the production UI and configure CONTEXTDB_UI_SERVER / CONTEXTDB_TEST_NODE_BIN")
    from hindsight_ext_contextdb.artifacts import verify_ui_build

    verify_ui_build(ROOT)
    authorization = contextdb_deployment.headers["Authorization"]
    assert authorization.startswith("Bearer ")
    admin_key = authorization.removeprefix("Bearer ")
    password = "synthetic-ui-" + secrets.token_urlsafe(24)
    root = tmp_path_factory.mktemp("contextdb-production-ui")
    port = free_port()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", str(root))}
    env.update(
        {
            "NODE_ENV": "production",
            "HOSTNAME": "127.0.0.1",
            "PORT": str(port),
            "HINDSIGHT_CP_CONTEXTDB_ENABLED": "true",
            "HINDSIGHT_CP_ACCESS_KEY": password,
            "HINDSIGHT_CP_DATAPLANE_API_KEY": admin_key,
            "HINDSIGHT_CP_DATAPLANE_API_URL": contextdb_deployment.server.url,
        }
    )
    url = f"http://127.0.0.1:{port}"
    with (root / "ui.log").open("w") as log:
        process = subprocess.Popen([node, str(server)], cwd=server.parent, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                assert process.poll() is None, f"UI startup failed; log: {root / 'ui.log'}"
                try:
                    if httpx.get(url + "/login", timeout=1).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError(f"UI readiness timed out; log: {root / 'ui.log'}")
            yield AdminUI(url, password, admin_key)
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


async def _operation_done(ui: httpx.AsyncClient, operation: dict[str, str]) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        result = await ui.get("/api/contextdb/operations/" + operation["operation_id"])
        assert result.status_code == 200, result.text
        state = result.json()["state"]
        assert state != "failed", result.text
        if state == "succeeded":
            return
        await asyncio.sleep(0.1)
    raise AssertionError("Workspace operation did not complete")


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

        async def workspace(label: str) -> str:
            name = label.lower() + "_" + secrets.token_hex(4)
            request_id = secrets.token_hex(16)
            response = await ui.post(
                "/api/contextdb/workspaces", headers={"Idempotency-Key": request_id}, json={"name": name}
            )
            assert response.status_code == 202, response.text
            operation = response.json()
            await _operation_done(ui, operation)
            replay = await ui.post(
                "/api/contextdb/workspaces", headers={"Idempotency-Key": request_id}, json={"name": name}
            )
            assert replay.status_code == 202
            assert replay.json()["operation_id"] == operation["operation_id"]
            assert ui_settings.admin_key not in response.text
            return await service_story.operation_bank_id(ui, operation["workspace_id"], "/api/contextdb/workspaces")

        a, b, c = await workspace("MySQL"), await workspace("PG"), await workspace("Other")
        spaces = await ui.get("/api/contextdb/workspaces")
        assert spaces.status_code == 200
        assert {a, b, c}.issubset({item["bank_id"] for item in spaces.json()["items"]})
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
        listed = await ui.get(f"/api/contextdb/users/{uid}/keys")
        assert listed.status_code == 200
        assert "secret" not in listed.text
        assert reader_key["secret"] not in listed.text
        assert writer_key["secret"] not in listed.text
        assert ui_settings.admin_key not in listed.text
        base = contextdb_deployment.server.url
        reader = Hindsight(base_url=base, api_key=reader_key["secret"])
        writer = Hindsight(base_url=base, api_key=writer_key["secret"])
        all_spaces = Hindsight(base_url=base, api_key=all_key["secret"])
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
                headers=await service_story.workspace_condition_headers(
                    ui, "/api/contextdb/workspaces/" + b, {"Idempotency-Key": secrets.token_hex(16)}
                ),
            )
            assert deleted.status_code == 202, deleted.text
            await _operation_done(ui, deleted.json())
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
