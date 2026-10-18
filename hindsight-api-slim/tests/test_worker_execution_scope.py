"""Worker resource reservations include final writes and reject before touching SQL."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from hindsight_api.extensions.builtin.tenant import DefaultTenantExtension
from hindsight_api.worker.exceptions import DeferOperation, RetryTaskAt
from hindsight_api.worker.poller import ClaimedTask, WorkerPoller


class RecordingTenant(DefaultTenantExtension):
    def __init__(self, *, reject: bool = False) -> None:
        super().__init__({})
        self.active = False
        self.failed = False
        self.reject = reject
        self.calls: list[tuple[str | None, str, str | None]] = []

    @asynccontextmanager
    async def async_execution_scope(
        self, schema: str | None, bank_id: str, tenant_id: str | None
    ) -> AsyncIterator[None]:
        self.calls.append((schema, bank_id, tenant_id))
        if self.reject:
            raise ValueError("private-extension-diagnostic")
        self.active = True
        try:
            yield
        except BaseException:
            self.failed = True
            raise
        finally:
            self.active = False


def make_task() -> ClaimedTask:
    return ClaimedTask(
        operation_id=str(uuid.uuid4()),
        task_dict={
            "type": "graph_maintenance",
            "operation_type": "graph_maintenance",
            "bank_id": "jiamu",
            "_tenant_id": "a" * 32,
        },
        schema="ctxdb_ws_jiamu",
    )


def make_poller(executor: AsyncMock, tenant: DefaultTenantExtension | None = None) -> WorkerPoller:
    poller = WorkerPoller(backend=MagicMock(), worker_id="execution-test", executor=executor, tenant_extension=tenant)
    poller._mark_completed = AsyncMock()
    poller._mark_failed = AsyncMock()
    poller._schedule_retry = AsyncMock()
    poller._defer_operation = AsyncMock()
    return poller


async def run_background(poller: WorkerPoller, task: ClaimedTask) -> None:
    await poller.execute_task(task)
    background = poller._active_tasks[task.operation_id].bg_task
    await background
    async with asyncio.timeout(5):
        while poller._in_flight_count:
            await asyncio.sleep(0)


async def test_default_extension_execution_scope_is_noop_for_existing_workers() -> None:
    executor = AsyncMock()
    poller = make_poller(executor)
    task = make_task()
    await run_background(poller, task)
    executor.assert_awaited_once_with(task.task_dict)
    poller._mark_completed.assert_awaited_once_with(task.operation_id, task.schema)
    assert poller._active_tasks == {}


@pytest.mark.parametrize("outcome", ["completed", "retry", "deferred", "failed"])
async def test_scope_encloses_executor_and_final_status_writes(outcome: str) -> None:
    tenant = RecordingTenant()

    async def execute(_: object) -> None:
        assert tenant.active
        if outcome == "retry":
            raise RetryTaskAt(datetime.now(timezone.utc))
        if outcome == "deferred":
            raise DeferOperation(datetime.now(timezone.utc))
        if outcome == "failed":
            raise RuntimeError("synthetic executor failed")

    poller = make_poller(AsyncMock(side_effect=execute), tenant)

    async def write(*_: object) -> None:
        assert tenant.active

    for name in ["_mark_completed", "_mark_failed", "_schedule_retry", "_defer_operation"]:
        setattr(poller, name, AsyncMock(side_effect=write))
    await run_background(poller, make_task())
    assert tenant.calls == [("ctxdb_ws_jiamu", "jiamu", "a" * 32)]
    assert tenant.active is False
    assert tenant.failed is (outcome == "failed")
    expected = {
        "completed": poller._mark_completed,
        "retry": poller._schedule_retry,
        "deferred": poller._defer_operation,
        "failed": poller._mark_failed,
    }[outcome]
    expected.assert_awaited_once()


async def test_scope_entry_rejection_never_executes_or_writes_in_reused_schema(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant = RecordingTenant(reject=True)
    executor = AsyncMock()
    poller = make_poller(executor, tenant)
    await run_background(poller, make_task())
    executor.assert_not_awaited()
    poller._mark_completed.assert_not_awaited()
    poller._mark_failed.assert_not_awaited()
    poller._schedule_retry.assert_not_awaited()
    assert "private-extension-diagnostic" not in caplog.text
    assert "resource admission failed" in caplog.text


async def test_cancelled_execution_keeps_failure_signal_until_scope_exit() -> None:
    tenant = RecordingTenant()
    entered = asyncio.Event()

    async def execute(_: object) -> None:
        entered.set()
        await asyncio.Event().wait()

    poller = make_poller(AsyncMock(side_effect=execute), tenant)
    task = make_task()
    await poller.execute_task(task)
    background = poller._active_tasks[task.operation_id].bg_task
    await entered.wait()
    background.cancel()
    with pytest.raises(asyncio.CancelledError):
        await background
    assert tenant.failed and not tenant.active
    poller._mark_completed.assert_not_awaited()
    poller._mark_failed.assert_not_awaited()


async def test_terminal_write_unknown_result_retains_resource_guard() -> None:
    tenant = RecordingTenant()
    poller = make_poller(AsyncMock(), tenant)
    poller._write_terminal = AsyncMock(return_value=False)
    await run_background(poller, make_task())
    assert tenant.failed and not tenant.active
