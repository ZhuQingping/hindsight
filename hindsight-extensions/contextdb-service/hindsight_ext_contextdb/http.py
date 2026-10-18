"""One operations administrator credential protects all management routes."""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Callable, Coroutine, Literal, cast

import asyncpg
from fastapi import APIRouter, Depends, Path, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from hindsight_api.extensions.http import HttpExtension
from pydantic import BaseModel, Field
from starlette.middleware import Middleware

from .admission import AdmissionGuard, WorkspaceAdmissionMiddleware
from .config import Settings, repository_for
from .lifecycle import Lifecycle
from .models import (
    ApiKeyCreate,
    ApiKeyPatch,
    ControlPrincipal,
    KeyEditable,
    KeyIssued,
    KeyMetadata,
    ManagementOperation,
    Page,
    ServiceError,
    User,
    UserCreate,
    UserPatch,
    Workspace,
    WorkspaceCreate,
)
from .security import bearer_credential
from .tenant import ContextDBTenantExtension
from .validator import ContextDBOperationValidator

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository


ResourceId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


class ManagementOperationResponse(BaseModel):
    operation_id: str
    workspace_id: str
    action: Literal["create_workspace", "delete_workspace"]
    state: Literal["pending", "running", "succeeded", "failed"]
    error_code: str | None


class WorkspaceResponse(BaseModel):
    workspace_id: str
    bank_id: str
    etag: str
    name: str
    description: str
    state: str
    version: int
    created_at: datetime
    latest_operation_id: str | None = None


class AdminIdentity(BaseModel):
    user_id: str
    role: Literal["admin"] = "admin"
    instance_id: str
    cloud_tenant_id: str


class FieldError(BaseModel):
    field: str
    reason: Literal["required", "invalid", "unknown"]


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[FieldError] = Field(default_factory=list)


def _validation_fields(error: RequestValidationError) -> list[FieldError]:
    # Locations may contain attacker-controlled unknown names. Only expose the
    # contract whitelist, never Pydantic input, custom errors, or arbitrary keys.
    known = {
        "body",
        "query",
        "path",
        "name",
        "description",
        "status",
        "authorization",
        "mode",
        "workspaces",
        "workspace_id",
        "workspace_name",
        "bank_id",
        "permission",
        "user_id",
        "key_id",
        "operation_id",
        "q",
        "limit",
        "offset",
    }
    fields = []
    for item in error.errors()[:20]:
        location = [str(part) for part in item["loc"] if str(part) in known or isinstance(part, int)]
        reason = (
            "required" if item["type"] == "missing" else "unknown" if item["type"] == "extra_forbidden" else "invalid"
        )
        fields.append(FieldError(field=".".join(location) or "request", reason=reason))
    return fields


def _principal(request: Request) -> ControlPrincipal:
    return request.state.contextdb_principal


