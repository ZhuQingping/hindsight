"""Local entrypoints must initialize authentication before exposing any service."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
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
        assert prefix + "PUBLIC_ORIGIN" not in ui
        assert ui[prefix + "PUBLIC_API_PORT"] == "8888"
    for filename in ("api.env", "ui.env"):
        assert (local_environment / filename).stat().st_mode & 0o777 == 0o600
    assert "synthetic-provider-key" not in (local_environment / "ui.env").read_text()


@pytest.mark.parametrize(
    "failure", ["database", "extensions", "configuration", "credentials", "migration", "serve", None]
)
def test_local_start_initializes_before_serving_and_stops_pg(
    local_environment: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], failure: str | None
) -> None:
    events: list[str] = []
    configure = local.configure

    def control(command: str, directory: Path, data_dir: Path) -> DatabaseConnection | None:
        assert directory == local_environment
        assert data_dir == directory / "pgdata"
        events.append(command)
        if command == "start" and failure == "database":
            raise ValueError("synthetic secret must not escape")
        return DatabaseConnection(uri="postgresql://synthetic") if command == "start" else None

    async def extensions(url: str) -> None:
        events.append("extensions")
        if failure == "extensions":
            raise ValueError("synthetic secret must not escape")

    async def credentials(*args: object) -> None:
        events.append("credentials")
        if failure == "credentials":
            raise ValueError("synthetic secret must not escape")

    def configuration(directory: Path, url: str, api_port: int, ui_port: int) -> None:
        events.append("configuration")
        if failure == "configuration":
            raise ValueError("synthetic secret must not escape")
        configure(directory, url, api_port, ui_port)

    def migrate(*args: object, **kwargs: object) -> None:
        events.append("migration")
        if failure == "migration":
            raise subprocess.CalledProcessError(2, ["init", "synthetic secret must not escape"])

    def serve(*args: object) -> int:
        events.append("serve")
        if failure == "serve":
            raise OSError("synthetic secret must not escape")
        return 0

    monkeypatch.setattr(local, "pg_control", control)
    monkeypatch.setattr(local, "enable_extensions", extensions)
    monkeypatch.setattr(local, "configure", configuration)
    monkeypatch.setattr(local, "prepare_deployment", credentials)
    monkeypatch.setattr(local.subprocess, "run", migrate)
    monkeypatch.setattr(local, "serve", serve)
    with pytest.raises(SystemExit) as result:
        local.main()
    assert result.value.code == (2 if failure else 0)
    expected = ["start", "extensions", "configuration", "credentials", "migration", "serve"]
    if failure:
        expected = expected[
            : expected.index(
                {
                    "database": "start",
                    "extensions": "extensions",
                    "configuration": "configuration",
                    "credentials": "credentials",
                    "migration": "migration",
                    "serve": "serve",
                }[failure]
            )
            + 1
        ]
    assert events == expected + ([] if failure == "database" else ["stop"])
    diagnostic = capsys.readouterr().err
    assert "synthetic secret must not escape" not in diagnostic
    if failure:
        stage = {
            "database": "embedded database startup",
            "extensions": "extension initialization",
            "configuration": "configuration",
            "credentials": "credential bootstrap",
            "migration": "deployment initialization",
            "serve": "service launch",
        }[failure]
        assert f"Local initialization failed during {stage}" in diagnostic
        assert "test_local_deployment.py:" in diagnostic
        exception = {"migration": "CalledProcessError", "serve": "OSError"}.get(failure, "ValueError")
        assert exception in diagnostic


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
    stopped = SimpleNamespace(running=False)
    running = SimpleNamespace(running=True, uri="postgresql://synthetic", data_dir=str(data_dir))
    fake.info.side_effect = [stopped, running, stopped, running]
    constructor = Mock(return_value=fake)
    runner = Mock()
    monkeypatch.setitem(sys.modules, "pg0", SimpleNamespace(Pg0=constructor, _run_pg0=runner))
    embedded.control("start", directory, data_dir)
    before = (directory / "pg-secrets.json").read_bytes()
    embedded.control("start", directory, data_dir)
    assert (directory / "pg-secrets.json").read_bytes() == before
    assert constructor.call_args.kwargs["data_dir"] == str(data_dir)
    (directory / "pg-secrets.json").unlink()
    (data_dir / "PG_VERSION").write_text("18")
    with pytest.raises(ValueError, match="Restore"):
        embedded.control("start", directory, data_dir)


@pytest.mark.parametrize("prefix", ["-a", "--", "_a", "aa"])
def test_pg_password_is_one_literal_cli_value_and_never_rotated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prefix: str
) -> None:
    directory = tmp_path / "runtime"
    data_dir = directory / "pgdata"
    private_directory(directory)
    secret = embedded.DatabaseSecret(password=prefix + "synthetic-password-" * 4)
    embedded.save_credential(directory / "pg-secrets.json", secret)
    before = (directory / "pg-secrets.json").read_bytes()
    fake = Mock()
    fake.info.side_effect = [None, SimpleNamespace(running=True, uri="postgresql://synthetic", data_dir=str(data_dir))]
    fake.start.side_effect = AssertionError("The SDK's split password argv is unsafe")
    runner = Mock()
    monkeypatch.setitem(sys.modules, "pg0", SimpleNamespace(Pg0=Mock(return_value=fake), _run_pg0=runner))
    assert embedded.control("start", directory, data_dir).uri == "postgresql://synthetic"
    assert runner.call_args.args.count("--password=" + secret.password) == 1
    assert "--password" not in runner.call_args.args
    assert (directory / "pg-secrets.json").read_bytes() == before


def test_pg0_cli_accepts_a_leading_dash_password_as_a_literal() -> None:
    from pg0 import _run_pg0

    # --help exercises the real parser on every platform without starting PG.
    assert _run_pg0("start", "--password=-synthetic-password", "--help").returncode == 0


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


@pytest.mark.parametrize("arguments", [["--ui-port", "10001"], ["--random-port"]])
def test_ui_only_port_override_reaches_service_without_rewriting_state(
    local_environment: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    local.configure(local_environment, "postgresql://synthetic", 8888, 9999)
    before = (local_environment / "ui.env").read_bytes()
    monkeypatch.setattr(sys, "argv", ["local", "--component", "ui", *arguments])
    serve = Mock(return_value=0)
    monkeypatch.setattr(local, "serve", serve)
    with pytest.raises(SystemExit) as result:
        local.main()
    assert result.value.code == 0
    port = int(serve.call_args.args[1]["CONTEXTDB_LOCAL_UI_PORT"])
    assert 1024 <= port <= 65535
    if arguments[0] == "--ui-port":
        assert port == 10001
    assert (local_environment / "ui.env").read_bytes() == before


@pytest.mark.parametrize("origin", ["http://localhost:9999", "https://memory.example.com"])
def test_ui_launch_applies_override_after_persisted_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    from hindsight_ext_contextdb.launch import launch

    monkeypatch.setattr(
        os,
        "environ",
        {
            **os.environ,
            "CONTEXTDB_UI_DEV": "1",
            "CONTEXTDB_LOCAL_UI_PORT": "10001",
            "CONTEXTBASE_CP_PORT": "9999",
            "CONTEXTBASE_CP_PUBLIC_ORIGIN": origin,
            "CONTEXTBASE_CP_DATAPLANE_API_URL": "http://127.0.0.1:8888",
        },
    )
    path = tmp_path / "ui-secrets.json"
    path.write_text(json.dumps({"password": "saved-password", "admin_key": "saved-admin"}))
    path.chmod(0o600)
    monkeypatch.setattr(os, "chdir", Mock())
    monkeypatch.setattr(subprocess, "run", Mock())
    monkeypatch.setattr(os, "execvp", Mock(side_effect=RuntimeError("exec intercepted")))
    with pytest.raises(RuntimeError, match="exec intercepted"):
        launch("ui", tmp_path, tmp_path)
    assert os.environ["PORT"] == "10001"
    assert os.environ["CONTEXTBASE_CP_PORT"] == os.environ["HINDSIGHT_CP_PORT"] == "10001"
    expected = "http://localhost:10001" if origin.startswith("http://localhost:") else origin
    assert os.environ["CONTEXTBASE_CP_PUBLIC_ORIGIN"] == expected
    assert os.environ["CONTEXTBASE_CP_DATAPLANE_API_URL"] == "http://127.0.0.1:8888"
    assert os.environ["CONTEXTBASE_CP_ACCESS_KEY"] == "saved-password"


@pytest.mark.parametrize("origin,public_port", [("", None), ("", "18080"), ("", ""), ("https://ui.test", None)])
def test_local_public_port_uses_api_port_only_for_dynamic_mode(
    local_environment: Path, monkeypatch: pytest.MonkeyPatch, origin: str, public_port: str | None
) -> None:
    monkeypatch.setenv("CONTEXTBASE_CP_PUBLIC_ORIGIN", origin)
    if public_port is not None:
        monkeypatch.setenv("CONTEXTBASE_CP_PUBLIC_API_PORT", public_port)
    local.configure(local_environment, "postgresql://synthetic", 18888, 19999)
    ui = dotenv_values(local_environment / "ui.env")
    if origin:
        assert "CONTEXTBASE_CP_PUBLIC_API_PORT" not in ui
    else:
        assert ui["CONTEXTBASE_CP_PUBLIC_API_PORT"] == ("18888" if public_port is None else public_port)
