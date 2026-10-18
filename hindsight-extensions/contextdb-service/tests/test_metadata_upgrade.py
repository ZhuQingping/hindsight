"""Real isolated PG verifies first-release installation and non-destructive refusal."""

from pathlib import Path

import asyncpg
import pytest
from hindsight_ext_contextdb.migrations import migrate_connection
from hindsight_ext_contextdb.models import ApiKeyCreate, ApiKeyPatch, Scope, ServiceError, UserCreate, WorkspaceCreate
from hindsight_ext_contextdb.repository import Repository
from pydantic import ValidationError

from .test_repository import ADMIN, ADMIN_SECRET, ready_workspace

FIXTURES = Path(__file__).parent / "fixtures/development-metadata"


async def test_latest_schema_constraints_and_comment_coverage(repository):
    missing = await repository.pool.fetchval("""
        SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
        WHERE n.nspname='ctxdb_meta' AND c.relkind='r'
          AND (obj_description(c.oid,'pg_class') IS NULL OR col_description(c.oid,a.attnum) IS NULL)
    """)
    assert missing == 0
    with pytest.raises(asyncpg.CheckViolationError):
        await repository.pool.execute(
            "INSERT INTO ctxdb_meta.deployment_info VALUES(false,'x','y',2,'contextdb-first-release',now())"
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await repository.pool.execute(
            "INSERT INTO ctxdb_meta.users(user_id,name,name_key,version) VALUES($1,'Name','name',0)", "b" * 32
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await repository.pool.execute(
            "INSERT INTO ctxdb_meta.users(user_id,name,name_key) VALUES($1,' ','invalid')", "b" * 32
        )


async def test_per_workspace_permissions_name_only_edit_and_revoked_pagination(repository):
    first = await ready_workspace(repository, "First")
    second = await ready_workspace(repository, "Second")
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "u")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(
            name="mixed",
            authorization={
                "mode": "selected",
                "workspaces": [
                    {"bank_id": first.bank_id, "permission": "read"},
                    {"bank_id": second.bank_id},
                ],
            },
        ),
        "k",
    )
    assert Scope.MEMORY_WRITE not in (await repository.authenticate(issued.secret, first.bank_id)).scopes
    assert Scope.MEMORY_WRITE in (await repository.authenticate(issued.secret, second.bank_id)).scopes
    changed = await repository.update_key(
        ADMIN, user.user_id, issued.metadata.key_id, ApiKeyPatch(name="renamed"), 1, "rename"
    )
    assert changed.authorization == issued.metadata.authorization
    assert changed.display_key == "ctx_live_***" + issued.secret[-6:]
    assert (await repository.authenticate(issued.secret, second.bank_id)).permission == "read_write"
    await repository.revoke_key(ADMIN, user.user_id, issued.metadata.key_id, "revoke")
    page = await repository.list_keys(ADMIN, user.user_id, 1, 0)
    assert page.total == 0 and page.items == []
    workspace = await repository.get_workspace(ADMIN, first.workspace_id)
    assert workspace.latest_operation_id is not None
    assert "instance_id" not in user.model_dump()


async def test_empty_selected_is_denied_and_all_cannot_commit_grants(repository):
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "u")
    key_id = "d" * 32
    await repository.pool.execute(
        "INSERT INTO ctxdb_meta.api_keys(key_id,user_id,name,digest,access_mode) VALUES($1,$2,'Empty',decode(repeat('ab',32),'hex'),'selected')",
        key_id,
        user.user_id,
    )
    key = (await repository.list_keys(ADMIN, user.user_id, 20, 0)).items[0]
    assert key.authorization.mode == "selected" and key.authorization.workspaces == []
    space = await ready_workspace(repository)
    with pytest.raises(asyncpg.CheckViolationError):
        async with repository.pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE ctxdb_meta.api_keys SET access_mode='all',permission='read' WHERE key_id=$1", key_id
            )
            await conn.execute(
                "INSERT INTO ctxdb_meta.key_workspace_permissions VALUES($1,$2,'read')", key_id, space.workspace_id
            )


