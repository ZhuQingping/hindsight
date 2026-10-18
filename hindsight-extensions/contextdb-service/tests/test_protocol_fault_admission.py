"""A protocol-wrapped backend fault must not erase the durable cleanup barrier."""

from __future__ import annotations

import asyncio
from typing import cast

import httpx
import pytest
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.admission import (
    AdmissionGuard,
    WorkspaceAdmissionMiddleware,
    mark_engine_started,
    restore_admission,
)
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.repository import Repository

from .test_admission import GuardHost
from .test_extensions import configured  # noqa: F401 - pytest fixture
from .test_repository import admin_actor, key_input, ready_workspace, space_user


@pytest.mark.parametrize(
    "outcome,retained",
    [
        ("http_503", True),
        ("http_503_before_engine", False),
        ("mcp_fault", True),
        ("mcp_fault_before_engine", False),
        ("result_validation", True),
        ("bad_args", False),
        ("safe_403", False),
        ("detached_cancel", True),
    ],
)
async def test_normal_asgi_return_preserves_wrapped_fault_not_safe_rejection(
    repository: Repository, database_url: str, configured: Settings, outcome: str, retained: bool
) -> None:
    workspace = await ready_workspace(repository)
    member = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository), member.user_id, key_input(workspace.bank_id), "protocol-key"
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    detached: list[asyncio.Task] = []

    async def app(scope, receive, send) -> None:
        if outcome in {"http_503", "mcp_fault"}:
            mark_engine_started()
        if outcome in {"mcp_fault", "mcp_fault_before_engine"}:
            scope["hindsight.request_context_failure"]()
        elif outcome in {"result_validation", "bad_args"}:
            try:
                with scope["hindsight.request_context_restore"]():
                    if outcome == "result_validation":
                        mark_engine_started()  # Successful native gate preceded serialization failure.
                    raise ValueError("synthetic protocol validation failure")
            except ValueError:
                pass  # The real framework packages this into an MCP error response.
        elif outcome == "detached_cancel":
            started = asyncio.Event()

            async def tool() -> None:
                with scope["hindsight.request_context_restore"]():
                    mark_engine_started()
                    started.set()
                    await asyncio.Event().wait()

            detached.append(asyncio.create_task(tool()))
            await started.wait()
        status = 503 if outcome in {"http_503", "http_503_before_engine"} else 403 if outcome == "safe_403" else 200
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"redacted synthetic response"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard)), base_url="http://test"
        ) as client:
            await client.post(
                f"/v1/default/banks/{workspace.bank_id}/memories/recall", headers={"Authorization": key.secret}
            )
        assert await repository.has_outstanding_admissions(workspace.workspace_id) is retained
        if retained:
            assert (
                await repository.pool.fetchval(
                    "SELECT state FROM ctxdb_meta.request_admissions WHERE workspace_id=$1", workspace.workspace_id
                )
                == "interrupted"
            )
        assert all(task.done() for task in detached)
    finally:
        await asyncio.gather(*detached, return_exceptions=True)
        await guard.stop()


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("failure", ["tool_denied", "validation", "cancelled"])
async def test_guard_retains_only_faults_after_successful_engine_gate(
    repository: Repository, database_url: str, configured: Settings, started: bool, failure: str
) -> None:
    from fastmcp.exceptions import ToolError

    workspace = await ready_workspace(repository)
    user = await space_user(repository, workspace.workspace_id)
    key = await repository.create_key(
        await admin_actor(repository), user.user_id, key_input(workspace.bank_id), "engine-boundary"
    )
    error = (
        ToolError("Tool unavailable")
        if failure == "tool_denied"
        else ValueError("Invalid tool arguments")
        if failure == "validation"
        else asyncio.CancelledError()
    )
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    try:
        with pytest.raises(type(error)):
            async with guard.enter(key.secret, workspace.bank_id) as request:
                with restore_admission(request):
                    if started:
                        mark_engine_started()
                    raise error
        assert await repository.has_outstanding_admissions(workspace.workspace_id) is started
    finally:
        await guard.stop()
