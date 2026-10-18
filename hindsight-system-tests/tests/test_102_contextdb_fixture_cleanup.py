"""Force ContextDB fixture failures without creating a database or child process."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from unittest.mock import ANY, AsyncMock, Mock

import pytest


def load_system_module(monkeypatch: pytest.MonkeyPatch, path: Path, name: str) -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, root / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve annotations through sys.modules when a file is loaded.
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_readiness_failure_stops_unreturned_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_system_module(
        monkeypatch, Path("hindsight_system_tests/server.py"), "hindsight_system_tests.ctxdb_cleanup_server"
    )
    process = Mock()
    spawn = Mock(return_value=process)
    monkeypatch.setattr(module.subprocess, "Popen", spawn)
    monkeypatch.setattr(module, "free_port", lambda: 43210)
    monkeypatch.setattr(module, "_wait_until_healthy", Mock(side_effect=AssertionError("synthetic readiness failure")))
    with pytest.raises(AssertionError, match="synthetic readiness failure"):
        module.start_hindsight_server(
            stub_url="http://unused.invalid", log_path=tmp_path / "server.log", python_executable="unused-python"
        )
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert spawn.call_args.kwargs["stdout"].closed


@dataclass
class TemporaryFactory:
    path: Path

    def mktemp(self, name: str) -> Path:
        return self.path


@dataclass
class FixtureRequest:
    param: str = "embedded-worker"


@dataclass
class ProviderStub:
    url: str = "http://unused.invalid"


def test_bootstrap_failure_stops_owned_pg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_system_module(monkeypatch, Path("tests/test_100_contextdb_service.py"), "ctxdb_cleanup_story")
    pg = Mock()
    pg.start.return_value.uri = "postgresql://synthetic-unused"
    connection = Mock()
    connection.close = AsyncMock()
    # Provisioning now uses the ordered offline migration, so inject failure at
    # that boundary; the cleanup property is unchanged and still fully asserted.
    migration = AsyncMock(side_effect=RuntimeError("synthetic bootstrap failure"))
    monkeypatch.setattr("hindsight_ext_contextdb.migrations.migrate_connection", migration)
    monkeypatch.setattr(module, "Pg0", Mock(return_value=pg))
    monkeypatch.setattr(module.asyncpg, "connect", AsyncMock(return_value=connection))
    start_server = Mock(side_effect=AssertionError("server must not start after failed bootstrap"))
    monkeypatch.setattr(module, "start_hindsight_server", start_server)
    fixture = module.contextdb_deployment.__wrapped__(FixtureRequest(), ProviderStub(), TemporaryFactory(tmp_path))
    with pytest.raises(RuntimeError, match="synthetic bootstrap failure"):
        next(fixture)
    pg.stop.assert_called_once()
    migration.assert_awaited_once_with(
        connection, "story-instance", "story-tenant", pepper="synthetic-story-pepper-32-bytes-long", admin_secret=ANY
    )
    assert migration.await_args.kwargs["admin_secret"].startswith("ctx_admin_")
    connection.close.assert_awaited_once()
    start_server.assert_not_called()
