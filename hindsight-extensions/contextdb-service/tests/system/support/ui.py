"""Own one production Next process against this story's API."""

from __future__ import annotations

import os
import secrets
import subprocess
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
    if server != artifact_root / "hindsight-control-plane/standalone/server.js":
        raise ValueError("UI server must use the checkout's hindsight-control-plane/standalone/server.js layout")
    verify_ui_build(artifact_root)
    # UI acceptance may use an isolated build without touching a running local UI.
    # Its own manifest is necessary but does not prove it matches this API tree.
    if source_fingerprint(artifact_root) != source_fingerprint(source_root):
        raise ValueError("Selected UI artifact does not match the system-test source checkout")


@contextmanager
def ui_owner(contextdb_deployment: ContextDBDeployment, server: Path, node: str, root: Path) -> Iterator[AdminUI]:
    server = server.resolve()
    verify_ui_server(server, ROOT)
    authorization = contextdb_deployment.headers["Authorization"]
    assert authorization.startswith("Bearer ")
    admin_key = authorization.removeprefix("Bearer ")
    password = "synthetic-ui-" + secrets.token_urlsafe(24)
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
