"""A lost session or unknown executor is not proof that destructive cleanup is safe."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import ExtensionContext
from hindsight_ext_contextdb.admission import durable_admission
from hindsight_ext_contextdb.lifecycle import Lifecycle
from hindsight_ext_contextdb.repository import Repository

from .test_repository import ADMIN, ready_workspace


async def test_durable_barrier_commits_before_work_and_clears_only_on_normal_exit(repository: Repository) -> None:
    workspace = await ready_workspace(repository)
    assert not await repository.has_outstanding_admissions(workspace.workspace_id)
    async with durable_admission(
        repository, workspace.workspace_id, workspace.schema_name, "http", "replica-one"
    ) as ticket:
        # This separate pool query sees a committed record, not an uncommitted
        # insertion tied to the session lock that could disappear on disconnect.
        assert await repository.has_outstanding_admissions(workspace.workspace_id)
        ticket.work_started = True
    assert not await repository.has_outstanding_admissions(workspace.workspace_id)


@pytest.mark.parametrize("started", [False, True])
async def test_only_interrupted_started_work_leaves_a_cleanup_barrier(repository: Repository, started: bool) -> None:
    workspace = await ready_workspace(repository)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        async with durable_admission(
            repository, workspace.workspace_id, workspace.schema_name, "queue", "replica-one"
        ) as ticket:
            ticket.work_started = started
            raise RuntimeError("synthetic interruption")
    assert await repository.has_outstanding_admissions(workspace.workspace_id) is started
    if started:
        assert (
            await repository.pool.fetchval(
                "SELECT state FROM ctxdb_meta.request_admissions WHERE workspace_id=$1", workspace.workspace_id
            )
            == "interrupted"
        )


async def test_crashed_or_wrong_owner_cannot_expire_away_the_purge_barrier(repository: Repository) -> None:
    workspace = await ready_workspace(repository)
    await repository.register_admission(
        "crashed-admission", "unknown-old-executor", workspace.workspace_id, workspace.schema_name, "http"
    )
    await repository.finish_admission("crashed-admission", "different-executor", interrupted=False)
    await repository.pool.execute(
        "UPDATE ctxdb_meta.request_admissions SET created_at=now()-interval '30 days' WHERE admission_id='crashed-admission'"
    )
    assert await repository.has_outstanding_admissions(workspace.workspace_id)
    deleting = await repository.delete_workspace(ADMIN, workspace.workspace_id, "durable-delete", "r")
    operation = await repository.claim_operation()
    assert operation is not None and operation.operation_id == deleting.operation_id
    memory = Mock(spec=MemoryEngine)
    context = Mock(spec=ExtensionContext)
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
    assert await lifecycle._apply(operation) is False
    memory.get_bank_profile.assert_not_called()
    memory.delete_bank.assert_not_called()
    assert (await repository.get_workspace(ADMIN, workspace.workspace_id)).state == "deleting"
    assert (await repository.get_operation(ADMIN, operation.operation_id)).state == "running"
    assert await repository.has_outstanding_admissions(workspace.workspace_id)


async def test_delete_checks_registered_continuation_after_parent_queue_snapshot(repository: Repository) -> None:
    workspace = await ready_workspace(repository)
    # Tiny native-table stand-in only enables the lifecycle's Bank-present
    # branch; metadata/protocol assertions below do not claim core DDL ran.
    await repository.pool.execute(f'CREATE SCHEMA "{workspace.schema_name}"')
    await repository.pool.execute(f'CREATE TABLE "{workspace.schema_name}".banks (bank_id text PRIMARY KEY)')
    await repository.delete_workspace(ADMIN, workspace.workspace_id, "continuation-delete", "r")
    operation = await repository.claim_operation()
    assert operation is not None
    memory = Mock(spec=MemoryEngine)
    memory.get_bank_profile = AsyncMock(return_value={"bank_id": workspace.workspace_id})
    memory.delete_bank = AsyncMock()

    async def snapshot(*args, **kwargs) -> dict[str, int]:
        # The parent has finished by the native snapshot, but its continuation
        # already committed admission before its child queue INSERT. Ordering
        # admissions before this snapshot would miss exactly this interleaving.
        await repository.register_admission(
            "registered-continuation", "worker-owner", workspace.workspace_id, workspace.schema_name, "queue"
        )
        return {"total": 0}

    memory.list_operations = AsyncMock(side_effect=snapshot)
    lifecycle = Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, Mock(spec=ExtensionContext)))
    assert await lifecycle._apply(operation) is False
    memory.delete_bank.assert_not_called()
    current = await repository.get_operation(ADMIN, operation.operation_id)
    assert current.state == "running" and current.error_code == "waiting_for_admissions"
