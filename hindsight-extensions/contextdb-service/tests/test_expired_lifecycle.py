"""An expired lease is not revived merely because no other replica claimed it."""

import asyncio

import pytest
from hindsight_ext_contextdb.models import ServiceError, WorkspaceCreate
from hindsight_ext_contextdb.repository import Repository

from .test_repository import ADMIN


async def test_expired_unclaimed_owner_cannot_renew_complete_or_fail(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Expired owner"), "expired-owner", "r")
    operation = await repository.claim_operation()
    assert operation is not None
    await repository.pool.execute(
        "UPDATE ctxdb_meta.management_operations SET lease_until=now()-interval '1 second' WHERE operation_id=$1",
        operation.operation_id,
    )
    assert not await repository.renew_operation(operation)
    for finish in (repository.complete_operation, repository.fail_operation):
        with pytest.raises(ServiceError) as error:
            await finish(operation)
        assert error.value.code == "lease_lost"
    await repository.defer_operation(operation)
    # A stale defer cannot extend the deadline and hide this operation from a
    # healthy replica's recovery sweep.
    replacement = await repository.claim_operation()
    assert replacement is not None
    assert replacement.operation_id == operation.operation_id
    assert replacement.lease_token != operation.lease_token


@pytest.mark.parametrize("method", ["renew_operation", "complete_operation", "fail_operation", "defer_operation"])
async def test_owner_expiring_during_row_lock_wait_cannot_change_operation(repository: Repository, method: str) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Waiting owner"), "waiting-owner", "r")
    operation = await repository.claim_operation()
    assert operation is not None
    task: asyncio.Task | None = None
    try:
        async with repository.pool.acquire() as blocker, blocker.transaction():
            # Start valid, then hold a real conflicting lock until expiry. This
            # catches PG evaluating UPDATE's predicate before its lock wait.
            await blocker.execute(
                "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '200 milliseconds' "
                "WHERE operation_id=$1",
                operation.operation_id,
            )
            # Commit the new deadline before the blocker takes SHARE, so the
            # waiting statement sees a committed and still-valid owner row.
        async with repository.pool.acquire() as blocker, blocker.transaction():
            assert await blocker.fetchval(
                "SELECT lease_until>clock_timestamp() FROM ctxdb_meta.management_operations "
                "WHERE operation_id=$1 FOR SHARE",
                operation.operation_id,
            )
            task = asyncio.create_task(getattr(repository, method)(operation))
            deadline = asyncio.get_running_loop().time() + 5
            while not await repository.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                "AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.management_operations%')"
            ):
                assert asyncio.get_running_loop().time() < deadline
                assert not task.done(), "Operation did not reach the intended row-lock wait"
                await asyncio.sleep(0.005)
            # The delay is the lease interval under test, not a guess that the
            # waiter started: pg_stat_activity above proves the actual wait.
            await asyncio.sleep(0.25)
            assert await blocker.fetchval(
                "SELECT lease_until<=clock_timestamp() FROM ctxdb_meta.management_operations WHERE operation_id=$1",
                operation.operation_id,
            )
        if method == "renew_operation":
            assert await asyncio.wait_for(task, 5) is False
        elif method == "defer_operation":
            assert await asyncio.wait_for(task, 5) is None
        else:
            with pytest.raises(ServiceError) as error:
                await asyncio.wait_for(task, 5)
            assert error.value.code == "lease_lost"
        row = await repository.pool.fetchrow(
            "SELECT state,lease_token,lease_until<=clock_timestamp() AS expired "
            "FROM ctxdb_meta.management_operations WHERE operation_id=$1",
            operation.operation_id,
        )
        assert row is not None and row["state"] == "running" and row["expired"]
        assert row["lease_token"] == operation.lease_token
        assert (await repository.get_workspace(ADMIN, operation.workspace_id)).state == "creating"
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_locking_ownership_rechecks_expiry_after_its_wait(repository: Repository) -> None:
    await repository.create_workspace(ADMIN, WorkspaceCreate(name="Waiting read"), "waiting-read", "r")
    operation = await repository.claim_operation()
    assert operation is not None and operation.lease_token is not None
    await repository.pool.execute(
        "UPDATE ctxdb_meta.management_operations SET lease_until=clock_timestamp()+interval '200 milliseconds' "
        "WHERE operation_id=$1",
        operation.operation_id,
    )

    async def locking_read() -> bool:
        async with repository.pool.acquire() as reader, reader.transaction():
            return await repository.operation_is_owned(
                operation.operation_id,
                operation.lease_token,
                operation.action,
                operation.workspace_id,
                connection=reader,
                lock=True,
            )

    task: asyncio.Task[bool] | None = None
    try:
        async with repository.pool.acquire() as blocker, blocker.transaction():
            assert await blocker.fetchval(
                "SELECT lease_until>clock_timestamp() FROM ctxdb_meta.management_operations "
                "WHERE operation_id=$1 FOR UPDATE",
                operation.operation_id,
            )
            task = asyncio.create_task(locking_read())
            deadline = asyncio.get_running_loop().time() + 5
            while not await repository.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                "AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.management_operations%')"
            ):
                assert asyncio.get_running_loop().time() < deadline
                assert not task.done()
                await asyncio.sleep(0.005)
            await asyncio.sleep(0.25)
            assert await blocker.fetchval(
                "SELECT lease_until<=clock_timestamp() FROM ctxdb_meta.management_operations WHERE operation_id=$1",
                operation.operation_id,
            )
        assert await asyncio.wait_for(task, 5) is False
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