def _json(value: BaseModel, status: int = 200) -> JSONResponse:
    if isinstance(value, KeyMetadata):
        # Usage updates do not invalidate an editable authorization snapshot.
        # Keep approximate usage solely in the untagged list representation.
        value = KeyEditable.model_validate(value.model_dump())
    if isinstance(value, ManagementOperation):
        value = ManagementOperationResponse.model_validate(value.model_dump())
    if isinstance(value, Workspace):
        value = WorkspaceResponse.model_validate(value.model_dump())
    elif isinstance(value, Page[Workspace]):
        page = cast(Page[Workspace], value)
        value = Page[WorkspaceResponse](
            items=[WorkspaceResponse.model_validate(item.model_dump()) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
    response = JSONResponse(value.model_dump(mode="json"), status_code=status)
    if status == 202 and isinstance(value, ManagementOperationResponse):
        response.headers["Location"] = f"/ext/contextdb/v1/operations/{value.operation_id}"
    if isinstance(value, WorkspaceResponse):
        response.headers["ETag"] = value.etag
    if isinstance(value, (User, KeyEditable)):
        response.headers["ETag"] = f'"{value.version}"'
    return response


def _idempotency(request: Request) -> str:
    values = request.headers.getlist("Idempotency-Key")
    value = values[0] if len(values) == 1 else None
    if value is None or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is None:
        raise ServiceError(
            400,
            "invalid_idempotency",
            "Idempotency-Key must contain 1 to 128 ASCII letters, digits, underscores or hyphens",
        )
    return value


def _version(request: Request) -> int:
    values = request.headers.getlist("If-Match")
    value = values[0] if len(values) == 1 else ""
    if re.fullmatch(r'"[1-9][0-9]{0,21}"', value) is None:
        raise ServiceError(400, "invalid_version", "If-Match must contain the quoted resource version")
    return int(value[1:-1])


def _workspace_condition(request: Request) -> WorkspaceCondition:
    values = request.headers.getlist("If-Match")
    if not values:
        raise ServiceError(428, "precondition_required", "Read the workspace and send its ETag in If-Match")
    if len(values) != 1 or re.fullmatch(r'"[0-9a-f]{32}:[1-9][0-9]{0,21}"', values[0]) is None:
        raise ServiceError(400, "invalid_version", "If-Match must contain the workspace identity ETag")
    identity, version = values[0][1:-1].split(":")
    return WorkspaceCondition(workspace_id=identity, version=int(version))


class WorkspaceCondition(BaseModel):
    workspace_id: str
    version: int


class ContextDBHttpExtension(HttpExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()
        self.memory: MemoryEngine | None = None
        self.lifecycle: Lifecycle | None = None
        self.admission: AdmissionGuard | None = None

    def get_middleware(self, memory: MemoryEngine) -> list[Middleware]:
        self.admission = AdmissionGuard(memory, self.settings)
        if isinstance(memory.tenant_extension, ContextDBTenantExtension):
            memory.tenant_extension.transport_guard_installed = True
            memory.tenant_extension.admission_guard = self.admission
        return [Middleware(WorkspaceAdmissionMiddleware, guard=self.admission)]

    async def on_startup(self) -> None:
        if (
            self.memory is None
            or not isinstance(self.memory.tenant_extension, ContextDBTenantExtension)
            or not isinstance(self.memory._operation_validator, ContextDBOperationValidator)
        ):
            raise RuntimeError("ContextDB requires its tenant, validator and HTTP extensions")
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
            self.memory.tenant_extension.admission_guard = None

    def get_router(self, memory: MemoryEngine) -> APIRouter:
        self.memory = memory
        extension = self

        async def repository() -> Repository:
            tenant = memory.tenant_extension
            if isinstance(tenant, ContextDBTenantExtension):
                return await tenant.control_repository()
            return await repository_for(memory, extension.settings)

        admin_bearer = HTTPBearer(scheme_name="AdministratorKey", auto_error=False)

        async def admin_headers(
            _credential: HTTPAuthorizationCredentials | None = Security(admin_bearer),
        ) -> None:
            pass

        class ManagementRoute(APIRoute):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                dependencies = list(kwargs.get("dependencies") or [])
                dependencies.append(Depends(admin_headers))
                kwargs["dependencies"] = dependencies
                responses = dict(kwargs.get("responses") or {})
                for status in (400, 401, 403, 404, 409, 412, 428, 503):
                    responses.setdefault(status, {"model": ErrorResponse, "description": "Sanitized management error"})
                kwargs["responses"] = responses
                super().__init__(*args, **kwargs)
                # Keep request preconditions in the generated extension spec;
                # runtime still performs the sanitized checks in the wrapper.
                parameters = []
                if "PATCH" in self.methods:
                    parameters.append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "pattern": '^"[1-9][0-9]{0,21}"$',
                                "maxLength": 24,
                                "example": '"1"',
                            },
                        }
                    )
                if "/workspaces/{bank_id}" in self.path and "DELETE" in self.methods:
                    parameters.append(
                        {
                            "name": "If-Match",
                            "in": "header",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "pattern": '^"[0-9a-f]{32}:[1-9][0-9]{0,21}"$',
                                "example": '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:2"',
                            },
                        }
                    )
                if (
                    self.path.endswith("/workspaces")
                    and "POST" in self.methods
                    or "/workspaces/{bank_id}" in self.path
                    and "DELETE" in self.methods
                ):
                    parameters.append(
                        {
                            "name": "Idempotency-Key",
                            "in": "header",
                            "required": True,
                            "schema": {
                                "type": "string",
                                "pattern": "^[A-Za-z0-9_-]{1,128}$",
                                "minLength": 1,
                                "maxLength": 128,
                            },
                        }
                    )
                self.openapi_extra = {**(self.openapi_extra or {}), "parameters": parameters}
                success = self.responses.setdefault(self.status_code or 200, {})
                headers = {
                    "X-Request-ID": {"schema": {"type": "string"}},
                    "Cache-Control": {"schema": {"type": "string", "enum": ["no-store"]}},
                }
                for response in self.responses.values():
                    response.setdefault("headers", {}).update(headers)
                if self.response_model is WorkspaceResponse:
                    success["headers"]["ETag"] = {
                        "schema": {"type": "string", "example": '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:2"'}
                    }
                if self.response_model in {User, KeyEditable, KeyIssued}:
                    success["headers"]["ETag"] = {"schema": {"type": "string", "example": '"1"'}}

            def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
                original = super().get_route_handler()

                async def handle(request: Request) -> Response:
                    request_id = secrets.token_hex(16)
                    request.state.contextdb_request_id = request_id
                    try:
                        # Authenticate before request-body validation. Customer Keys
                        # never become administrators, even with all-space access.
                        request.state.contextdb_principal = await (await repository()).authenticate_admin(
                            bearer_credential(request.scope["headers"])
                        )
                        for name, value in request.path_params.items():
                            if (
                                name.endswith("_id")
                                and name != "bank_id"
                                and re.fullmatch(r"[0-9a-f]{32}", str(value)) is None
                            ):
                                raise ServiceError(
                                    400, "invalid_id", "Resource ID must contain 32 lowercase hexadecimal characters"
                                )
                        response = await original(request)
                    except ServiceError as error:
                        response = JSONResponse(
                            ErrorResponse(code=error.code, message=error.message, request_id=request_id).model_dump(),
                            status_code=error.status,
                        )
                    except RequestValidationError as error:
                        response = JSONResponse(
                            ErrorResponse(
                                code="invalid_request",
                                message="Invalid management request",
                                request_id=request_id,
                                fields=_validation_fields(error),
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

        router = APIRouter(
            prefix="/contextdb/v1",
            route_class=ManagementRoute,
            tags=["ContextDB management"],
            responses={"default": {"model": ErrorResponse, "description": "Sanitized management error"}},
        )

        @router.get("/admin/identity", response_model=AdminIdentity)
        async def admin_session(request: Request) -> Response:
            return _json(
                AdminIdentity(
                    user_id=_principal(request).actor_subject,
                    instance_id=extension.settings.instance_id,
                    cloud_tenant_id=extension.settings.cloud_tenant_id,
                )
            )

        @router.post("/workspaces", status_code=202, response_model=ManagementOperationResponse)
        async def create_workspace(request: Request, body: WorkspaceCreate) -> Response:
            operation = await (await repository()).create_workspace(
                _principal(request), body, _idempotency(request), request.state.contextdb_request_id
            )
            return _json(operation, 202)

        @router.get("/workspaces", response_model=Page[WorkspaceResponse])
        async def list_workspaces(
            request: Request,
            limit: int = Query(20, ge=0, le=100),
            offset: int = Query(0, ge=0),
            q: str = Query("", max_length=128),
        ) -> Response:
            return _json(await (await repository()).list_workspaces(_principal(request), limit, offset, q))

        @router.get("/workspaces/{bank_id}", response_model=WorkspaceResponse)
        async def get_workspace(
            request: Request, bank_id: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_]{0,53}$")]
        ) -> Response:
            return _json(await (await repository()).get_workspace_by_name(_principal(request), bank_id))

        @router.delete("/workspaces/{bank_id}", status_code=202, response_model=ManagementOperationResponse)
        async def delete_workspace(
            request: Request, bank_id: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_]{0,53}$")]
        ) -> Response:
            condition = _workspace_condition(request)
            return _json(
                await (await repository()).delete_workspace(
                    _principal(request),
                    bank_id,
                    _idempotency(request),
                    request.state.contextdb_request_id,
                    expected_id=condition.workspace_id,
                    expected_version=condition.version,
                ),
                202,
            )

        @router.get("/operations/{operation_id}", response_model=ManagementOperationResponse)
        async def get_operation(request: Request, operation_id: ResourceId) -> Response:
            return _json(await (await repository()).get_operation(_principal(request), operation_id))

        @router.get("/users", response_model=Page[User])
        async def list_users(
            request: Request,
            q: str = Query("", max_length=128),
            limit: int = Query(20, ge=0, le=100),
            offset: int = Query(0, ge=0),
        ) -> Response:
            return _json(await (await repository()).list_users(_principal(request), limit, offset, q))

        @router.post("/users", status_code=201, response_model=User)
        async def create_user(request: Request, body: UserCreate) -> Response:
            return _json(
                await (await repository()).create_user(_principal(request), body, request.state.contextdb_request_id),
                201,
            )

        @router.patch("/users/{user_id}", response_model=User)
        async def update_user(request: Request, user_id: ResourceId, body: UserPatch) -> Response:
            return _json(
                await (await repository()).update_user(
                    _principal(request), user_id, body, _version(request), request.state.contextdb_request_id
                )
            )

        @router.delete("/users/{user_id}", status_code=204)
        async def delete_user(request: Request, user_id: ResourceId) -> Response:
            await (await repository()).update_user(
                _principal(request),
                user_id,
                UserPatch(status="disabled"),
                None,
                request.state.contextdb_request_id,
                delete=True,
            )
            return Response(status_code=204)

        @router.get("/users/{user_id}/keys", response_model=Page[KeyMetadata])
        async def list_keys(
            request: Request,
            user_id: ResourceId,
            limit: int = Query(20, ge=0, le=100),
            offset: int = Query(0, ge=0),
            q: str = Query("", max_length=128),
        ) -> Response:
            return _json(await (await repository()).list_keys(_principal(request), user_id, limit, offset, q))

        @router.post("/users/{user_id}/keys", status_code=201, response_model=KeyIssued)
        async def create_key(request: Request, user_id: ResourceId, body: ApiKeyCreate) -> Response:
            issued = await (await repository()).create_key(
                _principal(request), user_id, body, request.state.contextdb_request_id
            )
            return _json(issued.response(), 201)

        @router.patch("/users/{user_id}/keys/{key_id}", response_model=KeyEditable)
        async def update_key(request: Request, user_id: ResourceId, key_id: ResourceId, body: ApiKeyPatch) -> Response:
            return _json(
                await (await repository()).update_key(
                    _principal(request), user_id, key_id, body, _version(request), request.state.contextdb_request_id
                )
            )

        @router.delete("/users/{user_id}/keys/{key_id}", status_code=204)
        async def revoke_key(request: Request, user_id: ResourceId, key_id: ResourceId) -> Response:
            await (await repository()).revoke_key(
                _principal(request), user_id, key_id, request.state.contextdb_request_id
            )
            return Response(status_code=204)

        return router
