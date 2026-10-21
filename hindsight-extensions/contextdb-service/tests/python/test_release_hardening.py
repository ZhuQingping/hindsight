"""Real PG regressions for unified authentication and human-facing directory names."""

import asyncio

import pytest
from hindsight_ext_contextdb.bootstrap import (
    SYSTEM_ADMIN_NAME,
    initialize_administrator,
)
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    Role,
    ServiceError,
    UserCreate,
    UserPatch,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.security import key_digest

from .support.identities import ADMIN, ADMIN_SECRET, ready_workspace


async def test_admin_uses_same_pg_digest_and_is_hidden_and_protected(repository):
    principal = await repository.authenticate(ADMIN_SECRET)
    assert principal.role == Role.ADMIN
    row = await repository.pool.fetchrow(
        "SELECT digest,user_id FROM ctxdb_meta.api_keys WHERE key_id=$1", principal.key_id
    )
    assert row["digest"] == key_digest(ADMIN_SECRET, repository.pepper)
    assert (await repository.list_users(ADMIN, 20, 0)).total == 0
    for operation in [
        repository.update_user(ADMIN, row["user_id"], UserPatch(name="stolen"), 1, "x"),
        repository.update_user(ADMIN, row["user_id"], UserPatch(status="disabled"), None, "x", delete=True),
        repository.list_keys(ADMIN, row["user_id"], 20, 0),
        repository.create_key(ADMIN, row["user_id"], ApiKeyCreate(name="extra", authorization={"mode": "all"}), "x"),
        repository.revoke_key(ADMIN, row["user_id"], principal.key_id, "x"),
    ]:
        with pytest.raises(ServiceError) as error:
            await operation
        assert error.value.status == 404
    wrong = Repository(
        repository.pool,
        repository.instance_id,
        repository.cloud_tenant_id,
        "wrong-pepper-is-also-at-least32-characters",
    )
    with pytest.raises(ServiceError) as error:
        await wrong.authenticate(ADMIN_SECRET)
    assert error.value.status == 401


async def test_repeat_bootstrap_keeps_identity_and_rejects_wrong_pepper(repository):
    before = await repository.authenticate(ADMIN_SECRET)
    async with repository.pool.acquire() as conn, conn.transaction():
        await initialize_administrator(conn, ADMIN_SECRET, repository.pepper)
    assert await repository.authenticate(ADMIN_SECRET) == before
    async with repository.pool.acquire() as conn, conn.transaction():
        with pytest.raises(ValueError, match="does not match"):
            await initialize_administrator(conn, ADMIN_SECRET, "wrong-but-long-enough-pepper-123456789")


async def test_member_name_unique_across_disabled_and_normalized_spellings(repository):
    member = await repository.create_user(ADMIN, UserCreate(name="  Ａｌｉｃｅ  "), "create")
    assert member.name == "Alice"
    await repository.update_user(ADMIN, member.user_id, UserPatch(status="disabled"), member.version, "disable")
    for name in ["alice", "ALICE", "ＡＬＩＣＥ", " Alice "]:
        with pytest.raises(ServiceError) as error:
            await repository.create_user(ADMIN, UserCreate(name=name), "duplicate")
        assert error.value.status == 409
    other = await repository.create_user(ADMIN, UserCreate(name="Bob"), "bob")
    with pytest.raises(ServiceError) as error:
        await repository.update_user(ADMIN, other.user_id, UserPatch(name="ALICE"), other.version, "rename")
    assert error.value.status == 409
    with pytest.raises(ServiceError):
        await repository.create_user(ADMIN, UserCreate(name=SYSTEM_ADMIN_NAME), "reserved")


async def test_concurrent_member_names_and_deleted_name_reuse_do_not_restore_keys(repository):
    results = await asyncio.gather(
        *[repository.create_user(ADMIN, UserCreate(name="same"), str(i)) for i in range(4)], return_exceptions=True
    )
    users = [item for item in results if not isinstance(item, Exception)]
    assert len(users) == 1
    assert all(isinstance(item, ServiceError) and item.status == 409 for item in results if isinstance(item, Exception))
    user = users[0]
    key = await repository.create_key(
        ADMIN, user.user_id, ApiKeyCreate(name="old", authorization={"mode": "all"}), "key"
    )
    await repository.update_user(ADMIN, user.user_id, UserPatch(status="disabled"), None, "delete", delete=True)
    recreated = await repository.create_user(ADMIN, UserCreate(name="same"), "new")
    assert recreated.user_id != user.user_id
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret)


async def test_workspace_name_is_exact_normalized_query_not_uuid_fallback(repository):
    space = await ready_workspace(repository, "Jiamu")
    found = await repository.get_workspace_by_name(ADMIN, "jiamu")
    assert found.workspace_id == space.workspace_id
    for query in ["jia", space.workspace_id]:
        with pytest.raises(ServiceError) as error:
            await repository.get_workspace_by_name(ADMIN, query)
        assert error.value.status == 404
    operation = await repository.create_workspace(ADMIN, WorkspaceCreate(name="ＰＧ"), "pending")
    assert (await repository.get_workspace_by_name(ADMIN, "pg")).workspace_id == operation.workspace_id
    assert (await repository.get_workspace_by_name(ADMIN, "pg")).state == "creating"


