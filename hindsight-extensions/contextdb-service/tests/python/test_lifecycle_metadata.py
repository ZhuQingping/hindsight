"""Synchronous lifecycle failures use owned disposable PG and native-call doubles."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import asyncpg
import pytest
from hindsight_ext_contextdb.models import ServiceError, WorkspaceCreate

from .support.identities import ADMIN, ready_workspace
from .support.lifecycle import lifecycle_for


async def test_create_delete_have_short_transactions_and_success_audit(repository):
    lifecycle = lifecycle_for(repository)
    workspace = await lifecycle.create(ADMIN, WorkspaceCreate(name="sync", description="Description"), "create")
    assert workspace.state == "active" and workspace.version == 2
    assert workspace.description == "Description"
    assert await repository.bank_exists(workspace)
    await lifecycle.delete(
        ADMIN, "sync", "delete", expected_id=workspace.workspace_id, expected_version=workspace.version
    )
    lifecycle.memory.delete_bank.assert_awaited_once()
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_sync')") is None
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.workspaces") == 0
    assert [
        row["action"]
        for row in await repository.pool.fetch("SELECT action FROM ctxdb_meta.audit_events ORDER BY event_id")
    ] == ["create_workspace", "delete_workspace"]


@pytest.mark.parametrize("stage", ["migration", "update", "verify"])
async def test_failed_creation_keeps_identity_and_residue_until_explicit_cleanup(repository, stage):
    lifecycle = lifecycle_for(repository)
    if stage == "migration":

        async def fail(schema):
            await repository.pool.execute(f'CREATE SCHEMA "{schema}"; CREATE TABLE "{schema}".partial(id int)')
            raise RuntimeError("synthetic migration failure")

        lifecycle.context.run_migration = AsyncMock(side_effect=fail)
    elif stage == "update":
        lifecycle.memory.update_bank = AsyncMock(side_effect=RuntimeError("synthetic Bank failure"))
    else:
        lifecycle.memory.get_bank_profile = AsyncMock(return_value=None)
    with pytest.raises((RuntimeError, ServiceError)):
        await lifecycle.create(ADMIN, WorkspaceCreate(name="partial"), "create")
    failed = await repository.get_workspace_by_name(ADMIN, "partial")
    assert failed.state == "failed" and failed.version == 2
    with pytest.raises(ServiceError) as conflict:
        await lifecycle.create(ADMIN, WorkspaceCreate(name="partial"), "retry")
    assert conflict.value.status == 409
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.audit_events") == 0
    await lifecycle.delete(
        ADMIN, "partial", "cleanup", expected_id=failed.workspace_id, expected_version=failed.version
    )
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_partial')") is None
    if stage != "verify":
        lifecycle.memory.delete_bank.assert_not_awaited()


async def test_native_delete_failure_never_reopens_space_and_retry_uses_current_etag(repository):
    lifecycle = lifecycle_for(repository)
    space = await lifecycle.create(ADMIN, WorkspaceCreate(name="retry"), "c")
    native_delete = lifecycle.memory.delete_bank
    lifecycle.memory.delete_bank = AsyncMock(side_effect=RuntimeError("synthetic index cleanup failure"))
    with pytest.raises(RuntimeError):
        await lifecycle.delete(
            ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
        )
    failed = await repository.get_workspace_by_name(ADMIN, space.bank_id)
    assert failed.state == "failed"
    with pytest.raises(ServiceError) as stale:
        await lifecycle.delete(
            ADMIN, space.bank_id, "stale", expected_id=space.workspace_id, expected_version=space.version
        )
    assert stale.value.status == 412
    lifecycle.memory.delete_bank = native_delete
    await lifecycle.delete(
        ADMIN, failed.bank_id, "retry", expected_id=failed.workspace_id, expected_version=failed.version
    )
    assert await repository.pool.fetchval("SELECT count(*) FROM ctxdb_meta.workspaces") == 0


async def test_schema_and_metadata_cleanup_rollback_together(repository, monkeypatch):
    lifecycle = lifecycle_for(repository)
    space = await lifecycle.create(ADMIN, WorkspaceCreate(name="rollback"), "c")
    original_audit = repository._audit

    async def failed_audit(conn, principal, request_id, action, **kwargs):
        if action == "delete_workspace":
            raise RuntimeError("synthetic final transaction failure")
        await original_audit(conn, principal, request_id, action, **kwargs)

    monkeypatch.setattr(repository, "_audit", failed_audit)
    with pytest.raises(RuntimeError):
        await lifecycle.delete(
            ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
        )
    failed = await repository.get_workspace_by_name(ADMIN, space.bank_id)
    assert failed.state == "failed"
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_rollback')") is not None
    assert not await repository.bank_exists(failed)
    monkeypatch.setattr(repository, "_audit", original_audit)
    await lifecycle.delete(
        ADMIN, space.bank_id, "retry", expected_id=failed.workspace_id, expected_version=failed.version
    )
    assert await repository.pool.fetchval("SELECT to_regnamespace('ctxdb_ws_rollback')") is None


async def test_cancellation_preserves_unknown_state_without_recovery_or_shield(repository):
    lifecycle = lifecycle_for(repository)
    entered = asyncio.Event()

    async def migrate(schema):
        entered.set()
        await asyncio.Event().wait()

    lifecycle.context.run_migration = AsyncMock(side_effect=migrate)
    task = asyncio.create_task(lifecycle.create(ADMIN, WorkspaceCreate(name="unknown"), "c"))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    space = await repository.get_workspace_by_name(ADMIN, "unknown")
    assert space.state == "creating"
    lifecycle.memory.update_bank.assert_not_awaited()
    with pytest.raises(ServiceError) as conflict:
        await lifecycle.delete(
            ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
        )
    assert conflict.value.status == 409


async def test_concurrent_delete_only_transitions_one_request(repository):
    space = await ready_workspace(repository)

    async def delete():
        return await repository.delete_workspace(
            ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
        )

    results = await asyncio.gather(delete(), delete(), return_exceptions=True)
    assert sum(not isinstance(item, Exception) for item in results) == 1
    assert any(isinstance(item, ServiceError) and item.status == 412 for item in results)


async def test_external_dependencies_are_never_dropped(repository):
    lifecycle = lifecycle_for(repository)
    space = await lifecycle.create(ADMIN, WorkspaceCreate(name="external"), "c")
    await repository.pool.execute("CREATE VIEW public.lifecycle_external AS SELECT * FROM ctxdb_ws_external.banks")
    try:
        with pytest.raises(ServiceError) as error:
            await lifecycle.delete(
                ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
            )
        assert error.value.code == "schema_dependencies"
        lifecycle.memory.delete_bank.assert_not_awaited()
        assert await repository.pool.fetchval("SELECT to_regclass('public.lifecycle_external')") is not None
    finally:
        await repository.pool.execute("DROP VIEW public.lifecycle_external")


async def test_native_awaits_do_not_hold_shared_pool_connection(repository, database_url):
    shared_pool = repository.pool
    only_connection = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    assert only_connection is not None
    repository.pool = only_connection
    try:
        lifecycle = lifecycle_for(repository)
        space = await asyncio.wait_for(lifecycle.create(ADMIN, WorkspaceCreate(name="one_connection"), "c"), 5)
        await asyncio.wait_for(
            lifecycle.delete(ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version),
            5,
        )
    finally:
        repository.pool = shared_pool
        await only_connection.close()


async def test_failure_recording_does_not_hide_original_native_failure(repository, monkeypatch):
    lifecycle = lifecycle_for(repository)
    lifecycle.context.run_migration = AsyncMock(side_effect=RuntimeError("synthetic original failure"))
    monkeypatch.setattr(repository, "fail_workspace", AsyncMock(side_effect=OSError("synthetic metadata unavailable")))
    with pytest.raises(RuntimeError, match="original failure"):
        await lifecycle.create(ADMIN, WorkspaceCreate(name="failed_write"), "c")
    space = await repository.get_workspace_by_name(ADMIN, "failed_write")
    assert space.state == "creating"


async def test_final_cleanup_rolls_back_authorizations_and_key_versions(repository, monkeypatch):
    from hindsight_ext_contextdb.models import ApiKeyCreate, UserCreate

    lifecycle = lifecycle_for(repository)
    space = await lifecycle.create(ADMIN, WorkspaceCreate(name="grants"), "c")
    user = await repository.create_user(ADMIN, UserCreate(name="Application"), "u")
    key = await repository.create_key(
        ADMIN,
        user.user_id,
        ApiKeyCreate(name="selected", authorization={"mode": "selected", "workspaces": [{"bank_id": space.bank_id}]}),
        "k",
    )
    original_audit = repository._audit

    async def audit(conn, principal, request_id, action, **kwargs):
        if action == "delete_workspace":
            raise RuntimeError("synthetic audit failure")
        await original_audit(conn, principal, request_id, action, **kwargs)

    monkeypatch.setattr(repository, "_audit", audit)
    with pytest.raises(RuntimeError):
        await lifecycle.delete(
            ADMIN, space.bank_id, "d", expected_id=space.workspace_id, expected_version=space.version
        )
    assert (
        await repository.pool.fetchval("SELECT version FROM ctxdb_meta.api_keys WHERE key_id=$1", key.metadata.key_id)
        == key.metadata.version
    )
    assert (
        await repository.pool.fetchval(
            "SELECT count(*) FROM ctxdb_meta.key_workspace_permissions WHERE workspace_id=$1", space.workspace_id
        )
        == 1
    )
    assert await repository.pool.fetchval("SELECT to_regnamespace($1)", space.schema_name) is not None
