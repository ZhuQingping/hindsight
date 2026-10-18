"""Native HTTP routing and diagnostic policy, without execution registration."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import TYPE_CHECKING
from urllib.parse import parse_qs

import asyncpg
from hindsight_api.engine.chunk_ids import build_chunk_id, parse_chunk_id
from hindsight_api.extensions.tenant import AuthenticationError
from pydantic import TypeAdapter, ValidationError
from starlette.datastructures import QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .authorization import authenticated_request
from .config import Settings, repository_for
from .diagnostics import business_operation_json
from .models import Role, ServiceError
from .routing import bank_list, bank_target
from .security import bearer_credential

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

_BOOL_QUERY = TypeAdapter(bool)


def _include_payload(scope: Scope) -> bool:
    values = QueryParams(scope.get("query_string", b"")).getlist("include_payload")
    if len(values) > 1:
        raise ServiceError(400, "invalid_query", "include_payload must occur at most once")
    if not values:
        return False
    try:
        return _BOOL_QUERY.validate_python(values[0])
    except ValidationError:
        raise ServiceError(400, "invalid_query", "include_payload must be a valid boolean") from None


def _bank_config_json(payload: bytes) -> str:
    # Reuse the host's public response schema, without importing its HTTP module
    # while extension slots are being constructed.
    from hindsight_api.api.http import BankConfigResponse

    state = BankConfigResponse.model_validate_json(payload)
    # Native config already applies public-field and caller permissions. Project
    # overrides onto the same keys at the plugin boundary, without another hook
    # call or changing native engine/storage behavior.
    state.overrides = {name: value for name, value in state.overrides.items() if name in state.config}
    return state.model_dump_json()


class WorkspaceAuthorizationMiddleware:
    """Resolve the canonical Bank before native alias/tenant routing.

    Protocol policy remains outside MCP mounting. No request holds a metadata
    transaction or waits for another executor to end.
    """

    def __init__(self, app: ASGIApp, memory: MemoryEngine, settings: Settings) -> None:
        self.app = app
        self.memory = memory
        self.settings = settings

    async def _project_json_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        project: Callable[[bytes], str],
        invalid_response: ServiceError,
    ) -> None:
        # Buffer only the explicitly selected JSON config/task endpoints, never
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
                            raise invalid_response
                        try:
                            body = project(bytes(chunks)).encode()
                        except ValueError:
                            raise invalid_response from None
                        headers = [(k, v) for k, v in headers if k.lower() != b"content-length"]
                        headers.append((b"content-length", str(len(body)).encode()))
                    else:
                        body = bytes(chunks)
                    await send({**start, "headers": headers})
                    await send({"type": "http.response.body", "body": body})

        # Native GZip middleware sits inside extension middleware. Request an
        # identity response for these small JSON responses so projection
        # happens before any compression, rather than parsing compressed bytes.
        identity_scope = {**scope, "headers": [(k, v) for k, v in scope["headers"] if k.lower() != b"accept-encoding"]}
        await self.app(identity_scope, receive, capture)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith("/ext/contextdb/"):
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        if path == "/mcp" or path.startswith("/mcp/"):
            # MCP resolves the current message's credential and actual tool Bank
            # in its public middleware, never from the initialization session.
            tail = path[len("/mcp/") :].split("/", 1)[0] if path.startswith("/mcp/") else ""
            if tail:
                scope["contextdb.mcp_path_bank"] = tail
            await self.app(scope, receive, send)
            return
        download_prefix = "/v1/default/files/download/"
        chunk_prefix = "/v1/default/chunks/"
        if not (
            path == "/v1/default/banks"
            or path.startswith("/v1/default/banks/")
            or path.startswith(download_prefix)
            or path.startswith(chunk_prefix)
        ):
            await self.app(scope, receive, send)
            return
        started = False

        async def observed_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            credential = bearer_credential(scope["headers"])
            repository = await repository_for(self.memory, self.settings)
            if path == "/v1/default/banks":
                if scope["method"] != "GET":
                    raise ServiceError(
                        403, "workspace_lifecycle", "Use the workspace management API for lifecycle operations"
                    )
                try:
                    params = parse_qs(scope.get("query_string", b"").decode("ascii"))
                    limit = int(params.get("limit", ["100"])[0])
                    offset = int(params.get("offset", ["0"])[0])
                except (ValueError, UnicodeError):
                    raise ServiceError(400, "invalid_pagination", "Invalid pagination") from None
                page = await bank_list(
                    self.memory, repository, credential, query=params.get("q", [None])[0], limit=limit, offset=offset
                )
                await JSONResponse(page.model_dump(mode="json"))(scope, receive, observed_send)
                return
            if path.startswith(chunk_prefix):
                # Chunks encode the Bank instead of carrying it as a path segment.
                # Use the native codec, but reject ambiguous pre-release encodings.
                chunk_id = path[len(chunk_prefix) :]
                chunk = parse_chunk_id(chunk_id)
                if (
                    chunk is None
                    or chunk.chunk_index < 0
                    or build_chunk_id(chunk.bank_id, chunk.document_id, chunk.chunk_index) != chunk_id
                ):
                    raise ServiceError(404, "not_found", "Chunk not found")
                bank_id = chunk.bank_id
            elif path.startswith(download_prefix):
                parts = path[len(download_prefix) :].split("/")
                if len(parts) > 4 and parts[0] == "tenants" and parts[2] == "banks" and ".." not in parts:
                    bank_id = parts[3]
                elif len(parts) > 2 and parts[0] == "banks" and ".." not in parts:
                    bank_id = parts[1]
                else:
                    raise ServiceError(404, "not_found", "File not found")
            else:
                bank_id = path[len("/v1/default/banks/") :].split("/", 1)[0]
            if not re.fullmatch(r"[a-z0-9][a-z0-9_]{0,53}", bank_id):
                raise ServiceError(403, "invalid_bank", "Use a registered canonical Bank ID")
            principal = await repository.authenticate(credential, bank_id, record_use=True)
            assert credential is not None
            clearing = scope["method"] == "DELETE" and path == f"/v1/default/banks/{bank_id}/memories"
            with (
                bank_target(bank_id, clear_memories=clearing),
                authenticated_request(credential, principal, bank_id, self.settings),
            ):
                suffix = path[len(f"/v1/default/banks/{bank_id}") :]
                if (scope["method"] == "POST" and suffix in {"/import", "/clone", "/transfer/import"}) or (
                    scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}
                    and (suffix == "/aliases" or suffix.startswith("/aliases/"))
                ):
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
                    or suffix.rstrip("/")
                    in {"/export", "/transfer/export", "/document-transfer/export", "/prompts/preview"}
                ) and principal.role != Role.ADMIN:
                    raise ServiceError(403, "admin_required", "The operations administrator Key is required")
                if suffix.rstrip("/") == "/config" and scope["method"] in {"GET", "PATCH", "DELETE"}:
                    await self._project_json_response(
                        scope,
                        receive,
                        observed_send,
                        _bank_config_json,
                        ServiceError(503, "invalid_bank_config", "Bank configuration response unavailable"),
                    )
                elif (
                    scope["method"] == "GET"
                    and re.fullmatch(r"/operations(?:/[^/]+)?/?", suffix)
                    and principal.role != Role.ADMIN
                ):
                    await self._project_json_response(
                        scope,
                        receive,
                        observed_send,
                        business_operation_json,
                        ServiceError(503, "invalid_diagnostics", "Task status response unavailable"),
                    )
                else:
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
            await JSONResponse({"detail": "Workspace authorization is unavailable"}, status_code=503)(
                scope, receive, send
            )