async def test_usage_timestamp_is_throttled_but_revocation_is_immediate(repository):
    user = await repository.create_user(ADMIN, UserCreate(name="app"), "u")
    key = await repository.create_key(ADMIN, user.user_id, ApiKeyCreate(name="all", authorization={"mode": "all"}), "k")
    await repository.authenticate(key.secret, record_use=True)
    first = await repository.pool.fetchval(
        "SELECT last_used_at FROM ctxdb_meta.api_keys WHERE key_id=$1", key.metadata.key_id
    )
    await repository.authenticate(key.secret, record_use=True)
    assert (
        await repository.pool.fetchval(
            "SELECT last_used_at FROM ctxdb_meta.api_keys WHERE key_id=$1", key.metadata.key_id
        )
        == first
    )
    await repository.revoke_key(ADMIN, user.user_id, key.metadata.key_id, "revoke")
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret, record_use=True)


async def test_delete_reclaims_schema_and_grants_but_keeps_audit_without_replay(repository):
    old = await ready_workspace(repository, "same_name")
    await repository.pool.execute(
        f'CREATE SCHEMA "{old.schema_name}"; CREATE TABLE "{old.schema_name}".data(value text); INSERT INTO "{old.schema_name}".data VALUES(\'old\')'
    )
    user = await repository.create_user(ADMIN, UserCreate(name="app"), "u")
    key = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="old", authorization={"mode": "selected", "workspaces": [{"bank_id": old.bank_id}]}),
        "k",
    )
    deletion = await repository.delete_workspace(
        ADMIN, old.bank_id, "d", expected_id=old.workspace_id, expected_version=old.version
    )
    await repository.finish_workspace_deletion(deletion, ADMIN, "d")
    assert await repository.pool.fetchval("SELECT to_regnamespace($1)", old.schema_name) is None
    assert (
        await repository.pool.fetchval(
            "SELECT count(*) FROM ctxdb_meta.workspaces WHERE workspace_id=$1", old.workspace_id
        )
        == 0
    )
    assert (
        await repository.pool.fetchval(
            "SELECT count(*) FROM ctxdb_meta.audit_events WHERE workspace_id=$1", old.workspace_id
        )
        > 0
    )
    stored = (await repository.list_keys(ADMIN, user.user_id, 20, 0)).items[0]
    assert stored.authorization.mode == "selected" and stored.authorization.workspaces == []
    assert stored.version == 2
    recreated = await repository.create_workspace(ADMIN, WorkspaceCreate(name=old.name), "new")
    assert recreated.workspace_id != old.workspace_id
    with pytest.raises(ServiceError) as stale:
        await repository.delete_workspace(
            ADMIN, old.bank_id, "old-request", expected_id=old.workspace_id, expected_version=old.version
        )
    assert stale.value.status == 412
    with pytest.raises(ServiceError):
        await repository.authenticate(key.secret, old.bank_id)


async def test_workspace_drop_refuses_foreign_view_and_rolls_back_metadata(repository):
    space = await ready_workspace(repository)
    await repository.pool.execute(
        f'CREATE SCHEMA "{space.schema_name}"; CREATE TABLE "{space.schema_name}".data(value text); CREATE VIEW public.foreign_workspace_view AS SELECT * FROM "{space.schema_name}".data'
    )
    deleting = await repository.delete_workspace(
        ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
    )
    try:
        with pytest.raises(ServiceError) as error:
            await repository.finish_workspace_deletion(deleting, ADMIN, "finish")
        assert error.value.code == "schema_dependencies"
        assert (await repository.get_workspace(ADMIN, space.workspace_id)).state == "deleting"
        assert await repository.pool.fetchval("SELECT to_regnamespace($1)", space.schema_name)
    finally:
        await repository.pool.execute("DROP VIEW public.foreign_workspace_view")
    await repository.finish_workspace_deletion(deleting, ADMIN, "finish")
    assert await repository.pool.fetchval("SELECT to_regnamespace($1)", space.schema_name) is None


async def test_lifecycle_rejects_external_cascade_before_deleting_native_rows(repository):
    from unittest.mock import AsyncMock, Mock

    from hindsight_ext_contextdb.lifecycle import Lifecycle

    space = await ready_workspace(repository, "external_cascade")
    schema = space.schema_name
    await repository.pool.execute(
        f'CREATE SCHEMA "{schema}"; CREATE TABLE "{schema}".banks(id text PRIMARY KEY); INSERT INTO "{schema}".banks VALUES(\'bank\'); CREATE TABLE public.external_workspace_rows(id text REFERENCES "{schema}".banks(id) ON DELETE CASCADE); INSERT INTO public.external_workspace_rows VALUES(\'bank\')'
    )
    memory = Mock()
    memory.get_bank_profile = AsyncMock(return_value={"id": "bank"})
    memory.delete_bank = AsyncMock()
    memory._file_storage.delete_prefix = AsyncMock()
    try:
        with pytest.raises(ServiceError) as error:
            await Lifecycle(repository, memory, Mock()).delete(
                ADMIN, space.bank_id, "delete", expected_id=space.workspace_id, expected_version=space.version
            )
        assert error.value.code == "schema_dependencies"
        memory.get_bank_profile.assert_not_awaited()
        memory.delete_bank.assert_not_awaited()
        memory._file_storage.delete_prefix.assert_not_awaited()
        assert await repository.pool.fetchval("SELECT count(*) FROM public.external_workspace_rows") == 1
        assert await repository.pool.fetchval(f'SELECT count(*) FROM "{schema}".banks') == 1
        assert (await repository.get_workspace(ADMIN, space.workspace_id)).state == "failed"
    finally:
        await repository.pool.execute("DROP TABLE public.external_workspace_rows")
