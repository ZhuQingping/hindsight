"""Foreground process launch for the existing node Agent or service supervisor."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from .artifacts import verify_ui_build
from .bootstrap import load_deployment_secrets


def launch(component: Literal["api", "worker", "ui"], directory: Path, source_root: Path) -> None:
    if component == "ui":
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
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in system_keys or key.startswith(("HINDSIGHT_CP_", "NEXT_PUBLIC_"))
        }
        os.environ.clear()
        os.environ.update(environment)
        load_deployment_secrets(directory, "ui")
        server = source_root / "hindsight-control-plane" / "standalone" / "server.js"
        if not server.is_file():
            raise ValueError("Build the matching UI standalone artifact before starting it")
        os.environ["HOSTNAME"] = os.environ.get("HINDSIGHT_CP_HOST", "0.0.0.0")
        os.environ["PORT"] = os.environ.get("HINDSIGHT_CP_PORT", "9999")
        os.execvp("node", ["node", str(server)])
    load_deployment_secrets(directory, "api")
    # API/Worker never need the UI login password or its backend Admin Key.
    for key in (
        "HINDSIGHT_CP_ACCESS_KEY",
        "HINDSIGHT_CP_DATAPLANE_API_KEY",
    ):
        os.environ.pop(key, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    arguments = [sys.executable, "-m", "hindsight_api.worker.main"]
    if component == "api":
        from hindsight_api.config import get_config

        config = get_config()
        arguments = [
            sys.executable,
            "-m",
            "uvicorn",
            "hindsight_ext_contextdb.asgi:create_app",
            "--factory",
            "--host",
            os.environ.get("HINDSIGHT_API_HOST", "0.0.0.0"),
            "--port",
            os.environ.get("HINDSIGHT_API_PORT", "8888"),
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
    os.execv(sys.executable, arguments)
