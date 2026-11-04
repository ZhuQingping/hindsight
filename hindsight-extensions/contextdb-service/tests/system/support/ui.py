"""Own one production Next process against this story's API."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from hindsight_system_tests.server import free_port

from ...paths import ROOT
from .deployment import ContextDBDeployment


@dataclass(frozen=True)
class AdminUI:
    url: str
    password: str = field(repr=False)
    admin_key: str = field(repr=False)


def verify_ui_server(server: Path, source_root: Path) -> None:
    """Verify the selected artifact itself and its match to the API checkout."""
    from hindsight_ext_contextdb.artifacts import source_fingerprint, verify_ui_build

    artifact_root = server.parents[2]
    if server != artifact_root / "contextbase-control-plane/standalone/server.js":
        raise ValueError("UI server must use the checkout's contextbase-control-plane/standalone/server.js layout")
    verify_ui_build(artifact_root)
    # UI acceptance may use an isolated build without touching a running local UI.
    # Its own manifest is necessary but does not prove it matches this API tree.
    if source_fingerprint(artifact_root) != source_fingerprint(source_root):
        raise ValueError("Selected UI artifact does not match the system-test source checkout")


@contextmanager
def ui_owner(
    contextdb_deployment: ContextDBDeployment,
    server: Path,
    node: str,
    root: Path,
    *,
    fixed_origin: bool = True,
    plugin_enabled: bool = True,
    ready_status: int = 200,
    port: int | None = None,
    password: str | None = None,
) -> Iterator[AdminUI]:
    server = server.resolve()
    verify_ui_server(server, ROOT)
    authorization = contextdb_deployment.headers["Authorization"]
    assert authorization.startswith("Bearer ")
    admin_key = authorization.removeprefix("Bearer ")
    password = password or "synthetic-ui-" + secrets.token_urlsafe(24)
    port = port or free_port()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", str(root))}
    env.update(
        {
            "NODE_ENV": "production",
            "HOSTNAME": "127.0.0.1",
            "PORT": str(port),
            "HINDSIGHT_CP_PORT": str(port),
            "HINDSIGHT_CP_HOST": "127.0.0.1",
            "HINDSIGHT_CP_AUTH_MODE": "local",
            "HINDSIGHT_CP_SESSION_DIR": str(root / "sessions"),
            "HINDSIGHT_CP_CONTEXTDB_ENABLED": str(plugin_enabled).lower(),
            "HINDSIGHT_CP_ACCESS_KEY": password,
            "HINDSIGHT_CP_DATAPLANE_API_KEY": admin_key,
            "HINDSIGHT_CP_DATAPLANE_API_URL": contextdb_deployment.server.url,
        }
    )
    if fixed_origin:
        env["HINDSIGHT_CP_PUBLIC_ORIGIN"] = f"http://127.0.0.1:{port}"
    command = [node, str(server)]
    if plugin_enabled and not fixed_origin:
        env["PYTHONPATH"] = str(ROOT / "hindsight-extensions/contextdb-service")
        command = [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; from hindsight_ext_contextdb.ui_gateway import run; run(Path(sys.argv[1]))",
            str(server.parents[2]),
        ]
    url = f"http://127.0.0.1:{port}"
    with (root / "ui.log").open("w") as log:
        process = subprocess.Popen(command, cwd=server.parent, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 60
            last_response = "no HTTP response"
            while time.monotonic() < deadline:
                assert process.poll() is None, f"UI startup failed; log: {root / 'ui.log'}"
                try:
                    response = httpx.get(url + "/login", timeout=1)
                    last_response = f"HTTP {response.status_code}, Location={response.headers.get('location')}"
                    if response.status_code == ready_status:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError(f"UI readiness timed out ({last_response}); log: {root / 'ui.log'}")
            yield AdminUI(url, password, admin_key)
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
