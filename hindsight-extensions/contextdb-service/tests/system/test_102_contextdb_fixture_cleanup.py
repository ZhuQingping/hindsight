"""Force ContextDB fixture failures without creating a database or child process."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, AsyncMock, Mock

import httpx
import pytest


def test_readiness_failure_stops_unreturned_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hindsight_system_tests import server as module

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


def test_bootstrap_failure_stops_owned_pg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from .support import deployment as module

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
    owner = module.deployment_owner(module.DeploymentOptions(), "http://unused.invalid", tmp_path)
    with pytest.raises(RuntimeError, match="synthetic bootstrap failure"):
        with owner:
            pytest.fail("Failed bootstrap must not yield a deployment")
    pg.stop.assert_called_once()
    migration.assert_awaited_once_with(
        connection, "story-instance", "story-tenant", pepper="synthetic-story-pepper-32-bytes-long", admin_secret=ANY
    )
    assert migration.await_args.kwargs["admin_secret"].startswith("ctx_admin_")
    connection.close.assert_awaited_once()
    start_server.assert_not_called()


@pytest.mark.asyncio
async def test_client_provisioning_failure_closes_already_created_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    from .support import clients as module
    from .support.deployment import ContextDBDeployment

    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.post = AsyncMock(
        side_effect=[
            httpx.Response(201, json={"bank_id": "first", "state": "active"}),
            httpx.Response(201, json={"bank_id": "other", "state": "active"}),
            httpx.Response(201, json={"user_id": "first-user"}),
            httpx.Response(201, json={"secret": "synthetic-first-key"}),
            RuntimeError("synthetic second client provisioning failure"),
        ]
    )
    client = Mock(aclose=AsyncMock())
    monkeypatch.setattr(module.httpx, "AsyncClient", Mock(return_value=session))
    monkeypatch.setattr(module, "Hindsight", Mock(return_value=client))
    deployment = ContextDBDeployment(Mock(url="http://unused.invalid"), {})
    with pytest.raises(RuntimeError, match="second client"):
        async with module.clients_owner(deployment):
            pytest.fail("Failed provisioning must not yield clients")
    client.aclose.assert_awaited_once()


@pytest.mark.parametrize("failure", [None, "missing_manifest", "changed_bundle", "other_source", "wrong_layout"])
def test_external_ui_artifact_is_verified_against_selected_bundle_and_checkout(
    tmp_path: Path, failure: str | None
) -> None:
    from hindsight_ext_contextdb.artifacts import (
        UiBuild,
        bundle_fingerprint,
        source_fingerprint,
    )

    from .support.ui import verify_ui_server

    checkout, built = tmp_path / "api-checkout", tmp_path / "isolated-build"
    for root in (checkout, built):
        for relative in (
            "hindsight-control-plane/src/page.tsx",
            "hindsight-clients/typescript/src/index.ts",
            "package-lock.json",
            "hindsight-control-plane/next.config.ts",
            "hindsight-control-plane/package.json",
            "hindsight-clients/typescript/package.json",
        ):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic-matching-source")
    server = built / "hindsight-control-plane/standalone/server.js"
    server.parent.mkdir(parents=True)
    server.write_text("// synthetic compiled server")
    manifest = server.with_name("contextdb-release.json")
    manifest.write_text(
        UiBuild(
            source_sha256=source_fingerprint(built), bundle_sha256=bundle_fingerprint(server.parent)
        ).model_dump_json()
    )
    if failure == "missing_manifest":
        manifest.unlink()
    elif failure == "changed_bundle":
        server.write_text("// changed compiled server")
    elif failure == "other_source":
        (checkout / "hindsight-control-plane/src/page.tsx").write_text("different-api-checkout-source")
    elif failure == "wrong_layout":
        server = server.with_name("unrelated-server.js")
        server.write_text("// unrelated entrypoint")
    if failure is None:
        # The API checkout intentionally has no standalone bundle. Validation
        # must use the explicitly selected isolated build, then compare sources.
        verify_ui_server(server, checkout)
    else:
        with pytest.raises(ValueError):
            verify_ui_server(server, checkout)
