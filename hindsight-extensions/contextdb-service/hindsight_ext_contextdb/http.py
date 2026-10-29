"""Administrator management routes and workspace-authorized usage reads."""

from __future__ import annotations

import logging
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

from .config import Settings, repository_for
from .lifecycle import Lifecycle
from .models import (
    ApiKeyCreate,
    ApiKeyPatch,
    BusinessPrincipal,
    KeyEditable,
    KeyIssued,
    KeyMetadata,
    Page,
    Scope,
    ServiceError,
    User,
    UserCreate,
    UserPatch,
    Workspace,
    WorkspaceCreate,
)
from .security import bearer_credential
from .tenant import ContextDBTenantExtension
from .usage import UsageCollector, collector_for
from .usage_repository import UsageItem, UsageRepository, UsageTarget
from .validator import ContextDBOperationValidator

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

    from .repository import Repository


logger = logging.getLogger(__name__)

ResourceId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


class WorkspaceResponse(BaseModel):
    workspace_id: str
    bank_id: str
    etag: str
    name: str
    description: str
    state: str
    version: int
    created_at: datetime


class ContextDBCapabilities(BaseModel):
    recall_usage: bool


class AdminIdentity(BaseModel):
    user_id: str
    role: Literal["admin"] = "admin"
    instance_id: str
    cloud_tenant_id: str
    capabilities: ContextDBCapabilities


class UsageReport(BaseModel):
    bank_id: str
    object_type: Literal["memory", "knowledge_page"]
    items: list[UsageItem]


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


def _principal(request: Request) -> BusinessPrincipal:
    return request.state.contextdb_principal


