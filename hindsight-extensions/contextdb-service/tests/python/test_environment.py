"""Public configuration works before native entrypoint alias normalization."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from hindsight_ext_contextdb.environment import service_env

from ..paths import EXTENSION


@pytest.fixture(autouse=True)
def clean_service_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in list(os.environ):
        if name.startswith(("CONTEXTBASE_API_", "HINDSIGHT_API_", "CONTEXTBASE_CP_", "HINDSIGHT_CP_")):
            monkeypatch.delenv(name)


@pytest.mark.parametrize("prefix", ["HINDSIGHT", "CONTEXTBASE", "both"])
def test_prepare_uses_effective_database_and_ui_password(
    prefix: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hindsight_ext_contextdb import __main__ as cli

    if prefix == "both":
        monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", "postgresql://wrong.invalid/ignored")
        monkeypatch.setenv("HINDSIGHT_CP_ACCESS_KEY", "ignored-password")
    selected = "CONTEXTBASE" if prefix == "both" else prefix
    monkeypatch.setenv(f"{selected}_API_DATABASE_URL", "postgresql://selected.invalid/database")
    monkeypatch.setenv(f"{selected}_CP_ACCESS_KEY", "selected-password")
    prepare = AsyncMock()
    monkeypatch.setattr(cli, "prepare_deployment", prepare)
    monkeypatch.setattr(sys, "argv", ["contextdb", "prepare", "--directory", str(tmp_path)])
    cli.main()
    prepare.assert_awaited_once_with(tmp_path, "postgresql://selected.invalid/database", "selected-password")


@pytest.mark.parametrize("prefix", ["HINDSIGHT", "CONTEXTBASE", "both"])
def test_settings_checks_effective_public_policy(prefix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from hindsight_ext_contextdb.config import Settings

    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", "instance")
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", "tenant")
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", "synthetic-pepper-32-characters-long")
    if prefix == "both":
        monkeypatch.setenv("HINDSIGHT_API_LLM_TRACE_ENABLED", "true")
        monkeypatch.setenv("HINDSIGHT_API_MCP_AUTH_TOKEN", "ignored-token")
    selected = "CONTEXTBASE" if prefix == "both" else prefix
    monkeypatch.setenv(f"{selected}_API_LLM_TRACE_ENABLED", "false")
    monkeypatch.setenv(f"{selected}_API_MCP_AUTH_TOKEN", "")
    monkeypatch.setenv(f"{selected}_API_MCP_ENABLED", "true")
    monkeypatch.setenv(f"{selected}_API_MCP_EXTENSION", "hindsight_ext_contextdb.mcp:ContextDBMCPExtension")
    assert Settings.from_environment().instance_id == "instance"
    monkeypatch.setenv("CONTEXTBASE_API_AUDIT_LOG_ENABLED", "true")
    with pytest.raises(ValueError, match="AUDIT_LOG_ENABLED"):
        Settings.from_environment()


def test_reading_aliases_never_loads_dotenv_or_mutates_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("CONTEXTBASE_API_PORT=9999\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HINDSIGHT_API_PORT", "8888")
    before = dict(os.environ)
    assert service_env("API_PORT") == "8888"
    assert dict(os.environ) == before
    monkeypatch.setenv("CONTEXTBASE_API_PORT", "")
    assert service_env("API_PORT", "7777") == ""
    monkeypatch.delenv("CONTEXTBASE_API_PORT")
    monkeypatch.delenv("HINDSIGHT_API_PORT")
    assert service_env("API_PORT", "7777") == "7777"


@pytest.mark.parametrize("command", ["migrate", "rotate"])
async def test_offline_database_commands_prefer_public_url(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from hindsight_ext_contextdb import __main__ as cli
    from hindsight_ext_contextdb.bootstrap import AdministratorCredential
    from hindsight_ext_contextdb.config import Settings

    monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", "postgresql://wrong.invalid/ignored")
    monkeypatch.setenv("CONTEXTBASE_API_DATABASE_URL", "postgresql://selected.invalid/database")
    settings = Settings(instance_id="instance", cloud_tenant_id="tenant", pepper="synthetic-pepper-32-characters-long")
    monkeypatch.setattr(cli.Settings, "from_environment", lambda: settings)
    monkeypatch.setattr(
        cli, "read_credential", lambda _: AdministratorCredential(key_id="a" * 32, secret="synthetic-credential")
    )
    connection = AsyncMock()
    connection.transaction = MagicMock(return_value=AsyncMock())
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(cli.asyncpg, "connect", connect)
    for name in ["verify_format", "verify_binding", "rotate_administrator", "migrate_connection"]:
        monkeypatch.setattr(cli, name, AsyncMock())
    await getattr(cli, command)(tmp_path / "admin.json")
    assert connect.await_args.args == ("postgresql://selected.invalid/database",)
    connection.close.assert_awaited_once()


def test_ui_shell_readiness_uses_public_url(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir(mode=0o700)
    config = deploy / "ui.env"
    config.write_text(
        "HINDSIGHT_CP_DATAPLANE_API_URL=http://wrong.invalid\n"
        "CONTEXTBASE_CP_DATAPLANE_API_URL=http://selected.invalid:9123\n"
    )
    config.chmod(0o600)
    capture = tmp_path / "arguments"
    interpreter = tmp_path / "python"
    interpreter.write_text(
        '#!/bin/bash\nif [ "$1" = - ]; then exec "$REAL_PYTHON" "$@"; fi\nprintf "%s\\n" "$@" >> "$CAPTURE_ARGUMENTS"\n'
    )
    interpreter.chmod(0o700)
    result = subprocess.run(
        ["bash", str(EXTENSION / "scripts/service.sh"), "ui"],
        env={
            **os.environ,
            "CONTEXTDB_DEPLOY_DIR": str(deploy),
            "CONTEXTDB_PYTHON": str(interpreter),
            "REAL_PYTHON": sys.executable,
            "CAPTURE_ARGUMENTS": str(capture),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    arguments = capture.read_text()
    assert "http://selected.invalid:9123/health/ready" in arguments
    assert "wrong.invalid" not in arguments


@pytest.mark.parametrize("prefix", ["HINDSIGHT", "CONTEXTBASE", "both"])
async def test_preflight_probes_the_effective_database(prefix: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncpg

    from hindsight_ext_contextdb.preflight import preflight

    if prefix == "both":
        monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", "postgresql://wrong.invalid/ignored")
        monkeypatch.setenv("HINDSIGHT_API_LLM_TRACE_ENABLED", "true")
    selected = "CONTEXTBASE" if prefix == "both" else prefix
    monkeypatch.setenv(f"{selected}_API_DATABASE_URL", "postgresql://selected.invalid/database")
    monkeypatch.setenv(f"{selected}_API_LLM_TRACE_ENABLED", "false")
    # Stop at the network boundary: the property is which database the command
    # probes, not availability of a live service or its PostgreSQL extensions.
    connect = AsyncMock(side_effect=OSError("synthetic connection failure"))
    monkeypatch.setattr(asyncpg, "connect", connect)
    report = await preflight()
    connect.assert_awaited_once_with("postgresql://selected.invalid/database", timeout=10)
    assert not any(item.name in {"database", "HINDSIGHT_API_LLM_TRACE_ENABLED"} for item in report.checks)


@pytest.mark.parametrize("command", ["init", "api"])
def test_shell_initialization_and_worker_checks_use_public_settings(tmp_path: Path, command: str) -> None:
    deploy = tmp_path / "deploy"
    deploy.mkdir(mode=0o700)
    config = deploy / "api.env"
    config.write_text(
        "HINDSIGHT_API_WORKER_ENABLED=false\nCONTEXTBASE_API_WORKER_ENABLED=true\n"
        "HINDSIGHT_API_TENANT_EXTENSION=internal-tenant\nCONTEXTBASE_API_TENANT_EXTENSION=public-tenant\n"
    )
    config.chmod(0o600)
    capture = tmp_path / "migration-tenant"
    interpreter = tmp_path / "python"
    interpreter.write_text(
        '#!/bin/bash\nif [ "$1" = - ]; then exec "$REAL_PYTHON" "$@"; fi\n'
        'if [ "$2" = hindsight_api.admin.cli ]; then\n'
        '  printf "%s|%s" "$CONTEXTBASE_API_TENANT_EXTENSION" "$HINDSIGHT_API_TENANT_EXTENSION" > "$CAPTURE_ARGUMENTS"\n'
        "fi\n"
    )
    interpreter.chmod(0o700)
    result = subprocess.run(
        ["bash", str(EXTENSION / "scripts/service.sh"), command],
        env={
            **os.environ,
            "CONTEXTDB_DEPLOY_DIR": str(deploy),
            "CONTEXTDB_PYTHON": str(interpreter),
            "CONTEXTDB_COMBINED": "1",
            "REAL_PYTHON": sys.executable,
            "CAPTURE_ARGUMENTS": str(capture),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    if command == "init":
        assert capture.read_text() == "|"
