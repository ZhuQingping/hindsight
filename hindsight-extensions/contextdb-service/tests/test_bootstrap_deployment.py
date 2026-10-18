"""Private credential persistence, offline import, and read-only deployment probes."""

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from hindsight_ext_contextdb.bootstrap import (
    AdministratorCredential,
    ApiSecrets,
    UiSecrets,
    prepare_deployment,
    read_credential,
    rotate_administrator,
    save_credential,
)
from hindsight_ext_contextdb.migrations import migrate_connection
from hindsight_ext_contextdb.models import ApiKeyCreate, ServiceError, UserCreate
from hindsight_ext_contextdb.preflight import preflight
from hindsight_ext_contextdb.security import issue_admin_key

from .test_repository import ADMIN, ADMIN_SECRET


async def test_source_service_init_is_repeatable_without_api_or_embedded_fallback(repository, database_url, tmp_path):
    available = set(await repository.pool.fetchval("SELECT array_agg(name) FROM pg_available_extensions"))
    if not {"vector", "pg_trgm", "btree_gin"} <= available:
        pytest.skip("Fixture PG distribution lacks the source-deployment profile extensions")
    for extension in ["vector", "pg_trgm", "btree_gin"]:
        await repository.pool.execute(f'CREATE EXTENSION IF NOT EXISTS "{extension}"')
    await repository.pool.execute("DROP SCHEMA ctxdb_meta CASCADE")
    directory = tmp_path / "service"
    directory.mkdir(mode=0o700)
    environment = {
        "HINDSIGHT_API_DATABASE_URL": database_url,
        "CONTEXTDB_INSTANCE_ID": repository.instance_id,
        "CONTEXTDB_CLOUD_TENANT_ID": repository.cloud_tenant_id,
        "HINDSIGHT_API_TEXT_SEARCH_EXTENSION": "native",
        "HINDSIGHT_API_LLM_TRACE_ENABLED": "false",
    }
    path = directory / "api.env"
    path.write_text("".join(f"{key}={shlex.quote(value)}\n" for key, value in environment.items()))
    path.chmod(0o600)
    script = Path(__file__).parents[1] / "scripts/service.sh"
    process_env = {key: value for key, value in os.environ.items() if not key.startswith(("HINDSIGHT_", "CONTEXTDB_"))}
    process_env.update(CONTEXTDB_DEPLOY_DIR=str(directory), CONTEXTDB_PYTHON=sys.executable)
    for _ in range(2):
        result = subprocess.run([str(script), "init"], env=process_env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.users WHERE role='admin'") == 1
    credential = read_credential(directory / "admin-key.json")
    assert credential.secret not in result.stdout + result.stderr


def test_credential_save_is_private_atomic_and_never_overwrites(tmp_path):
    key = issue_admin_key()
    credential = AdministratorCredential(key_id=key.key_id, secret=key.secret, sha256=key.digest.hex())
    path = tmp_path / "private" / "admin.json"
    save_credential(path, credential)
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_credential(path) == credential
    with pytest.raises(FileExistsError):
        save_credential(path, credential)
    assert not list(path.parent.glob(".admin-*"))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        read_credential(path)


async def test_prepare_before_initialization_preserves_all_secrets_and_rejects_loss(repository, database_url, tmp_path):
    await repository.pool.execute("DROP SCHEMA ctxdb_meta CASCADE")
    directory = tmp_path / "private"
    await prepare_deployment(directory, database_url, "custom-ui-password")
    originals = {path.name: path.read_bytes() for path in directory.iterdir()}
    await prepare_deployment(directory, database_url, "different-must-not-replace")
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == originals
    credential = read_credential(directory / "admin-key.json")
    api = ApiSecrets.model_validate_json((directory / "api-secrets.json").read_text())
    ui = UiSecrets.model_validate_json((directory / "ui-secrets.json").read_text())
    assert ui.admin_key == credential.secret and ui.password == "custom-ui-password"
    async with repository.pool.acquire() as connection:
        await migrate_connection(
            connection,
            repository.instance_id,
            repository.cloud_tenant_id,
            pepper=api.pepper,
            admin_secret=credential.secret,
        )
    (directory / "api-secrets.json").unlink()
    with pytest.raises(ValueError, match="missing"):
        await prepare_deployment(directory, database_url)
    assert (directory / "admin-key.json").read_bytes() == originals["admin-key.json"]
    assert not (directory / "api-secrets.json").exists()


async def test_offline_rotation_invalidates_only_the_admin_and_is_repeatable(repository):
    user = await repository.create_user(ADMIN, UserCreate(name="application"), "user")
    business = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="app", authorization={"mode": "all"}), "key"
    )
    replacement = issue_admin_key()
    before = (await repository.authenticate(ADMIN_SECRET)).user_id
    async with repository.pool.acquire() as conn, conn.transaction():
        await rotate_administrator(conn, replacement.secret, repository.pepper)
    assert (await repository.authenticate(replacement.secret)).user_id == before
    with pytest.raises(ServiceError):
        await repository.authenticate(ADMIN_SECRET)
    assert (await repository.authenticate(business.secret)).user_id == user.user_id
    async with repository.pool.acquire() as conn, conn.transaction():
        await rotate_administrator(conn, replacement.secret, repository.pepper)
    assert (
        await repository.pool.fetchval(
            "SELECT count(*) FROM ctxdb_meta.audit_events WHERE action='offline_admin_rotation'"
        )
        == 1
    )


async def test_preflight_reports_missing_plugins_and_never_claims_chinese_native_support(
    repository, database_url, monkeypatch
):
    monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", database_url)
    monkeypatch.setenv("HINDSIGHT_API_TEXT_SEARCH_EXTENSION", "native")
    report = await preflight(language="chinese")
    assert not report.passed
    assert any(item.name == "chinese_fulltext" and item.status == "fail" for item in report.checks)
    assert ADMIN_SECRET not in report.model_dump_json() and repository.pepper not in report.model_dump_json()
    assert await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == 1


async def test_api_and_ui_launch_environments_are_separate(tmp_path, monkeypatch):
    from hindsight_ext_contextdb.launch import launch

    monkeypatch.setattr("hindsight_ext_contextdb.launch.verify_ui_build", lambda root: None)

    directory = tmp_path / "private"
    save_credential(directory / "ui-secrets.json", UiSecrets(password="ui-password", admin_key=ADMIN_SECRET))
    server = tmp_path / "source" / "hindsight-control-plane" / "standalone" / "server.js"
    server.parent.mkdir(parents=True)
    server.write_text("// fixture")
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", "must-not-reach-ui")
    monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-ui")
    monkeypatch.setenv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "true")

    class Executed(Exception):
        pass

    def execute(program, args):
        import os

        assert "CONTEXTDB_KEY_PEPPER" not in os.environ and "HINDSIGHT_API_DATABASE_URL" not in os.environ
        assert "OPENAI_API_KEY" not in os.environ
        assert os.environ["HINDSIGHT_CP_DATAPLANE_API_KEY"] == ADMIN_SECRET
        assert os.environ["HOSTNAME"] == "0.0.0.0"
        raise Executed

    monkeypatch.setattr("os.execvp", execute)
    # launch replaces os.environ, so keep test isolation with a complete snapshot.
    import os

    original = dict(os.environ)
    try:
        with pytest.raises(Executed):
            launch("ui", directory, tmp_path / "source")
    finally:
        os.environ.clear()
        os.environ.update(original)
