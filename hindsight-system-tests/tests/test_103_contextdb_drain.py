"""Public-client drain races against real PG and both Worker deployments.

The one SQL use is fixture fault/barrier orchestration, not reading memory to
assert a result. All observable memory behavior uses the published SDK or MCP.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, Literal

import asyncpg
import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from hindsight_client_api.exceptions import ForbiddenException
from mcp.types import CallToolResult, JSONRPCError, JSONRPCMessage, JSONRPCResponse, TextContent
from pydantic import BaseModel

from hindsight_system_tests import reflect_loop
from hindsight_system_tests.payloads import consolidation, extracted, fact
from hindsight_system_tests.rulebook import LLMStub

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import (  # noqa: F401
    ContextDBDeployment,
    MemberClients,
)

contextdb_deployment = service_story.contextdb_deployment
contextdb_clients = service_story.contextdb_clients

pytest_plugins = ["tests.test_100_contextdb_service"]


class ToolName(BaseModel):
    name: str | None = None


class RpcRequest(BaseModel):
    method: str
    id: int | str | None = None
    params: ToolName | None = None


class ReflectAnswer(BaseModel):
    text: str


class WireEvent(BaseModel):
    sequence: int
    kind: Literal["request", "status", "rpc", "delete_waiting", "delete_accepted"]
    http_method: str | None = None
    method: str | None = None
    rpc_id: int | str | None = None
    tool: str | None = None
    status: int | None = None
    is_error: bool | None = None
    text: str | None = None


class WireTrace:
    def __init__(self) -> None:
        self.events: list[WireEvent] = []

    def record(
        self, kind: Literal["request", "status", "rpc", "delete_waiting", "delete_accepted"], **values: Any
    ) -> WireEvent:
        event = WireEvent(sequence=len(self.events), kind=kind, **values)
        self.events.append(event)
        return event

    async def request(self, request: httpx.Request) -> None:
        rpc = RpcRequest.model_validate_json(request.content) if request.method == "POST" else None
        event = self.record(
            "request",
            http_method=request.method,
            method=rpc.method if rpc else None,
            rpc_id=rpc.id if rpc else None,
            tool=rpc.params.name if rpc and rpc.params else None,
        )
        request.extensions["ctxdb_test_rpc"] = event

    async def response(self, response: httpx.Response) -> None:
        request = response.request.extensions["ctxdb_test_rpc"]
        self.record("status", **request.model_dump(exclude={"sequence", "kind", "status"}), status=response.status_code)
        assert isinstance(response.stream, httpx.AsyncByteStream)
        response.stream = ObservedStream(response.stream, self, request, response.headers.get("content-type", ""))

    def client_factory(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        # Only method/id/status and synthetic response summaries are recorded.
        # Identity encoding lets the observer see bytes without changing SSE flow.
        headers = {**(headers or {}), "Accept-Encoding": "identity"}
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=follow_redirects,
            event_hooks={"request": [self.request], "response": [self.response]},
        )

    def received(self, request: WireEvent, payload: bytes) -> None:
        message = JSONRPCMessage.model_validate_json(payload).root
        summary: ReflectAnswer | None = None
        result: CallToolResult | None = None
        if request.method == "tools/call" and isinstance(message, JSONRPCResponse):
            result = CallToolResult.model_validate(message.result)
            texts = [item.text for item in result.content if isinstance(item, TextContent)]
            if not result.isError:
                assert len(texts) == 1
                summary = ReflectAnswer.model_validate_json(texts[0])
        self.record(
            "rpc",
            http_method=request.http_method,
            method=request.method,
            rpc_id=message.id if isinstance(message, JSONRPCResponse | JSONRPCError) else None,
            tool=request.tool,
            is_error=result.isError if result else isinstance(message, JSONRPCError),
            text=summary.text if summary else None,
        )

    def expected_followup_revocation(self, error: httpx.HTTPStatusError) -> None:
        failed = error.request.extensions["ctxdb_test_rpc"]
        assert error.response.status_code == 401
        assert failed.method == "tools/list", "The actual tool request must never be accepted as a revoked follow-up"
        waiting = [event for event in self.events if event.kind == "delete_waiting"]
        success = [event for event in self.events if event.kind == "rpc" and event.method == "tools/call"]
        assert len(waiting) == len(success) == 1
        assert success[0].tool == "reflect" and success[0].is_error is False
        assert success[0].text == "DrainBarrier completed."
        assert waiting[0].sequence < success[0].sequence < failed.sequence
        rejected = [
            event
            for event in self.events
            if event.kind == "status" and event.method == failed.method and event.rpc_id == failed.rpc_id
        ]
        assert len(rejected) == 1 and rejected[0].status == 401
        assert failed.sequence < rejected[0].sequence
        calls = [event for event in self.events if event.kind == "request" and event.method == "tools/call"]
        assert len(calls) == 1 and calls[0].rpc_id == success[0].rpc_id
        statuses = [event.status for event in self.events if event.kind == "status" and event.rpc_id == calls[0].rpc_id]
        assert statuses == [200]


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, trace: WireTrace, request: WireEvent, content_type: str) -> None:
        self.stream, self.trace, self.request = stream, trace, request
        self.sse = content_type.startswith("text/event-stream")
        self.json = content_type.startswith("application/json")

    async def __aiter__(self) -> AsyncIterator[bytes]:
        buffer = b""
        async for chunk in self.stream:
            if self.sse:
                buffer = (buffer + chunk).replace(b"\r\n", b"\n")
                while b"\n\n" in buffer:
                    frame, buffer = buffer.split(b"\n\n", 1)
                    data = b"\n".join(line[5:].lstrip() for line in frame.split(b"\n") if line.startswith(b"data:"))
                    if data:
                        self.trace.received(self.request, data)
            elif self.json:
                buffer += chunk
            # Observe as the SDK reads: never aread an unbounded GET/SSE stream.
            yield chunk
        if self.json and buffer and self.request.method == "tools/call":
            self.trace.received(self.request, buffer)

    async def aclose(self) -> None:
        await self.stream.aclose()


@pytest.mark.parametrize("failure", ["tool_401", "wrong_rpc_id", "tool_error", "wrong_answer"])
def test_followup_revocation_requires_a_proven_successful_tool(failure: str) -> None:
    trace = WireTrace()
    trace.record("request", http_method="POST", method="tools/call", rpc_id=1, tool="reflect")
    trace.record("status", http_method="POST", method="tools/call", rpc_id=1, status=200)
    trace.record("delete_waiting")
    result = trace.record(
        "rpc", method="tools/call", rpc_id=1, tool="reflect", is_error=False, text="DrainBarrier completed."
    )
    failed = trace.record("request", http_method="POST", method="tools/list", rpc_id=2)
    trace.record("status", http_method="POST", method="tools/list", rpc_id=2, status=401)
    if failure == "tool_401":
        failed.method = "tools/call"
    elif failure == "wrong_rpc_id":
        result.rpc_id = 99
    elif failure == "tool_error":
        result.is_error = True
    else:
        result.text = "An unrelated answer"
    request = httpx.Request("POST", "http://unused.invalid/mcp/")
    request.extensions["ctxdb_test_rpc"] = failed
    error = httpx.HTTPStatusError(
        "synthetic revocation", request=request, response=httpx.Response(401, request=request)
    )
    with pytest.raises(AssertionError):
        trace.expected_followup_revocation(error)


@asynccontextmanager
async def session_revoked_on_delete(
    deployment: ContextDBDeployment,
    clients: MemberClients,
    trace: WireTrace,
    record_property: Callable[[str, object], None],
) -> AsyncIterator[Client]:
    transport = StreamableHttpTransport(
        f"{deployment.server.url}/mcp/{clients.bank_id}/",
        auth=clients.own_key,
        httpx_client_factory=trace.client_factory,
    )
    client = Client(transport)
    await client.__aenter__()
    try:
        yield client
    finally:
        try:
            await client.__aexit__(None, None, None)
        except httpx.HTTPStatusError as error:
            trace.expected_followup_revocation(error)
            with pytest.raises(ForbiddenException):
                await clients.own.arecall(bank_id=clients.bank_id, query="Verify revoked session")
        finally:
            record_property("mcp_wire_trace", json.dumps([event.model_dump() for event in trace.events]))


async def deleted(deployment: ContextDBDeployment, operation_id: str) -> None:
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers
    ) as management:
        deadline = asyncio.get_running_loop().time() + 45
        while True:
            result = await management.get(f"/operations/{operation_id}")
            assert result.status_code == 200, result.text
            assert result.json()["state"] != "failed", result.text
            if result.json()["state"] == "succeeded":
                return
            assert asyncio.get_running_loop().time() < deadline
            await asyncio.sleep(0.1)


@pytest.mark.parametrize("transport", ["sdk-sync-retain", "mcp-reflect"])
async def test_delete_waits_for_real_synchronous_retain(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    llm: LLMStub,
    transport: str,
    record_property: Callable[[str, object], None],
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    llm.on_step("extract_facts", contains="DrainBarrier").returns(
        extracted(fact("Alice builds DrainBarrier", who="Alice", entities=["Alice", "DrainBarrier"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    reflect_loop(llm, answer="DrainBarrier completed.")
    trace = WireTrace()
    async with httpx.AsyncClient(base_url=deployment.server.url, timeout=60) as management:
        async with llm.hold("extract_facts" if transport == "sdk-sync-retain" else "reflect") as held:
            async with session_revoked_on_delete(deployment, clients, trace, record_property) as mcp:
                retain = asyncio.create_task(
                    clients.own.aretain(
                        bank_id=clients.bank_id, content="Alice builds DrainBarrier.", retain_async=False
                    )
                    if transport == "sdk-sync-retain"
                    else mcp.call_tool("reflect", {"query": "Describe DrainBarrier."})
                )
                await held.reached()
                remove = asyncio.create_task(
                    management.delete(
                        f"/ext/contextdb/v1/workspaces/{clients.bank_id}",
                        headers=await service_story.workspace_condition_headers(
                            management,
                            f"/ext/contextdb/v1/workspaces/{clients.bank_id}",
                            {**deployment.headers, "Idempotency-Key": secrets.token_hex(8)},
                        ),
                    )
                )
                # The LLM arrival is a real execution barrier. The control request
                # must not finish while that synchronous write is still parked.
                await asyncio.sleep(0.3)
                assert not remove.done()
                trace.record("delete_waiting")
                held.release()
                try:
                    result = await asyncio.wait_for(retain, 30)
                except httpx.HTTPStatusError as error:
                    if transport != "mcp-reflect":
                        raise
                    # The SDK validates a completed result with a later tools/list.
                    # Accept only that revoked follow-up, proven by matching the
                    # successful tools/call ID/payload after the deletion barrier.
                    trace.expected_followup_revocation(error)
                else:
                    if transport == "mcp-reflect":
                        assert not result.is_error
                response = await asyncio.wait_for(remove, 30)
                assert response.status_code == 202, response.text
                trace.record("delete_accepted")
                await deleted(deployment, response.json()["operation_id"])
    with pytest.raises(ForbiddenException):
        await clients.own.arecall(bank_id=clients.bank_id, query="DrainBarrier")
    assert (await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="DrainBarrier")).results == []


async def test_delete_cannot_cross_authenticated_async_retain_before_queue_insert(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    llm.on_step("extract_facts", contains="QueueBarrier").returns(
        extracted(fact("Alice builds QueueBarrier", who="Alice", entities=["Alice", "QueueBarrier"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    conn = await asyncpg.connect(deployment.database_url)
    transaction = conn.transaction()
    async with httpx.AsyncClient(base_url=deployment.server.url, headers=deployment.headers, timeout=60) as management:
        # Schema names are deliberately absent from the public workspace API.
        # This isolated fixture lookup only locates the SQL fault barrier, never
        # reads memory or supplies customer-visible authorization assertions.
        schema = await conn.fetchval("SELECT schema_name FROM ctxdb_meta.workspaces WHERE bank_id=$1", clients.bank_id)
        assert schema.startswith("ctxdb_ws_") and len(schema) <= 63
        try:
            await transaction.start()
            # SHARE table lock admits reads but blocks the queue INSERT's
            # RowExclusive lock, after the native retain validator has accepted.
            await conn.execute(f'LOCK TABLE "{schema}".async_operations IN SHARE MODE')
            retain = asyncio.create_task(
                clients.own.aretain(bank_id=clients.bank_id, content="Alice builds QueueBarrier.", retain_async=True)
            )
            deadline = asyncio.get_running_loop().time() + 10
            while True:
                # PostgreSQL activity statistics are transaction-cached. Clear
                # the barrier connection's snapshot before observing arrival.
                await conn.execute("SELECT pg_stat_clear_snapshot()")
                if await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE datname=current_database() "
                    "AND wait_event_type='Lock' AND query LIKE $1)",
                    f"%INSERT INTO%{schema}%async_operations%",
                ):
                    break
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.01)
            remove = asyncio.create_task(
                management.delete(
                    f"/ext/contextdb/v1/workspaces/{clients.bank_id}",
                    headers=await service_story.workspace_condition_headers(
                        management,
                        f"/ext/contextdb/v1/workspaces/{clients.bank_id}",
                        {"Idempotency-Key": secrets.token_hex(8)},
                    ),
                )
            )
            await asyncio.sleep(0.3)
            assert not remove.done()
            await transaction.rollback()
            result = await asyncio.wait_for(retain, 30)
            assert result.operation_id
            response = await asyncio.wait_for(remove, 30)
            assert response.status_code == 202, response.text
            await deleted(deployment, response.json()["operation_id"])
        finally:
            await conn.close()
    with pytest.raises(ForbiddenException):
        await clients.own.arecall(bank_id=clients.bank_id, query="QueueBarrier")
