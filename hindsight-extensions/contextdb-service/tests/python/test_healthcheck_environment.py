"""Exercise the shipped health chain without exporting deployment secrets."""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web

from ..paths import EXTENSION, ROOT


async def test_healthcheck_keeps_private_settings_out_of_probe_environment(tmp_path: Path) -> None:
    paths: list[str] = []

    async def health(request: web.Request) -> web.Response:
        paths.append(request.path)
        return web.json_response({"status": "healthy"})

    app = web.Application()
    app.router.add_get("/health/ready", health)
    app.router.add_get("/api/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    process: asyncio.subprocess.Process | None = None
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        (tmp_path / "api.env").write_text(
            f"HINDSIGHT_API_PORT={port}\nHINDSIGHT_API_DATABASE_URL=synthetic-private-database\n"
        )
        (tmp_path / "ui.env").write_text(
            f"HINDSIGHT_CP_PORT={port}\nHINDSIGHT_CP_ACCESS_KEY=synthetic-ui-password\n"
            "HINDSIGHT_CP_DATAPLANE_API_KEY=synthetic-admin-key\n"
        )
        guard = tmp_path / "guard.py"
        guard.write_text(
            "import os, sys\n"
            "private = ('HINDSIGHT_API_DATABASE_URL', 'HINDSIGHT_CP_ACCESS_KEY', "
            "'HINDSIGHT_CP_DATAPLANE_API_KEY')\n"
            "assert not any(key in os.environ for key in private), 'Private setting exported'\n"
            "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n"
        )
        compose = yaml.safe_load((EXTENSION / "deployment/compose.yaml").read_text())
        command = compose["services"]["hindsight"]["healthcheck"]["test"][1]
        command = command.replace("/var/lib/contextdb/", shlex.quote(str(tmp_path)) + "/")
        command = command.replace(
            "/app/.venv/bin/python", f"{shlex.quote(sys.executable)} {shlex.quote(str(guard))}"
        ).replace("$$", "$")
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith(("HINDSIGHT_API_", "HINDSIGHT_CP_"))
        }
        environment["PYTHONPATH"] = str(EXTENSION) + os.pathsep + str(ROOT / "hindsight-api-slim")
        process = await asyncio.create_subprocess_exec(
            "sh", "-c", command, env=environment, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == 0, (stdout, stderr)
        assert paths == ["/health/ready", "/api/health"]
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