async def test_repeat_initialization_preserves_native_data_and_table_privileges(repository):
    await repository.pool.execute(
        "CREATE SCHEMA native_upgrade_sentinel; CREATE TABLE native_upgrade_sentinel.banks(bank_id text); INSERT INTO native_upgrade_sentinel.banks VALUES('arbitrary-original-bank'); GRANT SELECT ON ctxdb_meta.users TO PUBLIC"
    )
    try:
        await initialize(repository)
        assert (
            await repository.pool.fetchval("SELECT bank_id FROM native_upgrade_sentinel.banks")
            == "arbitrary-original-bank"
        )
        assert await repository.pool.fetchval("SELECT has_table_privilege('public','ctxdb_meta.users','SELECT')")
    finally:
        await repository.pool.execute("DROP SCHEMA native_upgrade_sentinel CASCADE")


async def test_selected_grants_enforce_reference_and_permission_constraints(repository):
    space = await ready_workspace(repository)
    user = await repository.create_user(ADMIN, UserCreate(name="App"), "u")
    issued = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="one", authorization={"mode": "selected", "workspaces": [{"bank_id": space.bank_id}]}),
        "k",
    )
    for sql in [
        "UPDATE ctxdb_meta.key_workspace_permissions SET permission='admin'",
        "UPDATE ctxdb_meta.key_workspace_permissions SET workspace_id=repeat('f',32)",
    ]:
        with pytest.raises(asyncpg.IntegrityConstraintViolationError):
            await repository.pool.execute(sql)
    assert (await repository.authenticate(issued.secret, space.bank_id)).permission == "read_write"


@pytest.mark.parametrize(
    "instance_id,tenant_id", [("wrong-instance", "tenant-test"), ("instance-test", "wrong-tenant")]
)
async def test_internal_execution_paths_fail_closed_on_wrong_deployment(repository, instance_id, tenant_id):
    operation = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Binding"), "binding", "r")
    claimed = await repository.claim_operation()
    assert claimed is not None
    wrong = Repository(repository.pool, instance_id, tenant_id, repository.pepper)
    assert (
        await wrong.operation_is_owned(claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id)
        is False
    )
    assert await wrong.renew_operation(claimed) is False
    assert await wrong.claim_operation() is None
    for call in [
        wrong.operation_workspace(claimed),
        wrong.internal_workspace(operation.workspace_id, "ctxdb_ws_" + operation.workspace_id),
        wrong.maintenance_workspace("ctxdb_ws_" + operation.workspace_id),
        wrong.register_admission(
            "e" * 32, "owner", operation.workspace_id, "ctxdb_ws_" + operation.workspace_id, "http"
        ),
        wrong.finish_admission("e" * 32, "owner", interrupted=False),
        wrong.has_outstanding_admissions(operation.workspace_id),
        wrong.complete_operation(claimed),
    ]:
        with pytest.raises(ServiceError):
            await call
    assert await repository.operation_is_owned(
        claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id
    )


async def test_normalization_expansion_rejected_before_persistence(repository):
    # U+FDFA expands to eighteen codepoints under NFKC; validate after expansion.
    with pytest.raises(ValidationError):
        WorkspaceCreate(name="\ufdfa" * 4)
    assert (await repository.list_workspaces(ADMIN, 20, 0)).total == 0


async def test_repeat_initialization_is_independent_of_role_search_path(repository):
    async with repository.pool.acquire() as conn:
        await conn.execute("SET search_path=ctxdb_meta,public")
        try:
            await migrate_connection(
                conn,
                repository.instance_id,
                repository.cloud_tenant_id,
                pepper=repository.pepper,
                admin_secret=ADMIN_SECRET,
            )
        finally:
            await conn.execute("RESET search_path")
    await repository.verify_schema()


async def initialize(repository: Repository) -> None:
    async with repository.pool.acquire() as conn:
        await migrate_connection(
            conn,
            repository.instance_id,
            repository.cloud_tenant_id,
            pepper=repository.pepper,
            admin_secret=ADMIN_SECRET,
        )


