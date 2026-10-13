"""Internal management REST adapter. Authentication precedes body validation.

User-facing authentication stays in the existing cloud control backend. This
router accepts only a service Key and the backend's actor assertion; persistence
and invariants live in Repository, not in handlers. No management MCP tools.
"""

from __future__ import annotations

import ipaddress
import secrets
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Literal, overload

import asyncpg
from fastapi import APIRouter, Depends, Header, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.security import APIKeyHeader
from hindsight_api.extensions.http import HttpExtension
from pydantic import BaseModel, Field
from starlette.middleware import Middleware

from .admission import AdmissionGuard, WorkspaceAdmissionMiddleware
from .config import Settings, repository_for
from .lifecycle import Lifecycle
from .models import (
    ApiKeyCreate,
    ControlPrincipal,
    Instance,
    InstanceCreate,
    KeyMetadata,
    ManagementOperation,
    Member,
    MemberCreate,
    MemberPatch,
    Page,
    ServiceError,
    Workspace,
    WorkspaceCreate,
    WorkspacePatch,
)
from .tenant import ContextDBTenantExtension
from .validator import ContextDBOperationValidator

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository


class KeyIssuedResponse(KeyMetadata):
    secret: str = Field(repr=False)


class RequestIdResponse(BaseModel):
    request_id: str


class InstanceResponse(Instance, RequestIdResponse):
    pass


class WorkspaceResponse(Workspace, RequestIdResponse):
    pass


class MemberResponse(Member, RequestIdResponse):
    pass


class ApiKeyIssuedResponse(KeyIssuedResponse, RequestIdResponse):
    pass


class WorkspacePageResponse(Page[Workspace], RequestIdResponse):
    pass


class MemberPageResponse(Page[Member], RequestIdResponse):
    pass


class ApiKeyPageResponse(Page[KeyMetadata], RequestIdResponse):
    pass


class ManagementOperationResponse(RequestIdResponse):
    # This is a positive public-field list: new executor fields must never leak
    # simply because the persisted ManagementOperation gains another attribute.
    operation_id: str
    workspace_id: str
    action: Literal["create_workspace", "delete_workspace"]
    state: Literal["pending", "running", "succeeded", "failed"]
    attempts: int = Field(ge=0)
    error_code: str | None


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


def _principal(request: Request) -> ControlPrincipal:
    return request.state.contextdb_principal


def _json(request: Request, value: BaseModel, status: int = 200) -> JSONResponse:
    # Serialization is the JSON boundary, not an untyped domain object.
    if isinstance(value, ManagementOperation):
        value = ManagementOperationResponse.model_validate(
            {**value.model_dump(), "request_id": request.state.contextdb_request_id}
        )
    payload = value.model_dump(mode="json")
    payload["request_id"] = request.state.contextdb_request_id
    return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})


@overload
def _idempotency(request: Request, *, required: Literal[True] = True) -> str: ...


@overload
def _idempotency(request: Request, *, required: Literal[False]) -> str | None: ...


def _idempotency(request: Request, *, required: bool = True) -> str | None:
    value = request.headers.get("Idempotency-Key")
    if value is None and not required:
        return None
    if not value or len(value) > 128:
        raise ServiceError(400, "invalid_idempotency", "Idempotency-Key must contain 1 to 128 characters")
    return value


def _version(request: Request) -> int:
    value = request.headers.get("If-Match", "")
    if len(value) > 24 or not value.startswith('"') or not value.endswith('"') or not value[1:-1].isdigit():
        raise ServiceError(400, "invalid_version", "If-Match must contain the quoted current resource version")
    return int(value[1:-1])


