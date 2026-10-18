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
from hindsight_api.extensions.tenant import AuthenticationError
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings, repository_for
from .diagnostics import business_operation_json
from .models import ServiceError

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository

logger = logging.getLogger(__name__)


_BOOL_QUERY = TypeAdapter(bool)


def _include_payload(scope: Scope) -> bool:
    """Match native FastAPI/Pydantic bool decoding without last-value ambiguity."""
    values = QueryParams(scope.get("query_string", b"")).getlist("include_payload")
    if len(values) > 1:
        raise ServiceError(400, "invalid_query", "include_payload must occur at most once")
    if not values:
        return False
    try:
        return _BOOL_QUERY.validate_python(values[0])
    except ValidationError:
        raise ServiceError(400, "invalid_query", "include_payload must be a valid boolean") from None


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


@dataclass
class MCPTransportLifetime:
    """Tie detached SDK handlers to one HTTP message without a Bank/PG lock."""

    owner: asyncio.Task[Any] | None = field(default=None, repr=False)
    tools: set[asyncio.Task[Any]] = field(default_factory=set, repr=False)
    active: bool = True
    failed: bool = False


@contextmanager
def restore_transport(lifetime: MCPTransportLifetime) -> Iterator[None]:
    if not lifetime.active:
        raise ServiceError(503, "transport_closed", "MCP HTTP request has ended")
    task = asyncio.current_task()
    registered = task is not None and task is not lifetime.owner and task not in lifetime.tools
    if registered:
        lifetime.tools.add(task)
    try:
        yield
    finally:
        if registered:
            lifetime.tools.discard(task)


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


