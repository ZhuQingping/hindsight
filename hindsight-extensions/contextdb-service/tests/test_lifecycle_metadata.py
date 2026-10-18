"""Durable operation concurrency/fencing without claiming a native migration ran."""

import asyncio
import contextlib
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import asyncpg
import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import ExtensionContext
from hindsight_ext_contextdb.lifecycle import Lifecycle
from hindsight_ext_contextdb.models import ServiceError, WorkspaceCreate
from hindsight_ext_contextdb.repository import Repository

from .test_repository import ADMIN, admin_actor, key_input, ready_workspace, space_user


async def test_only_one_executor_claims_operation(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Create"), "create-once", "request")
    results = await asyncio.gather(repository.claim_operation(), repository.claim_operation())
    claimed = [item for item in results if item is not None]
    assert len(claimed) == 1
    assert claimed[0].operation_id == created.operation_id
    assert claimed[0].attempts == 1
    assert await repository.renew_operation(claimed[0])
    await repository.complete_operation(claimed[0])
    assert (await repository.get_workspace(ADMIN, created.workspace_id)).state == "active"
    with pytest.raises(ServiceError) as error:
        await repository.complete_operation(claimed[0])
    assert error.value.code == "lease_lost"


async def test_failed_operation_is_not_activated_and_creator_can_inspect(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Failure"), "create-failure", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None
    await repository.complete_operation(claimed, error_code="synthetic_failure")
    assert (await repository.get_workspace(ADMIN, created.workspace_id)).state == "failed"
    assert (await repository.get_operation(ADMIN, created.operation_id)).error_code == "synthetic_failure"
    assert await repository.worker_workspaces() == []


async def test_failed_create_can_restart_without_creating_a_second_space(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Retry"), "retry-create", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None
    await repository.complete_operation(claimed, error_code="synthetic_failure")
    restarted = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Retry"), "retry-create", "request")
    assert restarted.operation_id == created.operation_id
    assert restarted.workspace_id == created.workspace_id
    assert restarted.state == "pending"
    assert (await repository.list_workspaces(ADMIN, 100, 0)).total == 1


async def test_failure_backoff_preserves_create_state_until_retries_exhaust(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Backoff"), "backoff", "request")
    for attempt in range(1, 4):
        claimed = await repository.claim_operation()
        assert claimed is not None and claimed.attempts == attempt
        await repository.fail_operation(claimed)
        state = await repository.get_operation(ADMIN, created.operation_id)
        assert state.state == ("pending" if attempt < 3 else "failed")
        if attempt < 3:
            assert await repository.claim_operation() is None
            # Advance only the metadata retry deadline; waiting is not the
            # property under test and no public control API can force this state.
            await repository.pool.execute(
                "UPDATE ctxdb_meta.management_operations SET lease_until=now()-interval '1 second' WHERE operation_id=$1",
                created.operation_id,
            )
    assert (await repository.get_workspace(ADMIN, created.workspace_id)).state == "failed"


async def test_delete_is_durable_and_same_request_replays_after_completion(repository: Repository) -> None:
    workspace = await ready_workspace(repository)
    deleted = await repository.delete_workspace(
        ADMIN,
        workspace.bank_id,
        "delete-once",
        "request",
        expected_id=workspace.workspace_id,
        expected_version=workspace.version,
    )
    assert (await repository.get_workspace(ADMIN, workspace.workspace_id)).state == "deleting"
    assert [item.workspace_id for item in await repository.worker_workspaces()] == [workspace.workspace_id]
    claimed = await repository.claim_operation()
    assert claimed is not None
    assert claimed.operation_id == deleted.operation_id
    await repository.complete_operation(claimed)
    assert await repository.worker_workspaces() == []
    assert (
        await repository.delete_workspace(
            ADMIN,
            workspace.bank_id,
            "delete-once",
            "request",
            expected_id=workspace.workspace_id,
            expected_version=workspace.version,
        )
    ).operation_id == deleted.operation_id
    assert (await repository.get_operation(ADMIN, deleted.operation_id)).state == "succeeded"


async def test_concurrent_delete_replays_the_same_operation(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = await ready_workspace(repository)
    original = asyncpg.Connection.fetchrow
    both_ready = asyncio.Event()
    arrivals = 0

    async def gated_fetchrow(
        self: asyncpg.Connection, query: str, *args: object, **kwargs: Any
    ) -> asyncpg.Record | None:
        nonlocal arrivals
        if "ctxdb_meta.workspaces" in query and "FOR UPDATE" in query:
            # Pause immediately before the shared row lock. This exposes the
            # former lookup-before-lock race without relying on scheduling sleeps.
            arrivals += 1
            if arrivals == 2:
                both_ready.set()
            await asyncio.wait_for(both_ready.wait(), timeout=5)
        return await original(self, query, *args, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "fetchrow", gated_fetchrow)
    first, second = await asyncio.gather(
        repository.delete_workspace(
            ADMIN,
            workspace.bank_id,
            "concurrent-delete",
            "first",
            expected_id=workspace.workspace_id,
            expected_version=workspace.version,
        ),
        repository.delete_workspace(
            ADMIN,
            workspace.bank_id,
            "concurrent-delete",
            "second",
            expected_id=workspace.workspace_id,
            expected_version=workspace.version,
        ),
    )
    assert first.operation_id == second.operation_id
    assert first.state == second.state == "pending"


async def test_old_failed_create_cannot_restart_after_failed_delete(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="old_create"), "old-create", "request")
    create_claim = await repository.claim_operation()
    assert create_claim is not None
    await repository.complete_operation(create_claim, error_code="synthetic_create_failure")
    deleted = await repository.delete_workspace(
        ADMIN,
        (await repository.get_workspace(ADMIN, created.workspace_id)).bank_id,
        "current-delete",
        "request",
        expected_id=created.workspace_id,
        expected_version=(await repository.get_workspace(ADMIN, created.workspace_id)).version,
    )
    delete_claim = await repository.claim_operation()
    assert delete_claim is not None and delete_claim.operation_id == deleted.operation_id
    await repository.complete_operation(delete_claim, error_code="synthetic_delete_failure")

    with pytest.raises(ServiceError) as error:
        await repository.create_workspace(ADMIN, WorkspaceCreate(name="old_create"), "old-create", "request")
    assert error.value.code == "superseded_operation"
    assert (await repository.get_workspace(ADMIN, created.workspace_id)).state == "failed"
    assert (await repository.get_operation(ADMIN, created.operation_id)).state == "failed"
    current = await repository.delete_workspace(
        ADMIN,
        (await repository.get_workspace(ADMIN, created.workspace_id)).bank_id,
        "current-delete",
        "request",
        expected_id=created.workspace_id,
        expected_version=(await repository.get_workspace(ADMIN, created.workspace_id)).version,
    )
    assert current.operation_id == deleted.operation_id and current.state == "pending"
    assert (await repository.get_workspace(ADMIN, created.workspace_id)).state == "deleting"
    # A legitimate retry advances its own generation; a second failure must
    # still be restartable without making the superseded create current again.
    retry_claim = await repository.claim_operation()
    assert retry_claim is not None and retry_claim.operation_id == deleted.operation_id
    await repository.complete_operation(retry_claim, error_code="synthetic_second_delete_failure")
    repeated = await repository.delete_workspace(
        ADMIN,
        (await repository.get_workspace(ADMIN, created.workspace_id)).bank_id,
        "current-delete",
        "request",
        expected_id=created.workspace_id,
        expected_version=(await repository.get_workspace(ADMIN, created.workspace_id)).version,
    )
    assert repeated.operation_id == deleted.operation_id and repeated.state == "pending"


async def test_operation_foreign_key_binds_registered_workspace(repository: Repository) -> None:
    # Dedicated metadata no longer repeats deployment identifiers. The real
    # workspace reference must still reject an orphan operation independently.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await repository.pool.execute(
            "INSERT INTO ctxdb_meta.management_operations "
            "(operation_id,workspace_id,action,target_id,idempotency_key,request_hash) "
            "VALUES ($1,$2,'delete_workspace',$3,'wrong-owner',repeat('c',64))",
            "a" * 32,
            "b" * 32,
            "b" * 32,
        )


async def test_key_foreign_key_binds_registered_user(repository: Repository) -> None:
    workspace = await ready_workspace(repository)
    user = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(await admin_actor(repository), user.user_id, key_input(workspace.bank_id), "key")
    # Key ownership is retained even after redundant per-row instance columns
    # are removed; forged metadata cannot point at an unknown member.
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await repository.pool.execute(
            "UPDATE ctxdb_meta.api_keys SET user_id=$2 WHERE key_id=$1", key.metadata.key_id, "f" * 32
        )


async def test_operation_ownership_checks_scope_state_and_live_lease(repository: Repository) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Owner"), "owner", "request")
    assert not await repository.operation_is_owned(
        created.operation_id, "unclaimed", "create_workspace", created.workspace_id
    )
    claimed = await repository.claim_operation()
    assert claimed is not None and claimed.lease_token is not None
    assert await repository.operation_is_owned(
        claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id
    )
    for operation_id, token, action, workspace_id in (
        ("other-operation", claimed.lease_token, claimed.action, claimed.workspace_id),
        (claimed.operation_id, "other-token", claimed.action, claimed.workspace_id),
        (claimed.operation_id, claimed.lease_token, "delete_workspace", claimed.workspace_id),
        (claimed.operation_id, claimed.lease_token, claimed.action, "other-workspace"),
        (claimed.operation_id, "", claimed.action, claimed.workspace_id),
    ):
        assert not await repository.operation_is_owned(operation_id, token, action, workspace_id)
    foreign_instance = Repository(repository.pool, "other-instance", repository.cloud_tenant_id, repository.pepper)
    assert not await foreign_instance.operation_is_owned(
        claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id
    )
    await repository.complete_operation(claimed)
    assert not await repository.operation_is_owned(
        claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id
    )


async def test_expired_owner_and_replaced_owner_cannot_authorize(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Lease"), "lease", "request")
    old = await repository.claim_operation()
    assert old is not None and old.lease_token is not None
    # Only metadata injection can force expiry without a wall-clock wait; this
    # fixture owns the database, and no public control API can change leases.
    await repository.pool.execute(
        "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()-interval '1 second' "
        "WHERE operation_id=$1",
        old.operation_id,
    )
    assert not await repository.operation_is_owned(old.operation_id, old.lease_token, old.action, old.workspace_id)
    new = await repository.claim_operation()
    assert new is not None and new.lease_token is not None and new.lease_token != old.lease_token
    assert not await repository.operation_is_owned(old.operation_id, old.lease_token, old.action, old.workspace_id)
    assert await repository.operation_is_owned(new.operation_id, new.lease_token, new.action, new.workspace_id)


async def test_short_operation_fence_blocks_owner_replacement(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Fence"), "fence", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None and claimed.lease_token is not None
    async with repository.pool.acquire() as owner, owner.transaction():
        assert await repository.operation_is_owned(
            claimed.operation_id,
            claimed.lease_token,
            claimed.action,
            claimed.workspace_id,
            connection=owner,
            lock=True,
        )
        async with repository.pool.acquire() as rival:
            with pytest.raises(asyncpg.LockNotAvailableError):
                async with rival.transaction():
                    # Deliberate bounded lock wait proves the actual PG fence,
                    # not merely the query text or a process-local mock lock.
                    await rival.execute("SET LOCAL lock_timeout='100ms'")
                    await rival.execute(
                        "UPDATE ctxdb_meta.management_operations SET lease_token='replacement' WHERE operation_id=$1",
                        claimed.operation_id,
                    )
    await repository.pool.execute(
        "UPDATE ctxdb_meta.management_operations SET lease_token='replacement' WHERE operation_id=$1",
        claimed.operation_id,
    )
    assert not await repository.operation_is_owned(
        claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id
    )
    with pytest.raises(ValueError, match="open transaction"):
        await repository.operation_is_owned(
            claimed.operation_id, claimed.lease_token, claimed.action, claimed.workspace_id, lock=True
        )


async def test_stale_executor_does_not_start_migration(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="stale_executor"), "stale-executor", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None
    await repository.pool.execute(
        "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()-interval '1 second' "
        "WHERE operation_id=$1",
        claimed.operation_id,
    )
    replacement = await repository.claim_operation()
    assert replacement is not None and replacement.lease_token != claimed.lease_token
    context = Mock(spec=ExtensionContext)
    context.run_migration = AsyncMock()
    memory = Mock(spec=MemoryEngine)
    memory.update_bank = AsyncMock()
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    with pytest.raises(ServiceError) as error:
        await lifecycle._apply(claimed)
    assert error.value.code == "lease_lost"
    context.run_migration.assert_not_called()
    memory.update_bank.assert_not_called()


async def test_cancelled_migration_is_awaited_before_executor_exits(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Cancellation"), "cancel-migration", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None
    entered, release, exited = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def migration(schema: str) -> None:
        entered.set()
        try:
            await release.wait()
        finally:
            exited.set()

    context = Mock(spec=ExtensionContext)
    context.run_migration = AsyncMock(side_effect=migration)
    memory = Mock(spec=MemoryEngine)
    memory.update_bank = AsyncMock()
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    executor = asyncio.create_task(lifecycle._apply(claimed))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        executor.cancel()
        # Give cancellation its scheduling turn, not a time-based DDL estimate.
        await asyncio.sleep(0)
        assert not exited.is_set()
        assert not executor.done()
        executor.cancel()  # A second shutdown must not outlive the migration thread.
        await asyncio.sleep(0)
        assert not exited.is_set()
        assert not executor.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(executor, 5)
        assert exited.is_set()
        memory.update_bank.assert_not_called()
    finally:
        release.set()
        executor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await executor


async def test_owner_replaced_during_migration_cannot_create_bank(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Replaced"), "replaced-migration", "request")
    claimed = await repository.claim_operation()
    assert claimed is not None
    entered, release = asyncio.Event(), asyncio.Event()

    async def migration(schema: str) -> None:
        entered.set()
        await release.wait()

    context = Mock(spec=ExtensionContext)
    context.run_migration = AsyncMock(side_effect=migration)
    memory = Mock(spec=MemoryEngine)
    memory.update_bank = AsyncMock()
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    executor = asyncio.create_task(lifecycle._apply(claimed))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        await repository.pool.execute(
            "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()-interval '1 second' "
            "WHERE operation_id=$1",
            claimed.operation_id,
        )
        replacement = await repository.claim_operation()
        assert replacement is not None and replacement.lease_token != claimed.lease_token
        release.set()
        with pytest.raises(ServiceError) as error:
            await asyncio.wait_for(executor, 5)
        assert error.value.code == "lease_lost"
        memory.update_bank.assert_not_called()
        assert (await repository.get_operation(ADMIN, claimed.operation_id)).state == "running"
    finally:
        release.set()
        executor.cancel()
        with contextlib.suppress(asyncio.CancelledError, ServiceError):
            await executor


@pytest.mark.parametrize("partial_banks_table", [False, True])
async def test_delete_failed_provisioning_reclaims_partial_schema_without_bank(
    repository: Repository, partial_banks_table: bool
) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Incomplete"), "incomplete", "request")
    create_claim = await repository.claim_operation()
    assert create_claim is not None
    await repository.complete_operation(create_claim, error_code="synthetic_migration_failure")
    workspace = await repository.get_workspace(ADMIN, created.workspace_id)
    if partial_banks_table:
        # A migration can commit an empty banks table before failing later.
        # Only this fixture's server-generated schema is touched; the complete
        # deletion contract now reclaims this partial schema as well.
        await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
        await repository.pool.execute(f'CREATE TABLE "{workspace.schema_name}".banks (bank_id text PRIMARY KEY)')
    deleted = await repository.delete_workspace(
        ADMIN,
        (await repository.get_workspace(ADMIN, created.workspace_id)).bank_id,
        "delete-incomplete",
        "request",
        expected_id=created.workspace_id,
        expected_version=(await repository.get_workspace(ADMIN, created.workspace_id)).version,
    )
    delete_claim = await repository.claim_operation()
    assert delete_claim is not None and delete_claim.operation_id == deleted.operation_id
    memory = Mock(spec=MemoryEngine)
    memory.get_bank_profile = AsyncMock(return_value=None)
    memory.delete_bank = AsyncMock()
    memory._file_storage = Mock()
    memory._file_storage.delete_prefix = AsyncMock(return_value=0)
    context = Mock(spec=ExtensionContext)
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    await asyncio.wait_for(lifecycle.execute(delete_claim), 5)
    assert (await repository.get_operation(ADMIN, deleted.operation_id)).state == "succeeded"
    assert await repository.bank_table_exists(workspace.schema_name) is False
    memory.delete_bank.assert_not_called()
    if partial_banks_table:
        request_context = memory.get_bank_profile.call_args.kwargs["request_context"]
        assert request_context.extra_headers["ctxdb-operation-id"] == delete_claim.operation_id
        assert request_context.extra_headers["ctxdb-lease-token"] == delete_claim.lease_token
        assert request_context.extra_headers["ctxdb-internal-purpose"] == "delete_workspace"
    else:
        memory.get_bank_profile.assert_not_called()
