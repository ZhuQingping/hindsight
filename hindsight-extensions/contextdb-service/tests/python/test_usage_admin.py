"""Offline usage upgrades do not run public business migrations or rotate keys."""

import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

import pytest

from hindsight_ext_contextdb.__main__ import main
from hindsight_ext_contextdb.bootstrap import AdministratorCredential, ApiSecrets, save_credential
from hindsight_ext_contextdb.usage_admin import maintain_usage
from hindsight_ext_contextdb.usage_repository import UsageDelta, UsageRepository, UsageTarget

from ..paths import EXTENSION
from .support.identities import ADMIN_SECRET, ready_workspace


async def test_offline_upgrade_is_repeatable_and_reset_clears_imported_stats(
    repository, configured, database_url, monkeypatch, tmp_path
):
    monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", database_url)
    monkeypatch.setenv("CONTEXTBASE_API_DATABASE_URL", database_url)
    workspace = await ready_workspace(repository)
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    credential = tmp_path / "admin.json"
    save_credential(credential, AdministratorCredential(key_id="a" * 32, secret=ADMIN_SECRET))
    assert await maintain_usage("upgrade-usage", credential, None) == 1
    assert await maintain_usage("upgrade-usage", credential, None) == 1
    target = UsageTarget(workspace.workspace_id, workspace.bank_id, workspace.schema_name)
    await UsageRepository(repository.pool).write(
        target, [UsageDelta("knowledge_page", "page", 3, datetime.now(timezone.utc))]
    )
    assert await maintain_usage("reset-usage", credential, workspace.bank_id) == 1
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0
    assert await repository.pool.fetchval("SELECT to_regclass('public.banks')") is None
    assert await repository.pool.fetchval("SELECT to_regclass('public.ctxdb_usage_stats')") is None
    # The existing administrator remains valid: upgrade/reset do not rotate it.
    assert (await repository.authenticate_admin(ADMIN_SECRET)).role.value == "admin"


@pytest.mark.parametrize(
    "arguments", [["upgrade-usage"], ["reset-usage", "--offline"], ["reset-usage", "--admin-key-file", "private.json"]]
)
def test_maintenance_requires_offline_and_explicit_credential(monkeypatch, arguments):
    monkeypatch.setattr(sys, "argv", ["contextdb", *arguments])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


async def test_successful_cli_loads_directory_secret_and_does_not_rotate_admin(
    repository, configured, database_url, tmp_path
):
    workspace = await ready_workspace(repository)
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    directory = tmp_path / "private"
    credential = directory / "admin-key.json"
    save_credential(credential, AdministratorCredential(key_id="a" * 32, secret=ADMIN_SECRET))
    save_credential(directory / "api-secrets.json", ApiSecrets(pepper=configured.pepper))
    environment = {
        **os.environ,
        "PYTHONPATH": str(EXTENSION),
        "PYTHON_DOTENV_DISABLED": "1",
        "HINDSIGHT_API_DATABASE_URL": database_url,
        "CONTEXTBASE_API_DATABASE_URL": database_url,
        # Success proves --directory loaded the persisted value, not this one.
        "CONTEXTDB_KEY_PEPPER": "incorrect-environment-pepper-at-least-32-characters",
    }
    for command in ("upgrade-usage", "reset-usage"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "hindsight_ext_contextdb",
                command,
                "--offline",
                "--directory",
                str(directory),
                "--admin-key-file",
                str(credential),
                "--bank-id",
                workspace.bank_id,
            ],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert "completed for 1 workspace" in result.stdout
        assert ADMIN_SECRET not in result.stdout + result.stderr
    assert (await repository.authenticate_admin(ADMIN_SECRET)).role.value == "admin"


async def test_native_single_schema_backup_restore_and_old_archive_reset(
    repository, configured, database_url, monkeypatch, tmp_path
):
    from hindsight_api.admin.cli import _backup, _effective_backup_tables, _restore

    from hindsight_ext_contextdb.usage_repository import provision_usage_tables

    workspace = await ready_workspace(repository)
    target = UsageTarget(workspace.workspace_id, workspace.bank_id, workspace.schema_name)
    async with repository.pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
        await provision_usage_tables(conn, workspace.schema_name)
    monkeypatch.setenv("HINDSIGHT_API_TENANT_EXTENSION", "hindsight_ext_contextdb.tenant:ContextDBTenantExtension")
    assert "ctxdb_usage_stats" in _effective_backup_tables()
    usage = UsageRepository(repository.pool)
    archive = tmp_path / "usage.zip"
    # Invoke the real native COPY/manifest/restore implementation, restricted to
    # the plugin table. Native content roundtrips have their own core tests.
    await usage.write(target, [UsageDelta("knowledge_page", "page", 7, datetime.now(timezone.utc))])
    await _backup(database_url, archive, target.schema_name, backup_tables=["ctxdb_usage_stats"])
    await usage.reset(target)
    await _restore(database_url, archive, target.schema_name, backup_tables=["ctxdb_usage_stats"])
    assert await repository.pool.fetchval(f"SELECT recall_count FROM {target.table()}") == 7
    # Restore does not reset ContextDB stats by itself; the required offline
    # plugin step runs before access is opened.
    await usage.reset(target)
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0
    old = tmp_path / "old.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(old, "w") as output:
        manifest = json.loads(source.read("manifest.json"))
        manifest["tables"].pop("ctxdb_usage_stats")
        output.writestr("manifest.json", json.dumps(manifest))
    await usage.write(target, [UsageDelta("knowledge_page", "page", 2, datetime.now(timezone.utc))])
    await _restore(database_url, old, target.schema_name, backup_tables=["ctxdb_usage_stats"])
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0


@pytest.mark.parametrize(
    "kind,ids,status",
    [
        ("memory", ["not-a-uuid"], 400),
        ("invalid", ["page"], 400),
        ("knowledge_page", ["page"] * 101, 400),
        ("knowledge_page", ["page"], 503),
    ],
)
async def test_management_usage_validation_and_unavailable_are_not_zero(repository, management, kind, ids, status):
    workspace = await ready_workspace(repository)
    response = await management.client.get(
        f"workspaces/{workspace.bank_id}/usage",
        params=[("object_type", kind), *(("ids", value) for value in ids)],
        headers=management.admin_headers,
    )
    assert response.status_code == status
    assert "items" not in response.json()