class ContextDBHttpExtension(HttpExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()
        self.auth = self.settings.control_auth()
        self.networks = [ipaddress.ip_network(value.strip()) for value in self.settings.control_networks]
        self.memory: MemoryEngine | None = None
        self.lifecycle: Lifecycle | None = None
        self.admission: AdmissionGuard | None = None

    def get_middleware(self, memory: MemoryEngine) -> list[Middleware]:
        self.admission = AdmissionGuard(memory, self.settings)
        if isinstance(memory.tenant_extension, ContextDBTenantExtension):
            memory.tenant_extension.transport_guard_installed = True
        return [Middleware(WorkspaceAdmissionMiddleware, guard=self.admission)]

    async def on_startup(self) -> None:
        if self.memory is None:
            raise RuntimeError("ContextDB HTTP router must be bound before startup")
        if not isinstance(self.memory.tenant_extension, ContextDBTenantExtension) or not isinstance(
            self.memory._operation_validator,
            ContextDBOperationValidator,
        ):
            raise RuntimeError("ContextDB management requires both ContextDB tenant and operation-validator extensions")
        repository = await self.memory.tenant_extension.control_repository()
        await repository.verify_schema()
        if self.admission is None:
            raise RuntimeError("ContextDB requires its transport admission middleware")
        await self.admission.start()
        self.memory.tenant_extension.http_lifecycle_owner = True
        self.lifecycle = Lifecycle(repository, self.memory, self.memory.tenant_extension.context)
        self.lifecycle.start()

    async def on_shutdown(self) -> None:
        if self.lifecycle is not None:
            await self.lifecycle.stop()
            self.lifecycle = None
        if self.admission is not None:
            await self.admission.stop()
        if self.memory is not None and isinstance(self.memory.tenant_extension, ContextDBTenantExtension):
            await self.memory.tenant_extension.close_control_pool()
            self.memory.tenant_extension.http_lifecycle_owner = False

    def get_router(self, memory: MemoryEngine) -> APIRouter:
        self.memory = memory
        extension = self

        class ManagementRoute(APIRoute):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                # These transport headers apply even to a bodyless 204. Keep the
                # declaration together with the wrapper that actually emits them.
                headers = {
                    "X-Request-ID": {"schema": {"type": "string"}},
                    "Cache-Control": {"schema": {"type": "string", "enum": ["no-store"]}},
                }
                success = self.responses.setdefault(self.status_code or 200, {})
                for response in self.responses.values():
                    response.setdefault("headers", {}).update(headers)
                if self.response_model in {WorkspaceResponse, MemberResponse}:
                    success["headers"]["ETag"] = {"schema": {"type": "string", "example": '"2"'}}

            def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
                original = super().get_route_handler()

                async def handle(request: Request) -> Response:
                    request_id = secrets.token_hex(16)
                    request.state.contextdb_request_id = request_id
                    try:
                        # Proxy middleware can rewrite ASGI client from forwarded
                        # headers. This private ingress rejects such headers and
                        # must run without --proxy-headers; ingress strips them.
                        if "X-Forwarded-For" in request.headers or "Forwarded" in request.headers:
                            raise ServiceError(
                                403, "control_network", "Forwarded identity is not accepted on control ingress"
                            )
                        peer = ipaddress.ip_address(request.client.host) if request.client else None
                        if peer is None or not any(peer in network for network in extension.networks):
                            raise ServiceError(
                                403, "control_network", "Management requests require the private control ingress"
                            )
                        request.state.contextdb_principal = extension.auth.authenticate(
                            request.headers.get("X-ContextDB-Control-Key"),
                            request.headers.get("X-ContextDB-Actor-Subject"),
                        )
                        response = await original(request)
                    except ServiceError as error:
                        response = JSONResponse(
                            ErrorResponse(code=error.code, message=error.message, request_id=request_id).model_dump(),
                            status_code=error.status,
                        )
                    except RequestValidationError:
                        # The default includes raw input values. A generic error
                        # both matches the contract and avoids echoing credentials.
                        response = JSONResponse(
                            ErrorResponse(
                                code="invalid_request", message="Invalid management request", request_id=request_id
                            ).model_dump(),
                            status_code=400,
                        )
                    except (asyncpg.PostgresError, OSError):
                        response = JSONResponse(
                            ErrorResponse(
                                code="metadata_unavailable",
                                message="Metadata service unavailable",
                                request_id=request_id,
                            ).model_dump(),
                            status_code=503,
                        )
                    response.headers["X-Request-ID"] = request_id
                    response.headers["Cache-Control"] = "no-store"
                    return response

                return handle

        control_key = APIKeyHeader(name="X-ContextDB-Control-Key", scheme_name="ControlPlaneKey", auto_error=False)

        async def control_headers(
            _credential: str | None = Security(control_key),
            _actor: str = Header(alias="X-ContextDB-Actor-Subject", min_length=1, max_length=256),
        ) -> None:
            # Standard OpenAPI metadata, not a second authentication path. The
            # route wrapper has already verified the credential before FastAPI
            # parses/validates body or dependencies; auto_error=False preserves it.
            pass

        router = APIRouter(
            prefix="/contextdb/v1",
            route_class=ManagementRoute,
            tags=["ContextDB management"],
            dependencies=[Depends(control_headers)],
            responses={
                # A documented default suppresses FastAPI's automatic 422. The
                # wrapper deliberately maps input validation to sanitized 400.
                "default": {"model": ErrorResponse, "description": "Management error; never returns credentials"},
                400: {"model": ErrorResponse, "description": "Invalid management request"},
                401: {"model": ErrorResponse, "description": "Missing or invalid control Key"},
                403: {"model": ErrorResponse, "description": "Control ingress or target permission denied"},
                404: {"model": ErrorResponse, "description": "Target not found or not visible"},
                409: {"model": ErrorResponse, "description": "State or idempotency conflict"},
                412: {"model": ErrorResponse, "description": "Resource version changed"},
                503: {"model": ErrorResponse, "description": "Metadata temporarily unavailable"},
            },
        )

        async def repository() -> Repository:
            tenant_extension = getattr(memory, "tenant_extension", None)
            if isinstance(tenant_extension, ContextDBTenantExtension):
                return await tenant_extension.control_repository()
            return await repository_for(memory, extension.settings)

        @router.post("/instances", status_code=201, response_model=InstanceResponse, operation_id="registerInstance")
        async def create_instance(request: Request, body: InstanceCreate) -> Response:
            value = await (await repository()).create_instance(_principal(request), body)
            return _json(request, value, 201)

        @router.get("/instances/{instance_id}", response_model=InstanceResponse, operation_id="getInstance")
        async def get_instance(request: Request, instance_id: str) -> Response:
            return _json(request, await (await repository()).get_instance(_principal(request), instance_id))

        @router.post(
            "/workspaces",
            status_code=202,
            response_model=ManagementOperationResponse,
            operation_id="createWorkspace",
            openapi_extra={
                "parameters": [
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                    }
                ]
            },
        )
        async def create_workspace(request: Request, body: WorkspaceCreate) -> Response:
            value = await (await repository()).create_workspace(
                _principal(request),
                body,
                _idempotency(request),
                request.state.contextdb_request_id,
            )
            return _json(request, value, 202)

        @router.get("/workspaces", response_model=WorkspacePageResponse, operation_id="listWorkspaces")
        async def list_workspaces(
            request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)
        ) -> Response:
            return _json(request, await (await repository()).list_workspaces(_principal(request), limit, offset))

        @router.get("/workspaces/{workspace_id}", response_model=WorkspaceResponse, operation_id="getWorkspace")
        async def get_workspace(request: Request, workspace_id: str) -> Response:
            value = await (await repository()).get_workspace(_principal(request), workspace_id)
            response = _json(request, value)
            response.headers["ETag"] = f'"{value.version}"'
            return response

        @router.patch(
            "/workspaces/{workspace_id}",
            response_model=WorkspaceResponse,
            operation_id="updateWorkspace",
            openapi_extra={
                "parameters": [{"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}]
            },
        )
        async def update_workspace(request: Request, workspace_id: str, body: WorkspacePatch) -> Response:
            value = await (await repository()).update_workspace(
                _principal(request),
                workspace_id,
                body,
                _version(request),
                request.state.contextdb_request_id,
            )
            response = _json(request, value)
            response.headers["ETag"] = f'"{value.version}"'
            return response

        @router.delete(
            "/workspaces/{workspace_id}",
            status_code=202,
            response_model=ManagementOperationResponse,
            operation_id="deleteWorkspace",
            openapi_extra={
                "parameters": [
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                    }
                ]
            },
        )
        async def delete_workspace(request: Request, workspace_id: str) -> Response:
            value = await (await repository()).delete_workspace(
                _principal(request),
                workspace_id,
                _idempotency(request),
                request.state.contextdb_request_id,
            )
            return _json(request, value, 202)

        @router.get(
            "/operations/{operation_id}",
            response_model=ManagementOperationResponse,
            operation_id="getManagementOperation",
        )
        async def get_operation(request: Request, operation_id: str) -> Response:
            return _json(request, await (await repository()).get_operation(_principal(request), operation_id))

        @router.post(
            "/workspaces/{workspace_id}/members",
            status_code=201,
            response_model=MemberResponse,
            operation_id="createMember",
        )
        async def create_member(request: Request, workspace_id: str, body: MemberCreate) -> Response:
            value = await (await repository()).create_member(
                _principal(request), workspace_id, body, request.state.contextdb_request_id
            )
            return _json(request, value, 201)

        @router.get("/workspaces/{workspace_id}/members", response_model=MemberPageResponse, operation_id="listMembers")
        async def list_members(
            request: Request, workspace_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)
        ) -> Response:
            return _json(
                request, await (await repository()).list_members(_principal(request), workspace_id, limit, offset)
            )

        @router.get(
            "/workspaces/{workspace_id}/members/{member_id}", response_model=MemberResponse, operation_id="getMember"
        )
        async def get_member(request: Request, workspace_id: str, member_id: str) -> Response:
            value = await (await repository()).get_member(_principal(request), workspace_id, member_id)
            response = _json(request, value)
            response.headers["ETag"] = f'"{value.version}"'
            return response

        @router.patch(
            "/workspaces/{workspace_id}/members/{member_id}",
            response_model=MemberResponse,
            operation_id="updateMember",
            openapi_extra={
                "parameters": [{"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}]
            },
        )
        async def update_member(request: Request, workspace_id: str, member_id: str, body: MemberPatch) -> Response:
            value = await (await repository()).update_member(
                _principal(request),
                workspace_id,
                member_id,
                body,
                _version(request),
                request.state.contextdb_request_id,
            )
            response = _json(request, value)
            response.headers["ETag"] = f'"{value.version}"'
            return response

        @router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=204, operation_id="deleteMember")
        async def delete_member(request: Request, workspace_id: str, member_id: str) -> Response:
            await (await repository()).update_member(
                _principal(request),
                workspace_id,
                member_id,
                MemberPatch(status="disabled"),
                None,
                request.state.contextdb_request_id,
                delete=True,
            )
            return Response(status_code=204)

        @router.post(
            "/workspaces/{workspace_id}/members/{member_id}/api-keys",
            status_code=201,
            response_model=ApiKeyIssuedResponse,
            operation_id="createApiKey",
            openapi_extra={
                "parameters": [
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": False,
                        "schema": {"type": "string", "minLength": 1, "maxLength": 128},
                    }
                ]
            },
        )
        async def create_key(request: Request, workspace_id: str, member_id: str, body: ApiKeyCreate) -> Response:
            value = await (await repository()).create_key(
                _principal(request),
                workspace_id,
                member_id,
                body,
                request.state.contextdb_request_id,
                _idempotency(request, required=False),
            )
            return _json(
                request,
                KeyIssuedResponse.model_validate({**value.metadata.model_dump(), "secret": value.secret}),
                201,
            )

        @router.get(
            "/workspaces/{workspace_id}/members/{member_id}/api-keys",
            response_model=ApiKeyPageResponse,
            operation_id="listApiKeys",
        )
        async def list_keys(
            request: Request,
            workspace_id: str,
            member_id: str,
            limit: int = Query(20, ge=1, le=100),
            offset: int = Query(0, ge=0),
        ) -> Response:
            return _json(
                request,
                await (await repository()).list_keys(_principal(request), workspace_id, member_id, limit, offset),
            )

        @router.post(
            "/workspaces/{workspace_id}/members/{member_id}/api-keys/{key_id}/revoke",
            status_code=204,
            operation_id="revokeApiKey",
        )
        async def revoke_key(request: Request, workspace_id: str, member_id: str, key_id: str) -> Response:
            await (await repository()).revoke_key(
                _principal(request), workspace_id, member_id, key_id, request.state.contextdb_request_id
            )
            return Response(status_code=204)

        return router
