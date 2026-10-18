"""A cancelled task row cannot release the generation while its worker still writes."""

from __future__ import annotations

import asyncio
import uuid
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import ExtensionContext
from hindsight_api.worker.poller import ClaimedTask, WorkerPoller
from hindsight_ext_contextdb.lifecycle import Lifecycle
from hindsight_ext_contextdb.models import ServiceError, WorkspaceCreate
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension

from .test_extensions import configured as configured
from .test_repository import ADMIN, ready_workspace


async def settle(poller: WorkerPoller) -> None:
    async with asyncio.timeout(5):
        while poller._in_flight_count:
            await asyncio.sleep(0)


async def test_cancelled_running_worker_blocks_drop_and_name_reuse_through_final_write(repository, configured) -> None:
    old = await ready_workspace(repository, "jiamu")
    schema = old.schema_name
    operation_id = str(uuid.uuid4())
    await repository.pool.execute(
        f'CREATE SCHEMA "{schema}"; CREATE TABLE "{schema}".banks(bank_id text); CREATE TABLE "{schema}".probe(value text); CREATE TABLE "{schema}".async_operations(operation_id text PRIMARY KEY,bank_id text,status text)'
    )
    await repository.pool.execute(
        f"INSERT INTO \"{schema}\".async_operations VALUES($1,$2,'processing')", operation_id, old.bank_id
    )
    tenant = ContextDBTenantExtension({})
    tenant.metadata_pool = repository.pool
    entered, release = asyncio.Event(), asyncio.Event()

    async def old_writer(_: object) -> None:
        entered.set()
        await release.wait()
        await repository.pool.execute(f"INSERT INTO \"{schema}\".probe VALUES('old-worker')")

    poller = WorkerPoller(
        backend=MagicMock(),
        worker_id="held-writer",
        executor=AsyncMock(side_effect=old_writer),
        tenant_extension=tenant,
    )

    async def complete(_: str, __: str | None) -> None:
        assert await repository.has_outstanding_admissions(old.workspace_id)
        await repository.pool.execute(
            f"UPDATE \"{schema}\".async_operations SET status='completed' WHERE operation_id=$1 AND status<>'cancelled'",
            operation_id,
        )

    poller._mark_completed = AsyncMock(side_effect=complete)
    task = ClaimedTask(
        operation_id=operation_id,
        task_dict={"type": "graph_maintenance", "bank_id": old.bank_id, "_tenant_id": old.workspace_id},
        schema=schema,
    )
    memory = Mock(spec=MemoryEngine)
    memory.get_bank_profile = AsyncMock(return_value={"bank_id": old.bank_id})

    async def operations(*_: object, **__: object) -> dict[str, int]:
        return {
            "total": await repository.pool.fetchval(
                f"SELECT count(*) FROM \"{schema}\".async_operations WHERE status IN ('pending','processing')"
            )
        }

    memory.list_operations = AsyncMock(side_effect=operations)
    memory.delete_bank = AsyncMock()
    memory._file_storage = Mock()
    memory._file_storage.delete_prefix = AsyncMock()
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, Mock()))
    await poller.execute_task(task)
    background = poller._active_tasks[operation_id].bg_task
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert await repository.has_outstanding_admissions(old.workspace_id)
        # The real cancellation endpoint makes this same terminal transition;
        # cancellation is cooperative and does not terminate the running writer.
        await repository.pool.execute(
            f"UPDATE \"{schema}\".async_operations SET status='cancelled' WHERE operation_id=$1", operation_id
        )
        await repository.delete_workspace(
            ADMIN, old.bank_id, "delete", "r", expected_id=old.workspace_id, expected_version=old.version
        )
        deletion = await repository.claim_operation()
        assert deletion is not None
        assert await lifecycle._apply(deletion) is False
        assert await repository.pool.fetchval("SELECT to_regnamespace($1)", schema)
        with pytest.raises(ServiceError) as conflict:
            await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "premature", "r")
        assert conflict.value.status == 409
        release.set()
        await asyncio.wait_for(background, 5)
        await settle(poller)
        assert not await repository.has_outstanding_admissions(old.workspace_id)
        assert await repository.pool.fetchval(f'SELECT value FROM "{schema}".probe') == "old-worker"
        assert await lifecycle._apply(deletion) is True
        await repository.complete_operation(deletion)
        new = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "fresh-generation", "r")
        creation = await repository.claim_operation()
        assert creation is not None
        await repository.complete_operation(creation)
        await repository.pool.execute(f'CREATE SCHEMA "{schema}"; CREATE TABLE "{schema}".probe(value text)')
        assert new.workspace_id != old.workspace_id
        assert await repository.pool.fetchval(f'SELECT count(*) FROM "{schema}".probe') == 0
    finally:
        release.set()
        if not background.done():
            background.cancel()
        await asyncio.gather(background, return_exceptions=True)
        tenant.metadata_pool = None


