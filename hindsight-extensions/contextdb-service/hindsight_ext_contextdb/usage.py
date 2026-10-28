"""Best-effort recall usage: one loop-owned, bounded collector per API engine."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, Field, ValidationError
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .models import BusinessPrincipal
from .usage_repository import UsageDelta, UsageRepository, UsageTarget

logger = logging.getLogger(__name__)
ObjectType = Literal["memory", "knowledge_page"]
JSON_LIMIT = 512 * 1024


@dataclass(frozen=True)
class UsageKey:
    target: UsageTarget
    object_type: ObjectType
    object_id: str


@dataclass
class UsageMetrics:
    received: int = 0
    dropped: int = 0
    uncertain: int = 0
    stale: int = 0
    flushed: int = 0
    failed_batches: int = 0
    cleanup_failures: int = 0
    parse_failures: int = 0


@dataclass
class UsageCall:
    collector: UsageCollector
    target: UsageTarget
    operation: ObjectType | None
    active: bool = True
    seen: set[str] = field(default_factory=set)

    def record(self, object_type: ObjectType, ids: Iterable[str]) -> None:
        if not self.active or self.operation != object_type:
            return
        # Child tasks inherit this object. The root call invalidates it on exit;
        # no inherited context can record later background work as a direct call.
        fresh = set(ids) - self.seen
        self.seen.update(fresh)
        self.collector.record(self.target, object_type, fresh)


_call: ContextVar[UsageCall | None] = ContextVar("contextdb_usage_call", default=None)


def collector_for(memory: object) -> UsageCollector | None:
    value = getattr(memory, "_contextdb_usage", None)
    return value if isinstance(value, UsageCollector) else None


@contextmanager
def usage_call(
    memory: object, principal: BusinessPrincipal, bank_id: str, operation: ObjectType | None
) -> Iterator[UsageCall | None]:
    collector = collector_for(memory)
    call = None
    if collector is not None and principal.workspace_id is not None and principal.schema_name is not None:
        call = UsageCall(collector, UsageTarget(principal.workspace_id, bank_id, principal.schema_name), operation)
    token = _call.set(call)
    try:
        yield call
    finally:
        if call is not None:
            call.active = False
        _call.reset(token)


def record_recall(bank_id: str, ids: Iterable[str]) -> None:
    call = _call.get()
    if call is not None and call.target.bank_id == bank_id:
        call.record("memory", (str(UUID(value)) for value in ids))


class KnowledgeHit(BaseModel):
    id: str = Field(min_length=1, max_length=64)


class KnowledgeResult(BaseModel):
    results: list[KnowledgeHit] = Field(max_length=50)
    error: object | None = None


class WrappedKnowledgeResult(BaseModel):
    result: str


def record_knowledge(call: UsageCall | None, payload: object) -> None:
    if call is None:
        return
    try:
        if isinstance(payload, bytes | str):
            if len(payload) > JSON_LIMIT:
                raise ValueError("Usage response too large")
            result = KnowledgeResult.model_validate_json(payload)
        else:
            # Root MCP registration wraps its JSON string under `result`;
            # single-bank registration returns the native object directly.
            try:
                result = KnowledgeResult.model_validate(payload)
            except ValidationError:
                wrapped = WrappedKnowledgeResult.model_validate(payload)
                if len(wrapped.result) > JSON_LIMIT:
                    raise ValueError("Usage response too large")
                result = KnowledgeResult.model_validate_json(wrapped.result)
        if result.error is not None:
            raise ValueError("Knowledge search failed")
        call.record("knowledge_page", (hit.id for hit in result.results))
    except (ValueError, TypeError):
        call.collector.metrics.parse_failures += 1


async def observe_knowledge(app: ASGIApp, scope: Scope, receive: Receive, send: Send, call: UsageCall | None) -> None:
    """Observe only bounded identity JSON, without replacing a business response."""
    if call is None:
        await app(scope, receive, send)
        return
    chunks = bytearray()
    valid = False

    async def observe(message: Message) -> None:
        nonlocal valid
        if message["type"] == "http.response.start":
            headers = {key.lower(): value.lower() for key, value in message.get("headers", [])}
            valid = (
                message["status"] == 200
                and b"application/json" in headers.get(b"content-type", b"")
                and headers.get(b"content-encoding", b"identity") == b"identity"
            )
            if message["status"] == 200 and not valid and call is not None:
                call.collector.metrics.parse_failures += 1
        elif message["type"] == "http.response.body" and valid:
            block = message.get("body", b"")
            if len(chunks) + len(block) > JSON_LIMIT:
                valid = False
                chunks.clear()
                if call is not None:
                    call.collector.metrics.parse_failures += 1
            else:
                chunks.extend(block)
                if not message.get("more_body", False):
                    # Generation, not delivery, is the metric: a subsequent send
                    # failure does not undo a result already observed here.
                    record_knowledge(call, bytes(chunks))
        await send(message)

    identity_scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() != b"accept-encoding"]}
    await app(identity_scope, receive, observe)


class UsageCollector:
    def __init__(self, repository: UsageRepository, *, capacity: int = 10_000, batch_size: int = 500) -> None:
        self.repository = repository
        self.capacity = capacity
        self.batch_size = batch_size
        self.metrics = UsageMetrics()
        self.loop = asyncio.get_running_loop()
        self.pending: dict[UsageKey, UsageDelta] = {}
        self.occupied: set[UsageKey] = set()
        self.inflight: set[UsageKey] = set()
        self.pending_since: dict[UsageKey, float] = {}
        self.inflight_since: dict[UsageKey, float] = {}
        self.wake = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.closed = False
        self.cooldown_until = 0.0
        self.failures = 0

    def start(self) -> None:
        if self.task is None:
            self.task = self.loop.create_task(self._run(), name="contextdb-usage")

    def record(self, target: UsageTarget, object_type: ObjectType, ids: Iterable[str]) -> None:
        if self.closed or asyncio.get_running_loop() is not self.loop:
            return
        now = datetime.now(timezone.utc)
        # No await or PG operation on this path. All containers belong to this
        # event loop, including in-flight keys during the writer's await.
        for object_id in set(ids):
            self.metrics.received += 1
            key = UsageKey(target, object_type, object_id)
            previous = self.pending.get(key)
            if key not in self.occupied and len(self.occupied) >= self.capacity:
                self.metrics.dropped += 1
                continue
            self.occupied.add(key)
            if previous is None:
                self.pending_since[key] = self.loop.time()
            self.pending[key] = (
                replace(previous, count=previous.count + 1, last_recalled_at=max(previous.last_recalled_at, now))
                if previous is not None
                else UsageDelta(object_type, object_id, 1, now)
            )
        if len(self.pending) >= self.batch_size and self.loop.time() >= self.cooldown_until:
            self.wake.set()

    async def flush(self) -> None:
        if not self.pending:
            return
        target = next(iter(self.pending)).target
        keys: list[UsageKey] = []
        for key in self.pending:
            if key.target == target:
                keys.append(key)
                if len(keys) == self.batch_size:
                    break
        await self._flush_keys(keys)

    async def _flush_keys(self, keys: list[UsageKey]) -> None:
        target = keys[0].target
        entries = [self.pending.pop(key) for key in keys]
        self.inflight_since.update({key: self.pending_since.pop(key) for key in keys})
        self.inflight.update(keys)
        count = sum(entry.count for entry in entries)
        try:
            async with asyncio.timeout(1):
                written = await self.repository.write(target, entries)
            if written:
                self.metrics.flushed += count
            else:
                self.metrics.stale += count
            self.failures = 0
            self.cooldown_until = 0
        except asyncio.CancelledError:
            self.metrics.uncertain += count
            raise
        except Exception as error:
            # Never replay an increment: a lost commit acknowledgement cannot
            # be distinguished from a failed write without durable receipts.
            self.metrics.failed_batches += 1
            if isinstance(error, ValueError) or (
                isinstance(error, asyncpg.PostgresError) and not str(getattr(error, "sqlstate", "")).startswith("08")
            ):
                self.metrics.dropped += count
            else:
                self.metrics.uncertain += count
            self.failures += 1
            self.cooldown_until = self.loop.time() + min(30, 2 ** min(self.failures, 5))
            if self.failures == 1:
                logger.warning("ContextDB usage batch discarded; error_type=%s", type(error).__name__)
        finally:
            self.inflight.difference_update(keys)
            for key in keys:
                self.inflight_since.pop(key, None)
                if key not in self.pending:
                    self.occupied.discard(key)

    def oldest_event_seconds(self) -> float:
        if not self.pending_since and not self.inflight_since:
            return 0.0
        oldest = min(
            min(self.pending_since.values(), default=self.loop.time()),
            min(self.inflight_since.values(), default=self.loop.time()),
        )
        return max(0.0, self.loop.time() - oldest)

    async def _flush_round(self) -> None:
        # Freeze at most capacity keys, so new arrivals cannot extend this round
        # indefinitely. Continue small-space/full batches without another 1s
        # sleep; otherwise a quiet burst's last batch waits tens of seconds.
        targets: dict[UsageTarget, list[UsageKey]] = {}
        for key in self.pending:
            targets.setdefault(key.target, []).append(key)
        for keys in targets.values():
            for offset in range(0, len(keys), self.batch_size):
                if self.loop.time() < self.cooldown_until:
                    return
                await self._flush_keys(keys[offset : offset + self.batch_size])
                await asyncio.sleep(0)

    async def _run(self) -> None:
        next_flush = self.loop.time() + 1
        next_cleanup = self.loop.time() + 10 + random.uniform(0, 3)
        next_report = self.loop.time() + 60
        while True:
            self.wake.clear()
            now = self.loop.time()
            if now >= self.cooldown_until:
                if self.pending and (now >= next_flush or len(self.pending) >= self.batch_size):
                    await self._flush_round()
                    next_flush = self.loop.time() + 1
                if self.loop.time() >= next_cleanup and len(self.pending) < self.batch_size:
                    try:
                        async with asyncio.timeout(1):
                            await self.repository.cleanup()
                    except Exception as error:
                        self.metrics.cleanup_failures += 1
                        logger.debug("ContextDB usage cleanup deferred; error_type=%s", type(error).__name__)
                    next_cleanup = self.loop.time() + 10 + random.uniform(0, 3)
            if not self.pending:
                next_flush = self.loop.time() + 1
            if self.loop.time() >= next_report:
                logger.info(
                    "ContextDB usage; pending_objects=%d oldest_event_seconds=%.3f last_sweep_completed=%s metrics=%s",
                    len(self.occupied),
                    self.oldest_event_seconds(),
                    self.repository.last_sweep_completed,
                    self.metrics,
                )
                next_report = self.loop.time() + 60
            with suppress(TimeoutError):
                await asyncio.wait_for(self.wake.wait(), timeout=max(0.05, min(1, next_flush - self.loop.time())))

    async def close(self) -> None:
        self.closed = True
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        try:
            async with asyncio.timeout(5):
                while self.pending:
                    if self.loop.time() < self.cooldown_until:
                        break
                    await self.flush()
        except TimeoutError:
            pass
        self.metrics.dropped += sum(entry.count for entry in self.pending.values())
        self.pending.clear()
        self.pending_since.clear()
        self.inflight_since.clear()
        self.occupied.clear()
        logger.info("ContextDB usage collector stopped; metrics=%s", self.metrics)
