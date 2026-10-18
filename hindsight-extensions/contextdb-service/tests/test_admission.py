"""Deterministic cross-connection drain races, no arbitrary grace period."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
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
    mark_engine_started,
)
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import (
    ApiKeyCreate,
    ServiceError,
    WorkspaceCreate,
)
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension

from .test_extensions import configured as configured
from .test_repository import ADMIN, ADMIN_SECRET, admin_actor, key_input, ready_workspace, space_user


@dataclass
class GuardHost:
    pool: asyncpg.Pool
    db_url: str

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
async def test_mcp_initialize_has_no_workspace_admission(
    repository: Repository, database_url: str, configured: Settings, path: str
) -> None:
    workspace = await ready_workspace(repository)
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    reached = False

    async def app(scope, receive, send) -> None:
        nonlocal reached
        reached = True
        assert "contextdb.admission" not in scope
        assert not await repository.has_outstanding_admissions(workspace.workspace_id)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"initialize handled by native MCP"})

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard)), base_url="http://test"
    ) as client:
        assert (await client.post(path)).status_code == 200
    assert reached


async def test_mcp_tool_admission_targets_bank_and_rechecks_revocation(
    repository: Repository, database_url: str, configured: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import mcp.types as mt
    from fastmcp.exceptions import ToolError
    from fastmcp.server.middleware import MiddlewareContext
    from fastmcp.tools.base import ToolResult
    from hindsight_ext_contextdb import mcp as contextdb_mcp
    from starlette.requests import Request

    workspace = await ready_workspace(repository)
    other = await ready_workspace(repository, "Other")
    user = await space_user(repository, workspace.workspace_id)
    actor = await admin_actor(repository)
    key = await repository.create_key(actor, user.user_id, key_input(workspace.bank_id), "mcp-key")
    tenant = ContextDBTenantExtension({})

    @dataclass
    class MCPHost(GuardHost):
        tenant_extension: ContextDBTenantExtension

    host = MCPHost(repository.pool, database_url, tenant)
    guard = AdmissionGuard(cast(MemoryEngine, host), configured)
    tenant.admission_guard = guard
    routing = contextdb_mcp.ContextDBMCPRouting(cast(MemoryEngine, host), configured)
    request = Request({"type": "http", "headers": [(b"authorization", key.secret.encode())]})
    monkeypatch.setattr(contextdb_mcp, "get_http_request", lambda: request)
    message = mt.CallToolRequestParams(name="recall", arguments={"bank_id": workspace.bank_id, "query": "q"})
    context = MiddlewareContext(message=message, method="tools/call")
    calls = 0

    async def next_tool(context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
        nonlocal calls
        calls += 1
        assert is_admitted(workspace.schema_name, workspace.bank_id)
        assert await repository.has_outstanding_admissions(workspace.workspace_id)
        assert not await repository.has_outstanding_admissions(other.workspace_id)
        return ToolResult(content="complete")

    await guard.start()
    try:
        await routing.on_call_tool(context, next_tool)
        assert calls == 1 and (not await repository.has_outstanding_admissions(workspace.workspace_id))
        forbidden = MiddlewareContext(
            message=mt.CallToolRequestParams(name="recall", arguments={"bank_id": other.bank_id}),
            method="tools/call",
        )
        with pytest.raises(ToolError, match="cannot access"):
            await routing.on_call_tool(forbidden, next_tool)
        await repository.revoke_key(actor, user.user_id, key.metadata.key_id, "revoke")
        with pytest.raises(ToolError):
            await routing.on_call_tool(context, next_tool)
        assert calls == 1 and (not await repository.has_outstanding_admissions(workspace.workspace_id))
    finally:
        await guard.stop()


@pytest.mark.parametrize("syntax", ["Bearer {}", "{}", "Bearer  {}  "])
async def test_delete_waits_for_admitted_asgi_operation_and_rejects_new_requests(
    repository: Repository, database_url: str, configured: Settings, syntax: str
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Guard",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "guard-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived, release = (asyncio.Event(), asyncio.Event())

    async def app(scope, receive, send) -> None:
        assert is_admitted(workspace.schema_name, workspace.bank_id)
        arrived.set()
        await release.wait()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"finished"})

    transport = httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            request = asyncio.create_task(
                client.post(
                    f"/v1/default/banks/{workspace.bank_id}/memories/recall",
                    headers={"Authorization": syntax.format(key.secret)},
                )
            )
            await asyncio.wait_for(arrived.wait(), 5)
            deleting = asyncio.create_task(
                repository.delete_workspace(
                    ADMIN,
                    workspace.bank_id,
                    "delete",
                    "request",
                    expected_id=workspace.workspace_id,
                    expected_version=workspace.version,
                )
            )
            deadline = asyncio.get_running_loop().time() + 5
            while not await repository.pool.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.workspaces%FOR UPDATE%')"
            ):
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            assert not deleting.done()
            release.set()
            assert (await request).text == "finished"
            assert (await deleting).state == "pending"
            assert (
                await client.post(
                    f"/v1/default/banks/{workspace.bank_id}/memories/recall", headers={"Authorization": key.secret}
                )
            ).status_code == 403
    finally:
        release.set()
        await guard.stop()


async def test_cancelled_request_releases_cross_replica_admission(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Cancel",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "cancel-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived = asyncio.Event()

    async def active() -> None:
        async with guard.enter(key.secret, workspace.bank_id):
            arrived.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(active())
    try:
        await arrived.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        deleted = await asyncio.wait_for(
            repository.delete_workspace(
                ADMIN,
                workspace.bank_id,
                "cancel-delete",
                "r",
                expected_id=workspace.workspace_id,
                expected_version=workspace.version,
            ),
            5,
        )
        assert deleted.state == "pending"
        with pytest.raises(ServiceError):
            async with guard.enter(key.secret, workspace.bank_id):
                pytest.fail("Inactive workspace admitted a new request")
    finally:
        await guard.stop()


async def test_inactive_periodic_queue_insert_is_rejected_in_native_transaction(
    repository: Repository, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    await repository.delete_workspace(
        ADMIN,
        workspace.bank_id,
        "periodic-delete",
        "r",
        expected_id=workspace.workspace_id,
        expected_version=workspace.version,
    )
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = repository.pool
    try:
        operation = await repository.claim_operation()
        assert operation is not None and operation.lease_token is not None
        await repository.complete_operation(operation)
        with pytest.raises(OperationValidationError):
            async with extension.async_submission_scope(workspace.schema_name, workspace.bank_id):
                pytest.fail("Deleted workspace admitted a background submission")
    finally:
        extension.metadata_pool = None


async def test_lost_admission_connection_cancels_downstream_without_reusing_lock(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Loss",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
        ),
        "loss-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    arrived = asyncio.Event()
    continued = False

    async def downstream() -> None:
        nonlocal continued
        async with guard.enter(key.secret, workspace.bank_id):
            mark_engine_started()
            arrived.set()
            await asyncio.Event().wait()
            continued = True

    request = asyncio.create_task(downstream())
    try:
        await arrived.wait()
        pid = await repository.pool.fetchval(
            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='contextdb_admission' AND state='idle in transaction'"
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
        assert (
            await repository.delete_workspace(
                ADMIN,
                workspace.bank_id,
                "lost-delete",
                "r",
                expected_id=workspace.workspace_id,
                expected_version=workspace.version,
            )
        ).state == "pending"
    finally:
        if not request.done():
            request.cancel()
        await guard.stop()


async def test_waiting_metadata_writers_and_queue_scopes_do_not_starve_engine_pool(
    repository: Repository, database_url: str, configured: Settings
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        member.user_id,
        ApiKeyCreate(
            name="Pool",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": "read"}],
            },
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
    arrived, release = (asyncio.Event(), asyncio.Event())
    tasks: list[asyncio.Task] = []

    async def request() -> None:
        async with guard.enter(key.secret, workspace.bank_id):
            arrived.set()
            await release.wait()
            assert await asyncio.wait_for(host_pool.fetchval("SELECT 1"), 2) == 1

    async def queue() -> None:
        async with extension.async_submission_scope(workspace.schema_name, workspace.bank_id):
            assert await host_pool.fetchval("SELECT 1") == 1

    async def metadata_writer() -> None:
        async with metadata_pool.acquire() as conn, conn.transaction():
            await conn.fetchrow(
                "SELECT workspace_id FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR UPDATE",
                workspace.workspace_id,
            )
            await conn.execute(
                "UPDATE ctxdb_meta.workspaces SET description='updated' WHERE workspace_id=$1", workspace.workspace_id
            )

    await guard.start()
    try:
        tasks.append(asyncio.create_task(request()))
        await arrived.wait()
        tasks.append(asyncio.create_task(metadata_writer()))
        deadline = asyncio.get_running_loop().time() + 5
        while not await repository.pool.fetchval(
            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%ctxdb_meta.workspaces%FOR UPDATE%')"
        ):
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.01)
        tasks.extend((asyncio.create_task(queue()) for _ in range(2)))
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
        async with extension.async_submission_scope(workspace.schema_name, workspace.bank_id):
            arrived.set()
            await asyncio.Event().wait()
            continued = True

    task = asyncio.create_task(submit())
    try:
        await asyncio.wait_for(arrived.wait(), 5)
        pid = await repository.pool.fetchval(
            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() AND application_name='ctxdb_test_queue_guard' AND state='idle in transaction'"
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
    assert operation is not None and operation.lease_token is not None
    workspace = await repository.operation_workspace(operation)
    extension = ContextDBTenantExtension({})
    extension.metadata_pool = repository.pool
    try:
        with initializing_bank(workspace.schema_name, workspace.bank_id, operation.operation_id, operation.lease_token):
            async with extension.async_submission_scope(workspace.schema_name, workspace.bank_id):
                pass
        await repository.pool.execute(
            "UPDATE ctxdb_meta.management_operations SET lease_until=now()-interval '1 second' WHERE operation_id=$1",
            operation.operation_id,
        )
        with initializing_bank(workspace.schema_name, workspace.bank_id, operation.operation_id, operation.lease_token):
            with pytest.raises(OperationValidationError, match="lease was lost"):
                async with extension.async_submission_scope(workspace.schema_name, workspace.bank_id):
                    pytest.fail("Expired initializer admitted a queue INSERT")
    finally:
        extension.metadata_pool = None


@pytest.mark.parametrize("permission", ["read", "read_write"])
@pytest.mark.parametrize(
    "suffix,method",
    [("/export", "GET"), ("/transfer/export", "POST"), ("/document-transfer/export", "POST"), ("/download", "GET")],
)
async def test_archives_remain_operator_only_and_do_not_leak_admission(
    repository: Repository,
    database_url: str,
    configured: Settings,
    permission: str,
    suffix: str,
    method: str,
) -> None:
    workspace = await ready_workspace(repository)
    user = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository),
        user.user_id,
        ApiKeyCreate(
            name="Archive reader",
            authorization={
                "mode": "selected",
                "workspaces": [{"bank_id": workspace.bank_id, "permission": permission}],
            },
        ),
        "archive-key",
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    reached = False

    async def app(scope, receive, send) -> None:
        nonlocal reached
        reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"archive"})

    path = (
        f"/v1/default/files/download/tenants/{workspace.schema_name}/banks/{workspace.bank_id}/export.zip"
        if suffix == "/download"
        else f"/v1/default/banks/{workspace.bank_id}{suffix}"
    )
    await guard.start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard)), base_url="http://test"
        ) as client:
            response = await client.request(method, path, headers={"Authorization": "Bearer " + key.secret})
            assert response.status_code == 403
            assert not reached
            assert not await repository.has_outstanding_admissions(workspace.workspace_id)
            response = await client.request(method, path, headers={"Authorization": "Bearer " + ADMIN_SECRET})
            assert response.status_code == 200 and reached
            assert not await repository.has_outstanding_admissions(workspace.workspace_id)
    finally:
        await guard.stop()