def _json(value: BaseModel, status: int = 200) -> JSONResponse:
    if isinstance(value, KeyMetadata):
        # Usage updates do not invalidate an editable authorization snapshot.
        # Keep approximate usage solely in the untagged list representation.
        value = KeyEditable.model_validate(value.model_dump())
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
    if isinstance(value, WorkspaceResponse):
        response.headers["ETag"] = value.etag
    if isinstance(value, (User, KeyEditable)):
        response.headers["ETag"] = f'"{value.version}"'
    return response


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

    async def on_startup(self) -> None:
        if (
            self.memory is None
            or not isinstance(self.memory.tenant_extension, ContextDBTenantExtension)
            or not isinstance(self.memory._operation_validator, ContextDBOperationValidator)
        ):
            raise RuntimeError("ContextDB requires its tenant, validator and HTTP extensions")
        repository = await repository_for(self.memory, self.settings)
        await repository.verify_schema()
        if self.settings.recall_usage_enabled and collector_for(self.memory) is None:
            collector = UsageCollector(UsageRepository(repository.pool))
            setattr(self.memory, "_contextdb_usage", collector)
            collector.start()

    async def on_shutdown(self) -> None:
        collector = collector_for(self.memory) if self.memory is not None else None
        if collector is not None:
            await collector.close()
            setattr(self.memory, "_contextdb_usage", None)

    def get_router(self, memory: MemoryEngine) -> APIRouter:
        self.memory = memory
        extension = self

        async def repository() -> Repository:
            return await repository_for(memory, extension.settings)

        async def lifecycle() -> Lifecycle:
            if not isinstance(memory.tenant_extension, ContextDBTenantExtension):
                raise RuntimeError("ContextDB requires its tenant extension")
            return Lifecycle(await repository(), memory, memory.tenant_extension.context)

        admin_bearer = HTTPBearer(scheme_name="AdministratorKey", auto_error=False)

        async def admin_headers(
            _credential: HTTPAuthorizationCredentials | None = Security(admin_bearer),
        ) -> None:
            pass

        usage_bearer = HTTPBearer(scheme_name="WorkspaceReadKey", auto_error=False)

        async def usage_headers(
            _credential: HTTPAuthorizationCredentials | None = Security(usage_bearer),
        ) -> None:
            pass

        class ManagementRoute(APIRoute):
            credential_headers = staticmethod(admin_headers)

            async def authenticate(self, request: Request) -> BusinessPrincipal:
                return await (await repository()).authenticate_admin(bearer_credential(request.scope["headers"]))

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                dependencies = list(kwargs.get("dependencies") or [])
                dependencies.append(Depends(self.credential_headers))
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
                        # Apply the route's authority before validating inputs.
                        # Management stays admin-only; usage has a separate read policy.
                        request.state.contextdb_principal = await self.authenticate(request)
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
                        logger.exception("Management metadata service unavailable; request_id=%s", request_id)
                        response = JSONResponse(
                            ErrorResponse(
                                code="metadata_unavailable",
                                message="Metadata service unavailable",
                                request_id=request_id,
                            ).model_dump(),
                            status_code=503,
                        )
                    except Exception:
                        logger.exception("Management request failed; request_id=%s", request_id)
                        response = JSONResponse(
                            ErrorResponse(
                                code="management_failed",
                                message="Management request failed; query the resource before retrying",
                                request_id=request_id,
                            ).model_dump(),
                            status_code=500,
                        )
                    response.headers["X-Request-ID"] = request_id
                    response.headers["Cache-Control"] = "no-store"
                    return response

                return handle

        class UsageReadRoute(ManagementRoute):
            credential_headers = staticmethod(usage_headers)

            async def authenticate(self, request: Request) -> BusinessPrincipal:
                # Usage inherits content-read authority, not management authority.
                # Keep this route separate so management methods stay admin-only.
                return await (await repository()).authenticate(
                    bearer_credential(request.scope["headers"]), request.path_params["bank_id"]
                )

        router = APIRouter(
            prefix="/contextdb/v1",
            route_class=ManagementRoute,
            tags=["ContextDB management"],
            responses={"default": {"model": ErrorResponse, "description": "Sanitized management error"}},
        )

        @router.get("/admin/identity", response_model=AdminIdentity)
        async def admin_session(request: Request) -> Response:
            user_id = _principal(request).user_id
            assert user_id is not None  # authenticate_admin always preserves the actual PG user identity.
            return _json(
                AdminIdentity(
                    user_id=user_id,
                    instance_id=extension.settings.instance_id,
                    cloud_tenant_id=extension.settings.cloud_tenant_id,
                    capabilities=ContextDBCapabilities(recall_usage=extension.settings.recall_usage_enabled),
                )
            )

        @router.post("/workspaces", status_code=201, response_model=WorkspaceResponse)
        async def create_workspace(request: Request, body: WorkspaceCreate) -> Response:
            workspace = await (await lifecycle()).create(_principal(request), body, request.state.contextdb_request_id)
            return _json(workspace, 201)

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

        async def read_usage(
            request: Request,
            bank_id: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_]{0,53}$")],
            object_type: Literal["memory", "knowledge_page"],
            ids: Annotated[list[str], Query(min_length=1, max_length=100)],
        ) -> Response:
            principal = _principal(request)
            scope = Scope.MEMORY_READ if object_type == "memory" else Scope.KNOWLEDGE_READ
            if scope not in principal.scopes:
                raise ServiceError(403, "scope_forbidden", "Key lacks the required read scope")
            if not extension.settings.recall_usage_enabled:
                raise ServiceError(404, "usage_disabled", "Recall usage statistics are disabled")
            repo = await repository()
            assert principal.workspace_id is not None and principal.schema_name is not None
            try:
                items = await UsageRepository(repo.pool).read(
                    UsageTarget(principal.workspace_id, bank_id, principal.schema_name), object_type, ids
                )
            except ValueError:
                raise ServiceError(
                    400, "invalid_usage_ids", "Use canonical object IDs, at most 100 per request"
                ) from None
            return _json(UsageReport(bank_id=bank_id, object_type=object_type, items=items))

        router.add_api_route(
            "/workspaces/{bank_id}/usage",
            read_usage,
            methods=["GET"],
            response_model=UsageReport,
            route_class_override=UsageReadRoute,
            description="Read object usage with the same workspace read permission as memory or knowledge content.",
        )

        @router.delete("/workspaces/{bank_id}", status_code=204)
        async def delete_workspace(
            request: Request, bank_id: Annotated[str, Path(pattern=r"^[a-z0-9][a-z0-9_]{0,53}$")]
        ) -> Response:
            condition = _workspace_condition(request)
            await (await lifecycle()).delete(
                _principal(request),
                bank_id,
                request.state.contextdb_request_id,
                expected_id=condition.workspace_id,
                expected_version=condition.version,
            )
            return Response(status_code=204)

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