async def _cancel_and_drain_tools(request: AdmittedRequest | MCPTransportLifetime) -> None:
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
    async def enter(self, credential: str, bank_id: str) -> AsyncIterator[AdmittedRequest]:
        repository = await repository_for(self.memory, self.settings)
        principal = await repository.authenticate(credential, bank_id)
        assert principal.workspace_id is not None and principal.schema_name is not None
        if self.pool is None:
            raise ServiceError(503, "admission_unavailable", "Workspace admission is unavailable")
        from .repository import Repository

        metadata = Repository(
            self.pool,
            self.settings.instance_id,
            self.settings.cloud_tenant_id,
            self.settings.pepper,
            operation_retention_hours=self.settings.operation_retention_hours,
        )
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
                # A missing/filtered MCP tool may raise before any engine gate.
                # Such a protocol rejection cannot leave an unknown writer;
                # actual engine work is marked by the trusted validator gate.
                ticket.work_started = request.engine_started if request is not None else False
                ticket.failed = request.failed if request is not None else False

    @asynccontextmanager
    async def _locked_request(
        self, conn: asyncpg.Connection, workspace_id: str, schema: str, key_id: str
    ) -> AsyncIterator[AdmittedRequest]:
        from .repository import Repository

        await Repository._verify_binding(conn, self.settings.instance_id, self.settings.cloud_tenant_id)
        row = await conn.fetchrow(
            "SELECT state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 FOR KEY SHARE",
            workspace_id,
            schema,
        )
        if row is None or row["state"] != "active":
            raise ServiceError(401, "invalid_key", "Workspace no longer admits customer operations")
        bank_id = await conn.fetchval("SELECT bank_id FROM ctxdb_meta.workspaces WHERE workspace_id=$1", workspace_id)
        request = AdmittedRequest(schema, bank_id, key_id, owner=asyncio.current_task())
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
    """Route native REST before alias lookup; MCP acquires per-tool admission."""

    def __init__(self, app: ASGIApp, guard: AdmissionGuard) -> None:
        self.app = app
        self.guard = guard

    async def _business_status(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only the native JSON task status/list endpoints are buffered, never
        # Retain bodies, MCP/SSE streams, or arbitrary customer responses.
        start: Message | None = None
        chunks = bytearray()

        async def capture(message: Message) -> None:
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                chunks.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    assert start is not None
                    headers = list(start.get("headers", []))
                    if 200 <= start["status"] < 300:
                        if not any(
                            k.lower() == b"content-type" and b"application/json" in v.lower() for k, v in headers
                        ):
                            raise ServiceError(503, "invalid_diagnostics", "Task status response unavailable")
                        try:
                            body = business_operation_json(bytes(chunks)).encode()
                        except ValueError:
                            raise ServiceError(503, "invalid_diagnostics", "Task status response unavailable") from None
                        headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                        headers.append((b"content-length", str(len(body)).encode()))
                    else:
                        body = bytes(chunks)
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})

        # Native GZip middleware sits inside extension middleware. Request an
        # identity response for these small buffered diagnostics so projection
        # happens before any compression, rather than parsing compressed bytes.
        identity_scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() != b"accept-encoding"]}
        await self.app(identity_scope, receive, capture)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith("/ext/contextdb/"):
            await self.app(scope, receive, send)
            return
        import re

        from .routing import bank_list, bank_target
        from .security import bearer_credential

        path = scope["path"]
        if path == "/mcp" or path.startswith("/mcp/"):
            # Do not hold a workspace lock across an MCP event stream. Tool
            # middleware resolves the actual Bank and owns its durable admission.
            tail = path[len("/mcp/") :].split("/", 1)[0] if path.startswith("/mcp/") else ""
            if tail:
                scope["contextdb.mcp_path_bank"] = tail
            lifetime = MCPTransportLifetime(owner=asyncio.current_task())
            # The native identity adapter invokes this trusted factory in the
            # session task for EACH current message. A plain pass-through loses
            # the HTTP owner and leaves a detached tool running after an abort.
            scope["hindsight.request_context_restore"] = lambda: restore_transport(lifetime)
            try:
                await self.app(scope, receive, send)
            finally:
                lifetime.active = False
                await _cancel_and_drain_tools(lifetime)
            return
        download_prefix = "/v1/default/files/download/"
        if not (
            path == "/v1/default/banks" or path.startswith("/v1/default/banks/") or path.startswith(download_prefix)
        ):
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
            credential = bearer_credential(scope["headers"])
            if path == "/v1/default/banks":
                if scope["method"] != "GET":
                    raise ServiceError(
                        403, "workspace_lifecycle", "Use the workspace management API for lifecycle operations"
                    )
                from urllib.parse import parse_qs

                params = parse_qs(scope.get("query_string", b"").decode("ascii"))
                try:
                    limit, offset = int(params.get("limit", ["100"])[0]), int(params.get("offset", ["0"])[0])
                except ValueError:
                    raise ServiceError(400, "invalid_pagination", "Invalid pagination") from None
                repository = await repository_for(self.guard.memory, self.guard.settings)
                page = await bank_list(
                    self.guard.memory,
                    repository,
                    credential,
                    query=params.get("q", [None])[0],
                    limit=limit,
                    offset=offset,
                )
                await JSONResponse(page.model_dump(mode="json"))(scope, receive, send)
                return
            if path.startswith(download_prefix):
                parts = path[len(download_prefix) :].split("/")
                if len(parts) > 4 and parts[0] == "tenants" and parts[2] == "banks" and ".." not in parts:
                    bank_id = parts[3]
                elif len(parts) > 2 and parts[0] == "banks" and ".." not in parts:
                    bank_id = parts[1]
                else:
                    raise ServiceError(404, "not_found", "File not found")
            else:
                bank_id = path[len("/v1/default/banks/") :].split("/", 1)[0]
            if not re.fullmatch("[a-z0-9][a-z0-9_]{0,53}", bank_id):
                raise ServiceError(403, "invalid_bank", "Use a registered canonical Bank ID")
            clearing = scope["method"] == "DELETE" and path == f"/v1/default/banks/{bank_id}/memories"
            with bank_target(bank_id, clear_memories=clearing):
                async with self.guard.enter(credential or "", bank_id) as admitted:
                    suffix = path[len(f"/v1/default/banks/{bank_id}") :]
                    if (scope["method"] == "POST" and suffix in {"/import", "/clone", "/transfer/import"}) or (
                        scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}
                        and (suffix == "/aliases" or suffix.startswith("/aliases/"))
                    ):
                        # Refuse unsupported lifecycle combinations before body
                        # parsing/archive IO. Document imports retain their own
                        # memory.write gate; they cannot create another Bank.
                        raise ServiceError(
                            403, "workspace_lifecycle", "Use the workspace management API for lifecycle operations"
                        )
                    payload_requested = (
                        scope["method"] == "GET"
                        and re.fullmatch(r"/operations/[^/]+/?", suffix) is not None
                        and _include_payload(scope)
                    )
                    if (
                        payload_requested
                        or suffix.rstrip("/") in {"/audit-logs", "/audit-logs/stats"}
                        or path.startswith(download_prefix)
                        or suffix
                        in {
                            "/export",
                            "/transfer/export",
                            "/document-transfer/export",
                        }
                    ):
                        # Native archives may carry webhook signing secrets and
                        # delivery headers. Treat archive export/download as an
                        # operator feature; business reads still access documents.
                        repository = await repository_for(self.guard.memory, self.guard.settings)
                        await repository.authenticate_admin(credential)
                    scope["contextdb.admission"] = admitted
                    scope["hindsight.request_context_restore"] = lambda: restore_admission(admitted)

                    def report_failure() -> None:
                        assert admitted is not None
                        admitted.failed = True

                    scope["hindsight.request_context_failure"] = report_failure
                    if scope["method"] == "GET" and re.fullmatch(r"/operations(?:/[^/]+)?/?", suffix):
                        repository = await repository_for(self.guard.memory, self.guard.settings)
                        principal = await repository.authenticate(credential, bank_id)
                        if principal.role.value != "admin":
                            await self._business_status(scope, receive, observed_send)
                            return
                    await self.app(scope, receive, observed_send)
        except ServiceError as error:
            if started:
                raise
            await JSONResponse({"detail": error.message}, status_code=error.status)(scope, receive, send)
        except AuthenticationError as error:
            if started:
                raise
            await JSONResponse({"detail": error.reason}, status_code=401)(scope, receive, send)
        except (asyncpg.PostgresError, OSError, asyncio.TimeoutError):
            if started:
                raise
            await JSONResponse({"detail": "Workspace admission is unavailable"}, status_code=503)(scope, receive, send)
