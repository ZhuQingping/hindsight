"""Cross-replica drain using PG locks plus committed request-admission records.

Each authenticated HTTP operation holds a key-share workspace lock until its ASGI
response finishes (including cancellation). Freeze/delete use FOR UPDATE;
freeze/delete cannot close admission until these operations leave. A small,
separate metadata pool avoids starving the engine pool with held connections.
MCP GET event streams do not execute tools and are deliberately not held open;
tool-executing POST requests are guarded just like REST requests.
Durable records also block cleanup after a lost session or executor crash;
unknown/interrupted work is never reclaimed solely because time passed.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
import secrets
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import asyncpg
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings, repository_for
from .models import ServiceError

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository

logger = logging.getLogger(__name__)


@dataclass
class AdmittedRequest:
    schema: str
    bank_id: str
    key_id: str | None = None
    active: bool = True
    failed: bool = False
    engine_started: bool = False
    owner: asyncio.Task[Any] | None = field(default=None, repr=False)
    tools: set[asyncio.Task[Any]] = field(default_factory=set, repr=False)


@dataclass(repr=False)
class BankInitialization:
    schema: str
    bank_id: str
    operation_id: str
    lease_token: str
    active: bool = True


@dataclass
class AdmissionTicket:
    work_started: bool = False
    failed: bool = False


@asynccontextmanager
async def durable_admission(
    repository: Repository, workspace_id: str, schema: str, origin: str, owner_id: str
) -> AsyncIterator[AdmissionTicket]:
    """Keep a durable cleanup barrier across a lost PG session or process crash.

    Normal work removes the committed record. After work starts, an exception
    retains it: cancellation alone cannot prove every old database writer has
    stopped. No timer or new API automatically declares such work safe to purge.
    """
    admission_id = secrets.token_hex(16)
    await repository.register_admission(admission_id, owner_id, workspace_id, schema, origin)
    ticket = AdmissionTicket()
    interrupted = False
    try:
        yield ticket
    except BaseException:
        interrupted = ticket.work_started
        raise
    finally:
        interrupted = interrupted or (ticket.work_started and ticket.failed)
        finishing = asyncio.create_task(repository.finish_admission(admission_id, owner_id, interrupted=interrupted))
        cancelled: asyncio.CancelledError | None = None
        while not finishing.done():
            try:
                await asyncio.shield(finishing)
            except asyncio.CancelledError as error:
                cancelled = error
            except Exception:
                break
        try:
            finishing.result()
        except Exception:
            # A failed cleanup leaves a conservative durable barrier. Do not
            # expose PG errors/DSNs or falsely infer the record was removed.
            logger.warning("ContextDB admission recovery record retained")
        if cancelled is not None:
            raise cancelled


_admitted: contextvars.ContextVar[AdmittedRequest | None] = contextvars.ContextVar("ctxdb_admission", default=None)
_initializing: contextvars.ContextVar[BankInitialization | None] = contextvars.ContextVar(
    "ctxdb_initializing", default=None
)


def is_admitted(schema: str, bank_id: str) -> bool:
    request = _admitted.get()
    return bool(request and request.active and request.schema == schema and request.bank_id == bank_id)


def mark_engine_started() -> None:
    """A successful engine policy gate distinguishes execution from bad MCP args."""
    request = _admitted.get()
    if request is not None and request.active:
        request.engine_started = True


def bank_initialization(schema: str, bank_id: str) -> BankInitialization | None:
    request = _initializing.get()
    return request if request and request.active and request.schema == schema and request.bank_id == bank_id else None


@contextmanager
def restore_admission(request: AdmittedRequest) -> Iterator[None]:
    """Restore the current MCP message's trusted HTTP admission, not its session's.

    Only the owning HTTP guard may end this admission. Restoring a tool context
    does not acquire, extend or release the database lock.
    """
    if not request.active:
        raise ServiceError(503, "admission_lost", "Workspace admission has ended")
    task = asyncio.current_task()
    registered = task is not None and task is not request.owner and task not in request.tools
    if registered:
        request.tools.add(task)
    token = _admitted.set(request)
    try:
        yield
    except asyncio.CancelledError:
        request.failed = True
        raise
    except Exception:
        # FastMCP may fail result validation after the engine returned. Such
        # failures bypass native tools' error wrappers. Input/tool-discovery
        # rejection before an engine gate has no unknown native writer.
        request.failed = request.failed or request.engine_started
        raise
    finally:
        _admitted.reset(token)
        if registered:
            request.tools.discard(task)


async def _cancel_and_drain_tools(request: AdmittedRequest) -> None:
    """Do not release an HTTP lock while a detached MCP handler is still running."""
    tasks = [task for task in request.tools if not task.done() and task is not asyncio.current_task()]
    if not tasks:
        return
    request.failed = True
    for task in tasks:
        task.cancel("Owning workspace admission ended")
    drain = asyncio.gather(*tasks, return_exceptions=True)
    interrupted: asyncio.CancelledError | None = None
    while not drain.done():
        try:
            # A second HTTP cancellation must not abandon cleanup and release
            # the PG lock while the cancelled tool is rolling back its work.
            await asyncio.shield(drain)
        except asyncio.CancelledError as error:
            interrupted = error
    if interrupted is not None:
        raise interrupted


@asynccontextmanager
async def protected_transaction(pool: asyncpg.Pool) -> AsyncIterator[asyncpg.Connection]:
    """Cancel downstream work if PG drops the connection holding its admission.

    A lost lock cannot protect either an HTTP operation or a queue insertion.
    Ordinary caller cancellation is preserved; connection loss fails closed.
    """
    lost = False
    task = asyncio.current_task()
    assert task is not None

    def terminated(connection: asyncpg.Connection) -> None:
        nonlocal lost
        lost = True
        task.cancel("Workspace admission connection lost")

    try:
        async with pool.acquire(timeout=30) as connection:
            connection.add_termination_listener(terminated)
            try:
                async with connection.transaction():
                    yield connection
            finally:
                if not connection.is_closed():
                    connection.remove_termination_listener(terminated)
    except (asyncio.CancelledError, asyncpg.InterfaceError):
        if lost:
            raise ServiceError(503, "admission_lost", "Workspace admission was interrupted") from None
        raise


@contextmanager
def initializing_bank(schema: str, bank_id: str, operation_id: str, lease_token: str) -> Iterator[None]:
    """Only lifecycle may admit a default template's initial queue submissions.

    This is local execution state, not a client header or a reusable credential.
    Creating workspaces are invisible to workers until provisioning completes.
    """
    request = BankInitialization(schema, bank_id, operation_id, lease_token)
    token = _initializing.set(request)
    try:
        yield
    finally:
        request.active = False
        _initializing.reset(token)


class AdmissionGuard:
    def __init__(self, memory: MemoryEngine, settings: Settings) -> None:
        self.memory = memory
        self.settings = settings
        self.pool: asyncpg.Pool | None = None
        self.owner_id = secrets.token_hex(16)

    async def start(self) -> None:
        # This pool holds only metadata locks; native work always uses its own
        # pool. Sharing the latter can deadlock when every slot holds admission
        # and the admitted operations themselves need another connection.
        self.pool = await asyncpg.create_pool(
            self.memory.db_url, min_size=0, max_size=10, server_settings={"application_name": "contextdb_admission"}
        )

    async def stop(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    @asynccontextmanager
    async def enter(self, credential: str) -> AsyncIterator[AdmittedRequest]:
        repository = await repository_for(self.memory, self.settings)
        principal = await repository.authenticate(credential)
        if self.pool is None:
            raise ServiceError(503, "admission_unavailable", "Workspace admission is unavailable")
        from .repository import Repository

        metadata = Repository(self.pool, self.settings.instance_id, self.settings.cloud_tenant_id, self.settings.pepper)
        async with durable_admission(
            metadata, principal.workspace_id, principal.schema_name, "http", self.owner_id
        ) as ticket:
            request: AdmittedRequest | None = None
            try:
                async with protected_transaction(self.pool) as conn:
                    async with self._locked_request(
                        conn, principal.workspace_id, principal.schema_name, principal.key_id
                    ) as request:
                        ticket.work_started = True
                        yield request
            finally:
                ticket.failed = request.failed if request is not None else False

    @asynccontextmanager
    async def _locked_request(
        self, conn: asyncpg.Connection, workspace_id: str, schema: str, key_id: str
    ) -> AsyncIterator[AdmittedRequest]:
        row = await conn.fetchrow(
            "SELECT state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 "
            "AND instance_id=$3 AND cloud_tenant_id=$4 FOR KEY SHARE",
            workspace_id,
            schema,
            self.settings.instance_id,
            self.settings.cloud_tenant_id,
        )
        if row is None or row["state"] != "active":
            raise ServiceError(401, "invalid_key", "Workspace no longer admits customer operations")
        request = AdmittedRequest(schema, workspace_id, key_id, owner=asyncio.current_task())
        token = _admitted.set(request)
        try:
            yield request
        finally:
            # Child tasks inherit ContextVars; they cannot reuse a lock after
            # the owning HTTP request has finished and released it.
            request.active = False
            try:
                await _cancel_and_drain_tools(request)
            finally:
                _admitted.reset(token)


class WorkspaceAdmissionMiddleware:
    def __init__(self, app: ASGIApp, guard: AdmissionGuard) -> None:
        self.app = app
        self.guard = guard

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["path"].startswith("/ext/contextdb/")
            or (scope["method"] == "GET" and scope["path"].startswith("/mcp"))
        ):
            await self.app(scope, receive, send)
            return
        authorizations = [value for name, value in scope["headers"] if name.lower() == b"authorization"]
        if len(authorizations) > 1:
            await JSONResponse({"detail": "Ambiguous authorization"}, status_code=401)(scope, receive, send)
            return
        header = authorizations[0].decode("latin-1") if authorizations else ""
        # Native REST and MCP both accept a direct Key and strip surrounding
        # whitespace. Admission must use exactly the same credential syntax.
        credential = (header[7:] if header.lower().startswith("bearer ") else header).strip()
        if not credential.startswith("ctx_live_"):
            # Native authentication still rejects missing/invalid business Keys.
            # Control routes use a different header and must never acquire this
            # shared lock while attempting their own exclusive workspace lock.
            await self.app(scope, receive, send)
            return
        started = False
        admitted: AdmittedRequest | None = None

        async def observed_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if message["status"] >= 500 and admitted is not None:
                    admitted.failed = True
            await send(message)

        try:
            async with self.guard.enter(credential) as admitted:
                scope["contextdb.admission"] = admitted
                # The native MCP adapter invokes this trusted scope factory for
                # each message. Headers cannot inject an ASGI scope object.
                scope["hindsight.request_context_restore"] = lambda: restore_admission(admitted)

                def report_failure() -> None:
                    admitted.failed = True

                scope["hindsight.request_context_failure"] = report_failure
                await self.app(scope, receive, observed_send)
        except ServiceError as error:
            if started:
                raise
            await JSONResponse({"detail": error.message}, status_code=error.status)(scope, receive, send)
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError):
            if started:
                raise
            await JSONResponse({"detail": "Workspace admission is unavailable"}, status_code=503)(scope, receive, send)
