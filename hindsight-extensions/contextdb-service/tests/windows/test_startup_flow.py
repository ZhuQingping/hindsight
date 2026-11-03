"""Real API/UI startup, login, management and restart through PowerShell."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Native Windows startup acceptance")
ROOT = Path(__file__).resolve().parents[4]


def free_port() -> int:
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        return reserved.getsockname()[1]


def wait_for(url: str, process: subprocess.Popen[bytes], *, timeout: float = 240) -> httpx.Response:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        assert process.poll() is None, "Local process exited; inspect the captured startup log"
        try:
            response = httpx.get(url, timeout=10)
            if response.status_code == 200:
                return response
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise AssertionError("Local service did not become ready")


@pytest.mark.asyncio
async def test_powershell_start_auth_management_and_restart(tmp_path: Path) -> None:
    from contextbase_client import ContextBase
    from contextbase_client_api.exceptions import UnauthorizedException

    api_port, ui_port = free_port(), free_port()
    while ui_port == api_port:
        ui_port = free_port()
    state = tmp_path / "Windows 本地 state"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("HINDSIGHT_", "CONTEXTBASE_", "CONTEXTDB_"))
    }
    environment.update(
        PYTHON_DOTENV_DISABLED="1",
        CONTEXTDB_DEPLOY_DIR=str(state),
        CONTEXTBASE_API_LLM_PROVIDER="openai",
        CONTEXTBASE_API_LLM_MODEL="native-startup-test",
        CONTEXTBASE_API_LLM_API_KEY="synthetic-test-model-key",
        CONTEXTBASE_API_EMBEDDINGS_PROVIDER="openai",
        CONTEXTBASE_API_EMBEDDINGS_OPENAI_API_KEY="synthetic-test-embedding-key",
        CONTEXTBASE_API_EMBEDDINGS_OPENAI_DIMENSIONS="8",
        CONTEXTBASE_API_RERANKER_PROVIDER="rrf",
        CONTEXTBASE_CP_AUTH_MODE="bootstrap",
        CONTEXTBASE_CP_CONTEXTDB_ENABLED="false",
        NEXT_TELEMETRY_DISABLED="1",
    )
    api = f"http://127.0.0.1:{api_port}"
    ui = f"http://localhost:{ui_port}"
    before: dict[str, bytes] = {}
    for restart in (False, True):
        with (tmp_path / f"windows-{restart}.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(ROOT / "scripts/dev/start.ps1"),
                    "-Port",
                    str(api_port),
                    "-UiPort",
                    str(ui_port),
                ],
                env=environment,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            try:
                wait_for(api + "/health/ready", process)
                saved = json.loads((state / "ui-secrets.json").read_text(encoding="utf-8"))
                admin = json.loads((state / "admin-key.json").read_text(encoding="utf-8"))["secret"]
                # Native Bank calls go through the published SDK; no engine or SQL.
                denied = ContextBase(base_url=api, api_key="invalid")
                try:
                    with pytest.raises(UnauthorizedException):
                        await denied.banks.list_banks()
                finally:
                    await denied.aclose()
                authenticated = ContextBase(base_url=api, api_key=admin)
                try:
                    assert (await authenticated.banks.list_banks()).banks == []
                finally:
                    await authenticated.aclose()
                wait_for(ui + "/api/auth/session", process)
                with httpx.Client(base_url=ui, headers={"Origin": ui}, timeout=120) as browser:
                    assert browser.get("/api/contextdb/users").status_code == 401
                    assert browser.post("/api/auth/login", json={"key": "wrong"}).status_code == 401
                    assert browser.post("/api/auth/login", json={"key": saved["password"]}).status_code == 200
                    assert browser.get("/users").status_code == 200
                    users = browser.get("/api/contextdb/users")
                    assert users.status_code == 200 and users.json()["total"] >= 1
                    if not restart:
                        created = browser.post("/api/contextdb/users", json={"name": "Windows local user"})
                        assert created.status_code in {200, 201}
                    else:
                        assert any(user["name"] == "Windows local user" for user in users.json()["items"])
                    assert browser.post("/api/auth/logout").status_code == 200
                    assert browser.get("/api/contextdb/users").status_code == 401
                names = ("admin-key.json", "api-secrets.json", "ui-secrets.json", "pg-secrets.json")
                current = {name: (state / name).read_bytes() for name in names}
                if restart:
                    assert current == before
                before = current
            finally:
                if process.poll() is None:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    process.wait(timeout=60)
                assert process.poll() is not None
