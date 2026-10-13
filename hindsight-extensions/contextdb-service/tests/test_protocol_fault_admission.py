"""A protocol-wrapped backend fault must not erase the durable cleanup barrier."""

from __future__ import annotations

import asyncio
from typing import cast

import httpx
import pytest
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.admission import AdmissionGuard, WorkspaceAdmissionMiddleware, mark_engine_started
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.repository import Repository

from .test_admission import GuardHost
from .test_extensions import configured  # noqa: F401 - pytest fixture
from .test_repository import ADMIN, key_input, ready_workspace


@pytest.mark.parametrize(
    "outcome,retained",
    [
        ("http_503", True),
        ("mcp_fault", True),
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
    member = (await repository.list_members(ADMIN, workspace.workspace_id, 10, 0)).items[0]
    key = await repository.create_key(ADMIN, workspace.workspace_id, member.member_id, key_input(), "protocol-key")
    guard = AdmissionGuard(cast(MemoryEngine, GuardHost(repository.pool, database_url)), configured)
    await guard.start()
    detached: list[asyncio.Task] = []

    async def app(scope, receive, send) -> None:
        if outcome == "mcp_fault":
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
                    started.set()
                    await asyncio.Event().wait()

            detached.append(asyncio.create_task(tool()))
            await started.wait()
        status = 503 if outcome == "http_503" else 403 if outcome == "safe_403" else 200
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"redacted synthetic response"})

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=WorkspaceAdmissionMiddleware(app, guard)), base_url="http://test"
        ) as client:
            await client.post("/mcp/workspace/", headers={"Authorization": key.secret})
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
