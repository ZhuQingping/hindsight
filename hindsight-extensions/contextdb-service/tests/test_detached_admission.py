"""A cancelled MCP response cannot leave its session handler outside the lock."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.admission import AdmissionGuard, AdmittedRequest, restore_admission
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import ServiceError
from hindsight_ext_contextdb.repository import Repository

from .test_admission import GuardHost
from .test_extensions import configured  # noqa: F401 - pytest fixture
from .test_repository import ADMIN, admin_actor, key_input, ready_workspace, space_user


@pytest.mark.parametrize("disconnect", ["http_cancel", "pg_loss"])
async def test_detached_handler_is_cancelled_and_drained_before_admission_exits(
    repository: Repository, database_url: str, configured: Settings, disconnect: str
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository), member.user_id, key_input(workspace.bank_id), "detached-key"
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    tool_started, cleanup_started, release_cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    detached: list[asyncio.Task[None]] = []
    captured: list[AdmittedRequest] = []

    async def tool(request: AdmittedRequest) -> None:
        with restore_admission(request):
            tool_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleanup_started.set()
                await release_cleanup.wait()

    async def http_owner() -> None:
        async with guard.enter(key.secret, workspace.bank_id) as admitted:
            captured.append(admitted)
            # Stateful MCP dispatches separately from the response coroutine.
            detached.append(asyncio.create_task(tool(admitted)))
            await asyncio.Event().wait()

    owner = asyncio.create_task(http_owner())
    deletion: asyncio.Task | None = None
    try:
        await asyncio.wait_for(tool_started.wait(), 5)
        if disconnect == "http_cancel":
            owner.cancel()
        else:
            pid = await repository.pool.fetchval(
                "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                "AND application_name='contextdb_admission' AND state='idle in transaction'"
            )
            assert pid is not None
            assert await repository.pool.fetchval("SELECT pg_terminate_backend($1)", pid)
        await asyncio.wait_for(cleanup_started.wait(), 5)
        assert not captured[0].active
        with pytest.raises(ServiceError, match="admission has ended"):
            with restore_admission(captured[0]):
                pytest.fail("Ended HTTP admission was restored")
        # A second cancellation must not release a healthy PG lock while the
        # session handler is still rolling back / finishing its finally block.
        owner.cancel()
        await asyncio.sleep(0)
        assert not owner.done()
        if disconnect == "http_cancel":
            deletion = asyncio.create_task(
                repository.delete_workspace(
                    ADMIN,
                    workspace.bank_id,
                    "detached-delete",
                    "r",
                    expected_id=workspace.workspace_id,
                    expected_version=workspace.version,
                )
            )
            deadline = asyncio.get_running_loop().time() + 5
            while not await repository.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                "AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.workspaces%FOR UPDATE%')"
            ):
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            assert not deletion.done()
        release_cleanup.set()
        with pytest.raises(asyncio.CancelledError if disconnect == "http_cancel" else ServiceError):
            await asyncio.wait_for(owner, 5)
        assert all(task.done() for task in detached)
        if deletion is not None:
            assert (await deletion).state == "pending"
    finally:
        release_cleanup.set()
        owner.cancel()
        await asyncio.gather(owner, *detached, return_exceptions=True)
        if deletion is not None:
            await asyncio.gather(deletion, return_exceptions=True)
        await guard.stop()