async def test_fresh_installation_starts_at_one_and_repeat_preserves_identity(repository):
    from hindsight_ext_contextdb import METADATA_VERSION

    await repository.pool.execute("DROP SCHEMA ctxdb_meta CASCADE")
    await initialize(repository)
    assert METADATA_VERSION == 1
    assert await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == 1
    before = await repository.pool.fetchrow(
        "SELECT installed_at,(SELECT oid FROM pg_class WHERE oid='ctxdb_meta.users'::regclass) AS users_oid,"
        "(SELECT user_id FROM ctxdb_meta.users WHERE role='admin') AS admin_id FROM ctxdb_meta.deployment_info"
    )
    await initialize(repository)
    after = await repository.pool.fetchrow(
        "SELECT installed_at,(SELECT oid FROM pg_class WHERE oid='ctxdb_meta.users'::regclass) AS users_oid,"
        "(SELECT user_id FROM ctxdb_meta.users WHERE role='admin') AS admin_id FROM ctxdb_meta.deployment_info"
    )
    assert before == after
    await repository.verify_schema()
    assert (await repository.authenticate(ADMIN_SECRET)).role == "admin"


@pytest.mark.parametrize("development_version", [2, 3, 4, 99])
async def test_unsupported_versions_are_never_renumbered(repository, development_version):
    await repository.pool.execute(
        "ALTER TABLE ctxdb_meta.deployment_info DROP CONSTRAINT deployment_info_metadata_version_check"
    )
    await repository.pool.execute("UPDATE ctxdb_meta.deployment_info SET metadata_version=$1", development_version)
    before = await repository.pool.fetch("SELECT key_id,digest FROM ctxdb_meta.api_keys ORDER BY key_id")
    with pytest.raises(ValueError, match="not automatically upgraded or renumbered"):
        await initialize(repository)
    assert (
        await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == development_version
    )
    assert await repository.pool.fetch("SELECT key_id,digest FROM ctxdb_meta.api_keys ORDER BY key_id") == before
    with pytest.raises(RuntimeError, match="Unsupported"):
        await repository.verify_schema()


@pytest.mark.parametrize("development_version", [1, 2])
async def test_unreleased_layouts_are_rejected_even_if_labelled_one(repository, development_version):
    await repository.pool.execute("DROP SCHEMA ctxdb_meta CASCADE")
    await repository.pool.execute((FIXTURES / f"development_v{development_version}.sql").read_text())
    if development_version == 2:
        await repository.pool.execute(
            "INSERT INTO ctxdb_meta.deployment_info(instance_id,cloud_tenant_id,metadata_version,format_id) "
            "VALUES('instance-test','tenant-test',2,'contextdb-first-release')"
        )
    before = await repository.pool.fetchval("SELECT 'ctxdb_meta.users'::regclass::oid")
    with pytest.raises(ValueError, match="new database"):
        await initialize(repository)
    assert await repository.pool.fetchval("SELECT 'ctxdb_meta.users'::regclass::oid") == before
    assert not await repository.pool.fetchval("SELECT EXISTS(SELECT 1 FROM ctxdb_meta.users)")
    if development_version == 1:
        assert await repository.pool.fetchval("SELECT to_regclass('ctxdb_meta.deployment_info')") is None
        assert await repository.pool.fetchval("SELECT version FROM ctxdb_meta.schema_versions") == 1
    else:
        assert await repository.pool.fetchval("SELECT metadata_version FROM ctxdb_meta.deployment_info") == 2


async def test_fresh_installation_rolls_back_if_administrator_import_fails(repository, monkeypatch):
    async def fail_import(*args):
        raise RuntimeError("synthetic administrator import failure")

    monkeypatch.setattr("hindsight_ext_contextdb.migrations.initialize_administrator", fail_import)
    await repository.pool.execute("DROP SCHEMA ctxdb_meta CASCADE")
    with pytest.raises(RuntimeError, match="synthetic administrator import failure"):
        await initialize(repository)
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_meta')") is None
