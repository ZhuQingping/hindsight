"""Foreground process launch for the existing node Agent or service supervisor."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import Literal

from .artifacts import verify_ui_build
from .bootstrap import load_deployment_secrets
from .environment import service_env


def launch(component: Literal["api", "worker", "ui"], directory: Path, source_root: Path) -> None:
    if component == "ui":
        development = os.environ.get("CONTEXTDB_UI_DEV") == "1"
        local_port = os.environ.get("CONTEXTDB_LOCAL_UI_PORT") if development else None
        if not development:
            verify_ui_build(source_root)
        # Build/server processes receive UI-only configuration, never PG/model
        # credentials or the HMAC pepper from a shared operator shell.
        system_keys = {
            "PATH",
            "HOME",
            "TMPDIR",
            "TMP",
            "TEMP",
            "LANG",
            "LC_ALL",
            "TZ",
            "NODE_ENV",
            "NODE_OPTIONS",
            "NODE_EXTRA_CA_CERTS",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "contextdb_name",
            "product_display_name",
            "SystemRoot",
            "SYSTEMROOT",
            "COMSPEC",
            "PATHEXT",
            "USERPROFILE",
            "LOCALAPPDATA",
            "APPDATA",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in system_keys or key.startswith(("CONTEXTBASE_CP_", "HINDSIGHT_CP_", "NEXT_PUBLIC_"))
        }
        os.environ.clear()
        os.environ.update(environment)
        load_deployment_secrets(directory, "ui")
        if development:
            if local_port is not None:
                if not local_port.isdecimal() or not 1024 <= int(local_port) <= 65535:
                    raise ValueError("UI port must be within 1024..65535")
                previous_port = service_env("CP_PORT", "9999")
                origin = service_env("CP_PUBLIC_ORIGIN")
                # Adjust auto-generated loopback origins; an operator's external
                # proxy origin stays authoritative even if the dev port changes.
                for host in ("localhost", "127.0.0.1"):
                    if origin == f"http://{host}:{previous_port}":
                        for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
                            os.environ[prefix + "PUBLIC_ORIGIN"] = f"http://{host}:{local_port}"
                for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
                    os.environ[prefix + "PORT"] = local_port
            os.chdir(source_root)
            os.environ["HOSTNAME"] = service_env("CP_HOST", "127.0.0.1")
            os.environ["PORT"] = service_env("CP_PORT", "9999")
            if sys.platform == "win32":
                npm = shutil.which("npm.cmd")
                if npm is None:
                    raise ValueError("Install Node.js 24 and npm before starting the UI")
                subprocess.run([npm, "run", "build", "-w", "contextbase-client"], check=True)
                # Avoid npm's POSIX-only ${PORT:-9999} script on Windows.
                next_cli = source_root / "node_modules/next/dist/bin/next"
                _run_windows(
                    [
                        "node",
                        str(next_cli),
                        "dev",
                        str(source_root / "contextbase-control-plane"),
                        "--hostname",
                        os.environ["HOSTNAME"],
                        "--port",
                        os.environ["PORT"],
                    ]
                )
            subprocess.run(["npm", "run", "build", "-w", "contextbase-client"], check=True)
            os.execvp(
                "npm",
                [
                    "npm",
                    "run",
                    "dev",
                    "-w",
                    "@vectorize-io/hindsight-control-plane",
                    "--",
                    "--hostname",
                    os.environ["HOSTNAME"],
                ],
            )
        server = source_root / "contextbase-control-plane" / "standalone" / "server.js"
        if not server.is_file():
            raise ValueError("Build the matching UI standalone artifact before starting it")
        os.environ["HOSTNAME"] = service_env("CP_HOST", "0.0.0.0")
        os.environ["PORT"] = service_env("CP_PORT", "9999")
        if sys.platform == "win32":
            _run_windows(["node", str(server)])
        os.execvp("node", ["node", str(server)])
    load_deployment_secrets(directory, "api")
    # API/Worker never need the UI login password or its backend Admin Key.
    for key in (
        "CONTEXTBASE_CP_ACCESS_KEY",
        "CONTEXTBASE_CP_DATAPLANE_API_KEY",
        "HINDSIGHT_CP_ACCESS_KEY",
        "HINDSIGHT_CP_DATAPLANE_API_KEY",
    ):
        os.environ.pop(key, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    arguments = [sys.executable, "-m", "hindsight_api.worker.main"]
    if component == "api":
        from hindsight_api.config import get_config, load_dotenv_for_entrypoint

        load_dotenv_for_entrypoint()

        config = get_config()
        arguments = [
            sys.executable,
            "-m",
            "uvicorn",
            "hindsight_ext_contextdb.asgi:create_app",
            "--factory",
            "--host",
            config.host or "0.0.0.0",
            "--port",
            str(config.port),
            "--log-level",
            config.log_level,
            "--access-log" if config.access_log else "--no-access-log",
            "--workers",
            str(config.workers),
            # Match the native CLI: forwarded identity is opt-in, not trusted
            # implicitly because uvicorn's CLI enables proxy headers by default.
            "--no-proxy-headers",
            "--ws",
            "wsproto",
            "--timeout-keep-alive",
            "30",
            "--timeout-graceful-shutdown",
            "5",
        ]
    if sys.platform == "win32":
        _run_windows(arguments)
    os.execv(sys.executable, arguments)


def _run_windows(arguments: list[str]) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Windows launch requires Windows")
    # The supervisor broadcasts CTRL_BREAK to the group. Keep this wrapper alive
    # while uvicorn/Node shuts down; its Job Object owns all remaining children.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGBREAK, signal.SIG_IGN)
    raise SystemExit(subprocess.run(arguments, check=False).returncode)
