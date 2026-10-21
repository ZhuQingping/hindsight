"""The probe reaches a local UI with its configured public authority."""

import asyncio
import os
import shlex
import sys
from pathlib import Path

import pytest
import yaml
from aiohttp import web

from hindsight_ext_contextdb.ui_probe import healthy

from ..paths import EXTENSION


@pytest.mark.parametrize("status", [200, 302, 421, 503])
@pytest.mark.parametrize(
    ("origin", "host"),
    [
        ("https://ADMIN.example.test:443", "admin.example.test"),
        ("https://admin.example.test:9443", "admin.example.test:9443"),
        ("http://[0:0:0:0:0:0:0:1]:80", "[::1]"),
        ("https://例子.测试:443", "xn--fsqu00a.xn--0zwm56d"),
    ],
)
async def test_probe_uses_local_socket_and_configured_public_host(
    monkeypatch: pytest.MonkeyPatch, status: int, origin: str, host: str
) -> None:
    seen: list[str] = []

    async def health(request: web.Request) -> web.Response:
        seen.append(request.host)
        return web.Response(status=status)

    app = web.Application()
    app.router.add_get("/api/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        monkeypatch.setenv("CONTEXTBASE_CP_PUBLIC_ORIGIN", origin)
        monkeypatch.setenv("CONTEXTBASE_CP_PORT", str(runner.addresses[0][1]))
        monkeypatch.setenv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://wrong.example")
        assert await healthy() is (status == 200)
        assert seen == [host]
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("origin", ["", "file:///tmp/ui", "https://user:secret@example.test", "https://ui.test/path"])
async def test_probe_rejects_invalid_public_origin(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("CONTEXTBASE_CP_PUBLIC_ORIGIN", origin)
    assert await healthy() is False


@pytest.mark.parametrize("prefix", ["HINDSIGHT", "CONTEXTBASE", "both", "public-empty"])
async def test_compose_health_command_exports_ui_authority(tmp_path: Path, prefix: str) -> None:
    """Run the shipped shell chain; sourced shell variables are not exported."""
    seen: list[str] = []

    async def health(request: web.Request) -> web.Response:
        seen.append(request.host)
        if request.path == "/api/health" and request.host != "admin.example.test":
            return web.Response(status=421)
        return web.json_response({"status": "healthy", "database": "connected"})

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
        selected_prefix = "CONTEXTBASE" if prefix in {"both", "public-empty"} else prefix
        legacy_api = "HINDSIGHT_API_PORT=1\n" if prefix == "both" else ""
        legacy_ui = (
            "HINDSIGHT_CP_PUBLIC_ORIGIN=https://wrong.example.test\nHINDSIGHT_CP_PORT=1\n" if prefix == "both" else ""
        )
        if prefix == "public-empty":
            legacy_ui = f"HINDSIGHT_CP_PUBLIC_ORIGIN=https://admin.example.test\nHINDSIGHT_CP_PORT={port}\n"
        origin = "" if prefix == "public-empty" else "https://admin.example.test"
        (tmp_path / "api.env").write_text(legacy_api + f"{selected_prefix}_API_PORT={port}\n")
        (tmp_path / "ui.env").write_text(
            legacy_ui
            + f"{selected_prefix}_CP_PUBLIC_ORIGIN={origin}\n{selected_prefix}_CP_PORT={port}\n"
            + "HINDSIGHT_CP_ACCESS_KEY=synthetic-password\nCONTEXTBASE_CP_ACCESS_KEY=synthetic-public-password\n"
            + "HINDSIGHT_CP_DATAPLANE_API_KEY=synthetic-admin\nCONTEXTBASE_CP_DATAPLANE_API_KEY=synthetic-public-admin\n"
        )
        package = EXTENSION
        compose = yaml.safe_load((package / "deployment/compose.yaml").read_text())
        command = compose["services"]["hindsight"]["healthcheck"]["test"][1]
        # Only substitute container filesystem paths and Compose's dollar escape.
        command = command.replace("/var/lib/contextdb/", shlex.quote(str(tmp_path)) + "/")
        # Exercise the shipped shell chain with the real probes, and verify its
        # child environment rather than only inspecting the YAML text.
        guard = tmp_path / "probe_environment.py"
        guard.write_text(
            "import os, sys\n"
            "private = [p + n for p in ('HINDSIGHT_CP_', 'CONTEXTBASE_CP_') "
            "for n in ('ACCESS_KEY', 'DATAPLANE_API_KEY')]\n"
            "assert not any(name in os.environ for name in private), 'Probe inherited private UI settings'\n"
            "os.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n"
        )
        guarded_python = f"{shlex.quote(sys.executable)} {shlex.quote(str(guard))}"
        command = command.replace("/app/.venv/bin/python", guarded_python).replace("$$", "$")
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("HINDSIGHT_CP_", "CONTEXTBASE_CP_", "HINDSIGHT_API_", "CONTEXTBASE_API_"))
        }
        environment["PYTHONPATH"] = str(package) + os.pathsep + str(package.parents[1] / "hindsight-api-slim")
        process = await asyncio.create_subprocess_exec(
            "sh",
            "-c",
            command,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == (1 if prefix == "public-empty" else 0), (stdout, stderr)
        expected_hosts = [f"127.0.0.1:{port}"]
        if prefix != "public-empty":
            expected_hosts.append("admin.example.test")
        assert seen == expected_hosts
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()
        await runner.cleanup()
