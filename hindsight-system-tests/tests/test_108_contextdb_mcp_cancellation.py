"""A lost MCP HTTP admission must stop its separately dispatched tool handler.

The test-only extension records method lifecycle, never Key/payload contents.
SQL is used only to terminate this fixture's admission connection. Observable
memory/queue checks use the published SDK and are secondary to the exit trace.
"""

from __future__ import annotations

import asyncio
import inspect
import secrets
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import asyncpg
import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError
from pydantic import BaseModel

from hindsight_system_tests import LLMStub, reflect_loop
from hindsight_system_tests.server import HindsightServer

from . import test_100_contextdb_service as service
from .test_100_contextdb_service import ContextDBDeployment, MemberClients

pytestmark = pytest.mark.asyncio
SERVER_EXTENSIONS = Path(__file__).resolve().parents[1] / "server_extensions"


@dataclass
class CancellationDeployment:
    deployment: ContextDBDeployment
    trace_id: str


@pytest.fixture(params=["embedded-worker", "standalone-worker"])
def cancellation_deployment(
    request: pytest.FixtureRequest,
    stub_server: Any,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[CancellationDeployment]:
    trace_id = secrets.token_hex(8)
    original = service.start_hindsight_server
    startup_probe = tmp_path_factory.mktemp("contextdb-cancellation-observer")
    # Observe the real registered extension rather than replacing its routing
    # with the old trace-only MCP slot. This isolated subprocess startup hook
    # calls the original registration before adding logging-only middleware.
    (startup_probe / "sitecustomize.py").write_text(
        "from hindsight_ext_contextdb.mcp import ContextDBMCPExtension\n"
        "from contextdb_cancellation_probe import CancellationTrace\n"
        "original_register = ContextDBMCPExtension.register_tools\n"
        "def observed_register(self, mcp, memory):\n"
        "    original_register(self, mcp, memory)\n"
        "    mcp.add_middleware(CancellationTrace())\n"
        "ContextDBMCPExtension.register_tools = observed_register\n"
    )

    def instrumented_start(
        *,
        stub_url: str,
        log_path: Path,
        database_url: str,
        python_executable: str,
        extra_env: dict[str, str],
    ) -> HindsightServer:
        environment = {
            **extra_env,
            "PYTHONPATH": extra_env["PYTHONPATH"] + ":" + str(SERVER_EXTENSIONS) + ":" + str(startup_probe),
            "CONTEXTDB_TEST_CANCEL_TRACE_ID": trace_id,
        }
        return original(
            stub_url=stub_url,
            log_path=log_path,
            database_url=database_url,
            python_executable=python_executable,
            extra_env=environment,
        )

    monkeypatch.setattr(service, "start_hindsight_server", instrumented_start)
    # Unwrap pytest's fixture decorator, preserving its existing PG/process
    # ownership rather than duplicating database lifecycle code here.
    factory = cast(
        Callable[..., Generator[ContextDBDeployment, None, None]], inspect.unwrap(service.contextdb_deployment)
    )
    owner = factory(SimpleNamespace(param=request.param), stub_server, tmp_path_factory)
    try:
        yield CancellationDeployment(next(owner), trace_id)
    finally:
        owner.close()


@pytest.fixture
async def cancellation_clients(cancellation_deployment: CancellationDeployment) -> AsyncIterator[MemberClients]:
    factory = cast(
        Callable[[ContextDBDeployment], AsyncGenerator[MemberClients, None]], inspect.unwrap(service.contextdb_clients)
    )
    owner = factory(cancellation_deployment.deployment)
    try:
        yield await anext(owner)
    finally:
        await owner.aclose()


class ToolName(BaseModel):
    name: str | None = None


class RpcMethod(BaseModel):
    method: str
    params: ToolName | None = None


class HttpToolRequest:
    """Capture the actual HTTP transport task, not the MCP logical call task."""

    def __init__(self) -> None:
        self.task: asyncio.Task[Any] | None = None

    async def observe(self, request: httpx.Request) -> None:
        if request.method == "POST":
            rpc = RpcMethod.model_validate_json(request.content)
            if rpc.method == "tools/call" and rpc.params is not None and rpc.params.name == "reflect":
                self.task = asyncio.current_task()

    def client_factory(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout or httpx.Timeout(30, read=60),
            auth=auth,
            follow_redirects=follow_redirects,
            event_hooks={"request": [self.observe]},
        )


async def wait_for_handler_exit(probe: CancellationDeployment) -> str:
    prefix = f"ContextDB test tool {probe.trace_id} reflect "
    deadline = asyncio.get_running_loop().time() + 10
    while True:
        logs = probe.deployment.server.logs()
        if prefix + "exited" in logs:
            assert prefix + "started" in logs
            assert prefix + "cancelled" in logs
            assert logs.index(prefix + "started") < logs.index(prefix + "cancelled") < logs.index(prefix + "exited")
            return "\n".join(line for line in logs.splitlines() if prefix in line)
        assert asyncio.get_running_loop().time() < deadline, "Detached MCP handler did not terminate"
        await asyncio.sleep(0.02)


@pytest.mark.parametrize("disconnect", ["pg_loss", "http_abort"])
async def test_lost_http_admission_terminates_real_detached_mcp_tool(
    cancellation_deployment: CancellationDeployment,
    cancellation_clients: MemberClients,
    llm: LLMStub,
    disconnect: str,
    record_property: Callable[[str, object], None],
) -> None:
    deployment, clients = cancellation_deployment.deployment, cancellation_clients
    reflect_loop(llm, answer="CancellationBarrier must not finish.")
    observer = HttpToolRequest()
    transport = StreamableHttpTransport(
        f"{deployment.server.url}/mcp/{clients.bank_id}/",
        auth=clients.own_key,
        httpx_client_factory=observer.client_factory,
    )
    async with Client(transport) as mcp:
        async with llm.hold("reflect") as held:
            call = asyncio.create_task(mcp.call_tool("reflect", {"query": "Describe CancellationBarrier."}))
            try:
                await held.reached()
                assert observer.task is not None
                if disconnect == "pg_loss":
                    connection = await asyncpg.connect(deployment.database_url)
                    try:
                        # Exact fixture DB and application label: never target a
                        # developer/default service PID or inspect memory tables.
                        rows = await connection.fetch(
                            "SELECT pid FROM pg_stat_activity WHERE datname=current_database() "
                            "AND application_name='contextdb_admission' AND state='idle in transaction'"
                        )
                        assert len(rows) == 1
                        assert await connection.fetchval("SELECT pg_terminate_backend($1)", rows[0]["pid"])
                    finally:
                        await connection.close()
                else:
                    # Abort only HTTP tools/call. Cancelling the logical MCP call
                    # would send notifications/cancelled and test SDK cancellation
                    # rather than the service's detached-handler drain boundary.
                    observer.task.cancel("Synthetic tools/call HTTP abort")
                trace = await wait_for_handler_exit(cancellation_deployment)
                record_property("mcp_handler_trace_before_provider_release", trace)
                # Exit is proven before the provider is unparked: a handler that
                # continued later cannot make an empty-memory assertion pass.
                held.release()
                if call.done():
                    if call.cancelled():
                        record_property("client_terminal", "CancelledError")
                    else:
                        failure = call.exception()
                        if isinstance(failure, RuntimeError):
                            # Aborting the SDK's HTTP task can end its session
                            # runner without an exception. Its monitor maps only
                            # that exact outcome to this documented RuntimeError.
                            assert disconnect == "http_abort"
                            assert str(failure) == "Session task completed unexpectedly"
                        else:
                            assert isinstance(failure, (httpx.TransportError, McpError, ToolError)), (
                                "MCP unexpectedly completed"
                            )
                            if isinstance(failure, ToolError):
                                # Per-tool routing reports the admission loss in
                                # MCP's error envelope instead of dropping HTTP.
                                assert str(failure) == "Workspace admission was interrupted"
                        record_property("client_terminal", type(failure).__name__)
                else:
                    call.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await call
                    record_property("client_terminal", "Test cleanup after proven server handler exit")
            finally:
                held.release()
                if not call.done():
                    call.cancel()
                await asyncio.gather(call, return_exceptions=True)
    assert (await clients.own.memory.list_memories(clients.bank_id, limit=100)).total == 0
    assert (await clients.own.operations.list_operations(clients.bank_id, limit=100)).operations == []
