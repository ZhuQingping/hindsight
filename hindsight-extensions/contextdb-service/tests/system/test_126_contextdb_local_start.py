"""The real local launcher preserves authentication and Banks across PG restarts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from contextbase_client import ContextBase
from contextbase_client_api.exceptions import UnauthorizedException
from hindsight_system_tests.server import StubServer, free_port, stub_environment

from ..lifecycle_http import create_workspace
from ..paths import ROOT


@pytest.mark.asyncio
async def test_local_launcher_auth_and_persistence(stub_server: StubServer, tmp_path: Path) -> None:
    directory = tmp_path / "local-state"
    port = free_port()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CONTEXTDB_", "CONTEXTBASE_", "HINDSIGHT_"))
    }
    environment.update(stub_environment(stub_server.url))
    environment.update(
        CONTEXTDB_DEPLOY_DIR=str(directory),
        PYTHON_DOTENV_DISABLED="1",
        PYTHONPATH=os.pathsep.join(
            [str(ROOT / "hindsight-api-slim"), str(ROOT / "hindsight-extensions/contextdb-service")]
        ),
    )
    before: dict[str, bytes] = {}
    bank_id = "local_persistence"
    for restart in (False, True):
        with (tmp_path / f"local-{restart}.log").open("w") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "hindsight_ext_contextdb.local", "--component", "api", "--port", str(port)],
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 100
                while True:
                    assert process.poll() is None, f"Local startup failed: {log.name}"
                    assert time.monotonic() < deadline
                    try:
                        if httpx.get(f"http://127.0.0.1:{port}/health/ready", timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                credential = json.loads((directory / "admin-key.json").read_text())["secret"]
                for token in ("", "ctx_live_invalid"):
                    rejected = ContextBase(base_url=f"http://127.0.0.1:{port}", api_key=token)
                    try:
                        with pytest.raises(UnauthorizedException):
                            await rejected.banks.list_banks()
                    finally:
                        await rejected.aclose()
                client = ContextBase(base_url=f"http://127.0.0.1:{port}", api_key=credential)
                try:
                    if not restart:
                        async with httpx.AsyncClient(
                            base_url=f"http://127.0.0.1:{port}/ext/contextdb/v1",
                            headers={"Authorization": "Bearer " + credential},
                            timeout=60,
                        ) as management:
                            response = await create_workspace(management, json={"name": bank_id})
                            assert response.status_code == 200, response.text
                        before = {
                            name: (directory / name).read_bytes()
                            for name in ("admin-key.json", "api-secrets.json", "ui-secrets.json", "pg-secrets.json")
                        }
                    banks = await client.banks.list_banks()
                    assert bank_id in {bank.bank_id for bank in banks.banks}
                    assert all((directory / name).read_bytes() == content for name, content in before.items())
                finally:
                    await client.aclose()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