@pytest.mark.parametrize("missing_generation", [False, True])
async def test_delayed_claim_cannot_enter_successor_or_write_final_status(
    repository, configured, missing_generation: bool
) -> None:
    old = await ready_workspace(repository, "jiamu")
    await repository.delete_workspace(
        ADMIN, old.bank_id, "delete", "r", expected_id=old.workspace_id, expected_version=old.version
    )
    deletion = await repository.claim_operation()
    assert deletion is not None
    await repository.complete_operation(deletion)
    new = await repository.create_workspace(ADMIN, WorkspaceCreate(name="jiamu"), "new", "r")
    creation = await repository.claim_operation()
    assert creation is not None
    await repository.complete_operation(creation)
    tenant = ContextDBTenantExtension({})
    tenant.metadata_pool = repository.pool
    executor = AsyncMock()
    poller = WorkerPoller(backend=MagicMock(), worker_id="delayed", executor=executor, tenant_extension=tenant)
    poller._mark_completed = AsyncMock()
    poller._mark_failed = AsyncMock()
    task = ClaimedTask(
        operation_id=str(uuid.uuid4()),
        task_dict={
            "type": "graph_maintenance",
            "bank_id": "jiamu",
            "_tenant_id": None if missing_generation else old.workspace_id,
        },
        schema=old.schema_name,
    )
    try:
        await poller.execute_task(task)
        await poller._active_tasks[task.operation_id].bg_task
        await settle(poller)
        executor.assert_not_awaited()
        poller._mark_completed.assert_not_awaited()
        poller._mark_failed.assert_not_awaited()
        assert not await repository.has_outstanding_admissions(new.workspace_id)
    finally:
        tenant.metadata_pool = None


async def test_worker_failure_retains_unknown_writer_barrier(repository, configured) -> None:
    space = await ready_workspace(repository)
    tenant = ContextDBTenantExtension({})
    tenant.metadata_pool = repository.pool
    poller = WorkerPoller(
        backend=MagicMock(),
        worker_id="failed",
        executor=AsyncMock(side_effect=RuntimeError("synthetic")),
        tenant_extension=tenant,
    )
    poller._mark_failed = AsyncMock()
    task = ClaimedTask(
        operation_id=str(uuid.uuid4()),
        task_dict={"type": "graph_maintenance", "bank_id": space.bank_id, "_tenant_id": space.workspace_id},
        schema=space.schema_name,
    )
    try:
        await poller.execute_task(task)
        await poller._active_tasks[task.operation_id].bg_task
        await settle(poller)
        assert await repository.has_outstanding_admissions(space.workspace_id)
        assert (
            await repository.pool.fetchval(
                "SELECT state FROM ctxdb_meta.request_admissions WHERE workspace_id=$1", space.workspace_id
            )
            == "interrupted"
        )
    finally:
        tenant.metadata_pool = None
