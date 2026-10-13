"""Deterministic cross-connection drain races, no arbitrary grace period."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

import asyncpg
import httpx
import pytest
from hindsight_api import MemoryEngine
from hindsight_api.extensions.operation_validator import OperationValidationError
from hindsight_ext_contextdb.admission import (
    AdmissionGuard,
    WorkspaceAdmissionMiddleware,
    initializing_bank,
    is_admitted,
)
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import ApiKeyCreate, Scope, ServiceError, WorkspaceCreate, WorkspacePatch
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension

from .test_extensions import configured  # noqa: F401 - pytest fixture
from .test_repository import ADMIN, ready_workspace


@dataclass
class GuardHost:
    pool: asyncpg.Pool
    db_url: str

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@pytest.mark.parametrize("syntax", ["Bearer {}", "{}", "Bearer  {}  "])
async def test_delete_waits_for_admitted_asgi_operation_and_rejects_new_requests(
    repository: Repository, database_url: str, configured: Settings, syntax: str
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Guard", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "guard-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived, release = asyncio.Event(), asyncio.Event()

    async def app(scope, receive, send) -> None:
        assert is_admitted(workspace.schema_name, workspace.workspace_id)
        arrived.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"finished"})

    transport = httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request = asyncio.create_task(
                client.post("/mcp/bank/", headers={"Authorization": syntax.format(key.secret)})
            )
            await asyncio.wait_for(arrived.wait(), 5)
            deleting = asyncio.create_task(
                repository.delete_workspace(ADMIN, workspace.workspace_id, "delete", "request")
            )
            # Confirm the exclusive lock is actually waiting in PG, not merely
            # that the Python task has not yet been scheduled.
            deadline = asyncio.get_running_loop().time() + 5
            while not await repository.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                "AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.workspaces%FOR UPDATE%')"
            ):
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            assert not deleting.done()
            release.set()
            assert (await request).text == "finished"
            assert (await deleting).state == "pending"
            assert (await client.post("/mcp/bank/", headers={"Authorization": key.secret})).status_code == 401
    finally:
        release.set()
        await guard.stop()


async def test_cancelled_request_releases_cross_replica_admission(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Cancel", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "cancel-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived = asyncio.Event()

    async def active() -> None:
        async with guard.enter(key.secret):
            arrived.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(active())
    try:
        await arrived.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deleted = await asyncio.wait_for(
            repository.delete_workspace(ADMIN, workspace.workspace_id, "cancel-delete", "r"), 5
        )
        assert deleted.state == "pending"
        with pytest.raises(ServiceError):
            async with guard.enter(key.secret):
                pytest.fail("Inactive workspace admitted a new request")
    finally:
        await guard.stop()


async def test_inactive_periodic_queue_insert_is_rejected_in_native_transaction(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    await repository.delete_workspace(ADMIN, workspace.workspace_id, "periodic-delete", "r")
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = repository.pool
    try:
        # No native queue exists in this metadata fixture: querying it would
        # raise UndefinedTable rather than the expected rejection. A deleted
        # workspace must fail before touching any native schema.
        operation = await repository.claim_operation()
        assert operation is not None
        await repository.complete_operation(operation)
        with pytest.raises(OperationValidationError):
            async with extension.async_submission_scope(workspace.schema_name, workspace.workspace_id):
                pytest.fail("Deleted workspace admitted a background submission")
    finally:
        extension.metadata_pool = None


async def test_lost_admission_connection_cancels_downstream_without_reusing_lock(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Loss", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "loss-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived = asyncio.Event()
    continued = False

    async def downstream() -> None:
        nonlocal continued
        async with guard.enter(key.secret):
            arrived.set()
            await asyncio.Event().wait()
            continued = True

    request = asyncio.create_task(downstream())
    try:
        await arrived.wait()
        # Fault injection targets this fixture database and the explicitly named
        # admission connection, never the developer's PG/backend.
        pid = await repository.pool.fetchval(
            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
            "AND application_name='contextdb_admission' AND state='idle in transaction'"
        )
        assert pid is not None
        assert await repository.pool.fetchval("SELECT pg_terminate_backend($1)", pid)
        with pytest.raises(ServiceError) as error:
            await asyncio.wait_for(request, 5)
        assert error.value.code == "admission_lost"
        assert not continued
        assert await repository.has_outstanding_admissions(workspace.workspace_id)
        assert (
            await repository.pool.fetchval(
                "SELECT state FROM ctxdb_meta.request_admissions WHERE workspace_id=$1", workspace.workspace_id
            )
            == "interrupted"
        )
        assert (await repository.delete_workspace(ADMIN, workspace.workspace_id, "lost-delete", "r")).state == "pending"
    finally:
        if not request.done():
            request.cancel()
        await guard.stop()


async def test_waiting_metadata_writers_and_queue_scopes_do_not_starve_engine_pool(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(
        ADMIN,
        workspace.workspace_id,
        member.member_id,
        ApiKeyCreate(
            name="Pool", scopes=[Scope.MEMORY_READ], expires_at=datetime.now(timezone.utc) + timedelta(days=1)
        ),
        "pool-key",
    )
    host_pool = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    metadata_pool = await asyncpg.create_pool(database_url, min_size=0, max_size=4)
    assert host_pool is not None and metadata_pool is not None
    host = GuardHost(host_pool, database_url)
    guard = AdmissionGuard(cast(MemoryEngine, host), configured)
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = metadata_pool
    control = Repository(metadata_pool, repository.instance_id, repository.cloud_tenant_id, repository.pepper)
    arrived, release = asyncio.Event(), asyncio.Event()
    tasks: list[asyncio.Task] = []

    async def request() -> None:
        async with guard.enter(key.secret):
            arrived.set()
            await release.wait()
            assert await asyncio.wait_for(host_pool.fetchval("SELECT 1"), 2) == 1

    async def queue() -> None:
        async with extension.async_submission_scope(workspace.schema_name, workspace.workspace_id):
            assert await host_pool.fetchval("SELECT 1") == 1

    await guard.start()
    try:
        tasks.append(asyncio.create_task(request()))
        await arrived.wait()
        tasks.append(
            asyncio.create_task(
                control.update_workspace(
                    ADMIN, workspace.workspace_id, WorkspacePatch(state="active"), workspace.version, "pool-writer"
                )
            )
        )
        deadline = asyncio.get_running_loop().time() + 5
        while not await repository.pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
            "AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.workspaces%FOR UPDATE%')"
        ):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        tasks.extend(asyncio.create_task(queue()) for _ in range(2))
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        extension.metadata_pool = None
        await guard.stop()
        await metadata_pool.close()
        await host_pool.close()


async def test_lost_queue_admission_connection_cancels_submission(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    metadata_pool = await asyncpg.create_pool(
        database_url, min_size=0, max_size=2, server_settings={"application_name": "ctxdb_test_queue_guard"}
    )
    assert metadata_pool is not None
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = metadata_pool
    arrived = asyncio.Event()
    continued = False

    async def submit() -> None:
        nonlocal continued
        async with extension.async_submission_scope(workspace.schema_name, workspace.workspace_id):
            arrived.set()
            await asyncio.Event().wait()
            continued = True

    task = asyncio.create_task(submit())
    try:
        await asyncio.wait_for(arrived.wait(), 5)
        pid = await repository.pool.fetchval(
            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
            "AND application_name='ctxdb_test_queue_guard' AND state='idle in transaction'"
        )
        assert pid is not None
        assert await repository.pool.fetchval("SELECT pg_terminate_backend($1)", pid)
        with pytest.raises(OperationValidationError) as error:
            await asyncio.wait_for(task, 5)
        assert error.value.status_code == 503
        assert not continued
        assert await repository.has_outstanding_admissions(workspace.workspace_id)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        extension.metadata_pool = None
        await metadata_pool.close()


async def test_initial_template_requires_current_operation_lease(repository: Repository, configured: Settings) -> None:
    created = await repository.create_workspace(ADMIN, WorkspaceCreate(name="Template"), "template-create", "r")
    operation = await repository.claim_operation()
    assert operation is not None
    workspace = await repository.operation_workspace(operation)
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = repository.pool
    try:
        with initializing_bank(
            workspace.schema_name, created.workspace_id, operation.operation_id, operation.lease_token
        ):
            async with extension.async_submission_scope(workspace.schema_name, created.workspace_id):
                pass  # Creating workspace may enqueue its template under the valid lease.
        await repository.pool.execute(
            "UPDATE ctxdb_meta.management_operations SET lease_until=now()-interval '1 second' WHERE operation_id=$1",
            operation.operation_id,
        )
        with initializing_bank(
            workspace.schema_name, created.workspace_id, operation.operation_id, operation.lease_token
        ):
            with pytest.raises(OperationValidationError, match="lease was lost"):
                async with extension.async_submission_scope(workspace.schema_name, created.workspace_id):
                    pytest.fail("Expired initializer admitted a queue INSERT")
    finally:
        extension.metadata_pool = None
