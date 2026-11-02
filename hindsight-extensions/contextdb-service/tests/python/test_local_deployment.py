"""Local entrypoints must initialize authentication before exposing any service."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from dotenv import dotenv_values
from hindsight_ext_contextdb import embedded, local
from hindsight_ext_contextdb.bootstrap import load_deployment_secrets
from hindsight_ext_contextdb.embedded import DatabaseConnection, private_directory


@pytest.fixture
def local_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for key in list(os.environ):
        if key.startswith(("HINDSIGHT_", "CONTEXTBASE_", "CONTEXTDB_")):
            monkeypatch.delenv(key)
    directory = tmp_path / "runtime"
    private_directory(directory)
    monkeypatch.setenv("CONTEXTDB_DEPLOY_DIR", str(directory))
    monkeypatch.setattr(local, "load_dotenv", Mock())
    monkeypatch.setattr(sys, "argv", ["local", "--component", "api"])
    previous = signal.getsignal(signal.SIGTERM)
    yield directory
    signal.signal(signal.SIGTERM, previous)


def test_local_config_overrides_auth_bypass_aliases(local_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBASE_API_TENANT_EXTENSION", "")
    monkeypatch.setenv("CONTEXTBASE_CP_AUTH_MODE", "none")
    monkeypatch.setenv("CONTEXTBASE_API_LLM_API_KEY", "synthetic-provider-key")
    local.configure(local_environment, "postgresql://synthetic", 8888, 9999)
    api = dotenv_values(local_environment / "api.env")
    ui = dotenv_values(local_environment / "ui.env")
    for prefix in ("HINDSIGHT_API_", "CONTEXTBASE_API_"):
        assert api[prefix + "TENANT_EXTENSION"] == "hindsight_ext_contextdb.tenant:ContextDBTenantExtension"
        assert api[prefix + "RUN_MIGRATIONS_ON_STARTUP"] == "false"
    assert api["CONTEXTBASE_API_LLM_API_KEY"] == "synthetic-provider-key"
    for prefix in ("HINDSIGHT_CP_", "CONTEXTBASE_CP_"):
        assert ui[prefix + "AUTH_MODE"] == "local"
        assert ui[prefix + "CONTEXTDB_ENABLED"] == "true"
        assert ui[prefix + "SESSION_DIR"] == str(local_environment / "ui-sessions")
    for filename in ("api.env", "ui.env"):
        assert (local_environment / filename).stat().st_mode & 0o777 == 0o600
    assert "synthetic-provider-key" not in (local_environment / "ui.env").read_text()


@pytest.mark.parametrize("failure", ["extensions", "credentials", "migration", None])
def test_local_start_initializes_before_serving_and_stops_pg(
    local_environment: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    events: list[str] = []

    def control(command: str, directory: Path, data_dir: Path) -> DatabaseConnection | None:
        assert directory == local_environment
        assert data_dir == directory / "pgdata"
        events.append(command)
        return DatabaseConnection(uri="postgresql://synthetic") if command == "start" else None

    async def extensions(url: str) -> None:
        events.append("extensions")
        if failure == "extensions":
            raise ValueError("synthetic secret must not escape")

    async def credentials(*args: object) -> None:
        events.append("credentials")
        if failure == "credentials":
            raise ValueError("synthetic secret must not escape")

    def migrate(*args: object, **kwargs: object) -> None:
        events.append("migration")
        if failure == "migration":
            raise subprocess.CalledProcessError(2, "init")

    def serve(*args: object) -> int:
        events.append("serve")
        return 0

    monkeypatch.setattr(local, "pg_control", control)
    monkeypatch.setattr(local, "enable_extensions", extensions)
    monkeypatch.setattr(local, "prepare_deployment", credentials)
    monkeypatch.setattr(local.subprocess, "run", migrate)
    monkeypatch.setattr(local, "serve", serve)
    with pytest.raises(SystemExit) as result:
        local.main()
    assert result.value.code == (2 if failure else 0)
    expected = ["start", "extensions", "credentials", "migration", "serve"]
    if failure:
        expected = expected[
            : expected.index(
                {"extensions": "extensions", "credentials": "credentials", "migration": "migration"}[failure]
            )
            + 1
        ]
    assert events == expected + ["stop"]


def test_external_database_never_starts_or_stops_pg(local_environment: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBASE_API_DATABASE_URL", "postgresql://external")
    control = Mock(side_effect=AssertionError("External database must not be managed"))
    monkeypatch.setattr(local, "pg_control", control)
    monkeypatch.setattr(local, "prepare_deployment", AsyncMock())
    monkeypatch.setattr(local.subprocess, "run", Mock())
    monkeypatch.setattr(local, "serve", Mock(return_value=0))
    with pytest.raises(SystemExit) as result:
        local.main()
    assert result.value.code == 0
    control.assert_not_called()


def test_pg_registry_is_private_and_connection_never_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = tmp_path / "runtime"
    private_directory(directory)
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{"uri":"postgresql://synthetic"}', ""))
    monkeypatch.setattr(local.subprocess, "run", run)
    assert local.pg_control("start", directory, directory / "pgdata").uri == "postgresql://synthetic"
    assert run.call_args.kwargs["env"]["HOME"] == str(directory / "pg0-home")
    assert run.call_args.kwargs["capture_output"] is True
    assert (directory / "pg0-home").stat().st_mode & 0o777 == 0o700


def test_pg_secret_is_preserved_and_missing_existing_secret_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "runtime"
    data_dir = directory / "pgdata"
    private_directory(directory)
    private_directory(data_dir)
    fake = Mock()
    fake.info.return_value = SimpleNamespace(running=False)
    fake.start.return_value = SimpleNamespace(uri="postgresql://synthetic", data_dir=str(data_dir))
    constructor = Mock(return_value=fake)
    monkeypatch.setitem(sys.modules, "pg0", SimpleNamespace(Pg0=constructor))
    embedded.control("start", directory, data_dir)
    before = (directory / "pg-secrets.json").read_bytes()
    embedded.control("start", directory, data_dir)
    assert (directory / "pg-secrets.json").read_bytes() == before
    assert constructor.call_args.kwargs["data_dir"] == str(data_dir)
    (directory / "pg-secrets.json").unlink()
    (data_dir / "PG_VERSION").write_text("18")
    with pytest.raises(ValueError, match="Restore"):
        embedded.control("start", directory, data_dir)


def test_ui_uses_persisted_password_over_ambient_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", dict(os.environ))
    path = tmp_path / "ui-secrets.json"
    path.write_text(json.dumps({"password": "saved-password", "admin_key": "saved-admin"}))
    path.chmod(0o600)
    monkeypatch.setenv("CONTEXTBASE_CP_ACCESS_KEY", "wrong")
    monkeypatch.setenv("HINDSIGHT_CP_DATAPLANE_API_KEY", "wrong")
    load_deployment_secrets(tmp_path, "ui")
    assert os.environ["CONTEXTBASE_CP_ACCESS_KEY"] == "saved-password"
    assert os.environ["HINDSIGHT_CP_DATAPLANE_API_KEY"] == "saved-admin"
