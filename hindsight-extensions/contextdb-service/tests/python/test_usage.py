"""Bounded asynchronous usage, failure semantics and request-local collection."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from hindsight_api.engine.response_models import MemoryFact
from hindsight_api.engine.response_models import RecallResult as RecallPayload
from hindsight_api.extensions.operation_validator import RecallResult
from hindsight_api.models import RequestContext

from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.usage import (
    JSON_LIMIT,
    ObjectType,
    UsageCollector,
    observe_knowledge,
    record_knowledge,
    record_recall,
    usage_call,
)
from hindsight_ext_contextdb.usage_repository import UsageRepository, UsageTarget
from hindsight_ext_contextdb.validator import ContextDBOperationValidator

from .support.identities import ADMIN

UNIT_A, UNIT_B, UNIT_C = (str(UUID(int=value)) for value in (1, 2, 3))
TARGET = UsageTarget("a" * 32, "example", "ctxdb_ws_example")


def repository() -> Mock:
    return Mock(spec=UsageRepository, write=AsyncMock(return_value=True), cleanup=AsyncMock())


@pytest.mark.parametrize(
    "internal,operation,success,has_result,active,expected",
    [
        pytest.param(False, "memory", True, True, True, 2, id="direct-recall"),
        pytest.param(True, "memory", True, True, True, 1, id="internal-with-live-parent"),
        pytest.param(True, None, True, True, True, 1, id="worker-without-direct-call"),
        pytest.param(False, None, True, True, True, 1, id="reflect-or-refresh-parent"),
        pytest.param(False, "memory", True, True, False, 1, id="expired-parent"),
        pytest.param(False, "memory", False, True, True, 1, id="failed-recall"),
        pytest.param(False, "memory", True, False, True, 1, id="missing-result"),
    ],
)
async def test_recall_hook_counts_only_successful_direct_external_hits(
    configured: Settings,
    internal: bool,
    operation: ObjectType | None,
    success: bool,
    has_result: bool,
    active: bool,
    expected: int,
) -> None:
    collector = UsageCollector(repository())
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)
    collector.record(TARGET, "memory", [UNIT_A])
    before = dict(collector.pending)
    completed = RecallResult(
        bank_id=TARGET.bank_id,
        query="UsageSentinel",
        request_context=RequestContext(internal=internal),
        budget=None,
        max_tokens=100,
        enable_trace=False,
        fact_types=["world"],
        question_date=None,
        include_entities=False,
        max_entity_tokens=0,
        include_chunks=False,
        max_chunk_tokens=0,
        success=success,
        result=RecallPayload(results=[MemoryFact(id=UNIT_A, text="UsageSentinel", fact_type="world")])
        if has_result
        else None,
    )
    validator = ContextDBOperationValidator({})
    with usage_call(engine, principal, TARGET.bank_id, operation) as call:
        assert call is not None
        call.active = active
        await validator.on_recall_complete(completed)
    assert next(iter(collector.pending.values())).count == expected
    if expected == 1:
        # Exclusion must preserve the old timestamp as well as the count.
        assert collector.pending == before


async def test_aggregation_deduplicates_per_call_but_counts_new_requests() -> None:
    repo = repository()
    collector = UsageCollector(repo)
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)
    unit = str(uuid4())
    for _ in range(3):
        with usage_call(engine, principal, TARGET.bank_id, "memory"):
            record_recall(TARGET.bank_id, [unit, unit])
            record_recall(TARGET.bank_id, [unit])
    with usage_call(engine, principal, TARGET.bank_id, None):
        record_recall(TARGET.bank_id, [unit])
    await collector.flush()
    repo.write.assert_awaited_once()
    assert repo.write.call_args.args[0] == TARGET
    entry = repo.write.call_args.args[1][0]
    assert entry.count == 3 and entry.object_id == unit and entry.last_recalled_at.tzinfo is not None


async def test_inherited_context_expires_and_cannot_cross_bank() -> None:
    collector = UsageCollector(repository())
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)
    gate = asyncio.Event()

    async def inherited() -> None:
        await gate.wait()
        record_recall(TARGET.bank_id, [str(uuid4())])

    with usage_call(engine, principal, TARGET.bank_id, "memory"):
        task = asyncio.create_task(inherited())
        record_recall("another", [str(uuid4())])
    gate.set()
    await task
    assert not collector.pending


async def test_capacity_includes_inflight_and_keeps_new_events_during_write() -> None:
    repo = repository()
    collector = UsageCollector(repo, capacity=2)
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def write(*args) -> bool:
        entered.set()
        await gate.wait()
        return True

    repo.write.side_effect = write
    collector.record(TARGET, "memory", [UNIT_A, UNIT_B])
    first = asyncio.create_task(collector.flush())
    await entered.wait()
    collector.record(TARGET, "memory", [UNIT_A, UNIT_C])
    assert len(collector.occupied) == 2 and collector.metrics.dropped == 1
    gate.set()
    await first
    assert len(collector.pending) == 1
    await collector.flush()
    assert [sum(item.count for item in call.args[1]) for call in repo.write.call_args_list] == [2, 1]
    assert not collector.occupied
    assert collector.oldest_event_seconds() == 0


@pytest.mark.parametrize("error", [TimeoutError(), ConnectionError(), ValueError()])
async def test_failed_batch_is_never_replayed(error: Exception) -> None:
    repo = repository()
    repo.write.side_effect = error
    collector = UsageCollector(repo)
    collector.record(TARGET, "memory", [UNIT_A])
    await collector.flush()
    await collector.flush()
    repo.write.assert_awaited_once()
    assert not collector.pending and not collector.occupied
    assert collector.metrics.uncertain + collector.metrics.dropped == 1
    assert collector.metrics.uncertain == (0 if isinstance(error, ValueError) else 1)
    assert collector.cooldown_until > collector.loop.time()
    await collector.close()


async def test_batches_are_bounded_and_keep_workspace_identity() -> None:
    repo = repository()
    collector = UsageCollector(repo, batch_size=2)
    other = UsageTarget("b" * 32, "other", "ctxdb_ws_other")
    collector.record(TARGET, "memory", [UNIT_A, UNIT_B, UNIT_C])
    collector.record(other, "memory", [UNIT_A])
    await collector.close()
    assert all(len(call.args[1]) <= 2 for call in repo.write.call_args_list)
    assert [call.args[0] for call in repo.write.call_args_list] == [TARGET, TARGET, other]
    assert collector.metrics.flushed == 4


@pytest.mark.parametrize("wrapped", [False, True])
async def test_knowledge_wrapping_and_errors(wrapped: bool) -> None:
    collector = UsageCollector(repository())
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)
    payload = '{"results":[{"id":"page"},{"id":"page"}]}'
    with usage_call(engine, principal, TARGET.bank_id, "knowledge_page") as call:
        record_knowledge(call, {"result": payload} if wrapped else payload)
        record_knowledge(call, {"error": "failure"})
        record_knowledge(call, b"x" * (JSON_LIMIT + 1))
    assert [entry.count for entry in collector.pending.values()] == [1]
    assert collector.metrics.parse_failures == 2


async def test_observer_is_bounded_identity_and_counts_before_send_failure() -> None:
    collector = UsageCollector(repository())
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)

    async def app(scope, receive, send):
        assert not any(key.lower() == b"accept-encoding" for key, _ in scope["headers"])
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b'{"results":[', "more_body": True})
        await send({"type": "http.response.body", "body": b'{"id":"page"}]}', "more_body": False})

    async def send(message):
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            raise ConnectionError("Disconnected after generation")

    with usage_call(engine, principal, TARGET.bank_id, "knowledge_page") as call:
        with pytest.raises(ConnectionError):
            await observe_knowledge(app, {"headers": [(b"accept-encoding", b"gzip")]}, AsyncMock(), send, call)
    assert collector.metrics.received == 1


async def test_background_lifecycle_flushes_and_closes_once() -> None:
    collector = UsageCollector(repository())
    collector.start()
    task = collector.task
    collector.start()
    assert task is collector.task
    collector.record(TARGET, "memory", [UNIT_A])
    await collector.close()
    assert task.done() and collector.closed
    assert collector.metrics.flushed == 1
    collector.record(TARGET, "memory", [UNIT_B])
    assert not collector.pending


@pytest.mark.parametrize("workspaces,objects", [(1, 2000), (10, 1)])
async def test_automatic_writer_drains_quiet_burst_and_small_spaces(workspaces: int, objects: int) -> None:
    repo = repository()
    collector = UsageCollector(repo)
    for index in range(workspaces):
        target = UsageTarget(f"{index + 1:032x}", f"space{index}", f"ctxdb_ws_space{index}")
        collector.record(target, "memory", [str(UUID(int=value + 1)) for value in range(objects)])
    collector.start()
    try:
        async with asyncio.timeout(1.8):
            while collector.metrics.flushed < workspaces * objects:
                await asyncio.sleep(0.01)
        assert not collector.pending
        assert collector.metrics.dropped == 0
    finally:
        await collector.close()


@pytest.mark.parametrize(
    "headers",
    [[(b"content-type", b"text/html")], [(b"content-type", b"application/json"), (b"content-encoding", b"gzip")]],
)
async def test_unexpected_success_encoding_is_observable_without_changing_response(headers) -> None:
    collector = UsageCollector(repository())
    engine = SimpleNamespace(_contextdb_usage=collector)
    principal = replace(ADMIN, workspace_id=TARGET.workspace_id, schema_name=TARGET.schema_name)
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": b"unchanged", "more_body": False})

    async def send(message):
        sent.append(message)

    with usage_call(engine, principal, TARGET.bank_id, "knowledge_page") as call:
        await observe_knowledge(app, {"headers": []}, AsyncMock(), send, call)
    assert sent[-1]["body"] == b"unchanged"
    assert collector.metrics.parse_failures == 1 and not collector.pending
