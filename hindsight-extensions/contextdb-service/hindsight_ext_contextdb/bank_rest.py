"""Plugin-owned Bank REST adapter, dispatched before active-target auth.

Keep FastAPI validation and the host's route/metrics implementations rather
than hand-parsing JSON or cloning its middleware. The original application
continues to own tracing around this dispatcher; do not instrument it twice.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from hindsight_api.api.http import BankProfileResponse, CreateBankRequest, DeleteResponse, _internal_error
from hindsight_api.api.observability import HttpObservabilityMiddleware
from hindsight_api.api.passthrough_headers import collect_passthrough_headers
from hindsight_api.api.unknown_params import UnknownParamsRoute
from hindsight_api.config import get_config
from hindsight_api.extensions import AuthenticationError, OperationValidationError
from hindsight_api.models import RequestContext
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse, Response

from .authorization import authenticated_request
from .bank_contract import deletion_response, profile_response
from .config import Settings, repository_for
from .database_checks import metadata_errors
from .http import _workspace_condition
from .lifecycle import Lifecycle
from .models import Role, ServiceError
from .routing import bank_target
from .security import bearer_credential
from .tenant import ContextDBTenantExtension

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine


def create_bank_app(memory: MemoryEngine, settings: Settings) -> FastAPI:
    tenant = memory.tenant_extension
    assert isinstance(tenant, ContextDBTenantExtension)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    gzip_size = get_config().gzip_min_size
    if gzip_size >= 0:
        app.add_middleware(GZipMiddleware, minimum_size=gzip_size)
    app.add_middleware(HttpObservabilityMiddleware)
    # ContextDB Settings requires native Audit off and rejects enabled Bank
    # overrides. Even its disabled decorator probes Bank config before a new
    # schema exists (and after deletion); never run that probe here. Existing
    # repository management audits remain the lifecycle's authority.

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse(
            {"detail": error.message, "code": error.code, "request_id": request.state.request_id},
            status_code=error.status,
            headers={"Cache-Control": "no-store", "X-Request-ID": request.state.request_id},
        )

    @app.exception_handler(OperationValidationError)
    async def validation_error(request: Request, error: OperationValidationError) -> JSONResponse:
        return JSONResponse({"detail": error.reason}, status_code=error.status_code)

    async def admin(request: Request) -> RequestContext:
        cached = getattr(request.state, "bank_context", None)
        if cached is not None:
            return cached
        request.state.request_id = secrets.token_hex(12)
        repository = await repository_for(memory, settings)
        credential = bearer_credential(request.scope["headers"])
        request.state.principal = await repository.authenticate_admin(credential)
        request.state.repository = repository
        context = RequestContext(
            api_key=credential,
            extra_headers=collect_passthrough_headers(request.headers.raw, get_config().extension_passthrough_headers),
        )
        request.state.bank_context = context
        return context

    class BankRoute(UnknownParamsRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            handler = super().get_route_handler()

            async def authorized(request: Request) -> Response:
                # Authenticate before body validation; do not parse or echo an
                # unauthenticated management payload. Cache for Depends(admin).
                try:
                    with metadata_errors():
                        await admin(request)
                    return await handler(request)
                except (ServiceError, OperationValidationError, RequestValidationError, HTTPException):
                    raise
                except AuthenticationError as error:
                    raise HTTPException(status_code=401, detail=str(error)) from None
                except Exception as error:
                    # Preserve native wrapped-store 503/Retry-After and stable
                    # JSON 500 behavior. Do not relabel engine faults as metadata.
                    raise _internal_error(error, "ContextDB Bank REST") from None

            return authorized

    app.router.route_class = BankRoute

    async def write(
        bank_id: str, body: CreateBankRequest, request: Request, context: RequestContext, *, put: bool
    ) -> BankProfileResponse:
        repository = request.state.repository
        principal = request.state.principal
        conditions = request.headers.getlist("If-None-Match")
        if conditions and (not put or conditions != ["*"]):
            raise ServiceError(400, "invalid_condition", "Only PUT If-None-Match: * is supported")
        try:
            with metadata_errors():
                workspace = await repository.get_workspace_by_name(principal, bank_id)
        except ServiceError as error:
            if error.status != 404:
                raise
            if not put:
                raise
            workspace = None
        lifecycle = Lifecycle(repository, memory, tenant.context)
        try:
            if workspace is None or conditions:
                return await lifecycle.create_bank(
                    principal, bank_id, body, request.state.request_id, create_only=bool(conditions)
                )
            if workspace.state != "active":
                raise ServiceError(409, "workspace_state", "Verify the existing workspace management request")
            credential = context.api_key
            assert credential is not None
            # Normal external authorization for updates, never trusted internal
            # privileges or implicit recreation under an existing UUID.
            with bank_target(bank_id):
                with metadata_errors():
                    target = await repository.authenticate(credential, bank_id, record_use=True)
                with authenticated_request(credential, target, bank_id, settings):
                    result = await memory.update_bank(
                        bank_id,
                        name=body.name,
                        config_updates=body.get_config_updates() or None,
                        create_if_missing=False,
                        request_context=context,
                    )
            return profile_response(bank_id, result)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

    path = "/v1/default/banks/{bank_id}"
    create_condition = {
        "parameters": [
            {
                "name": "If-None-Match",
                "in": "header",
                "required": False,
                "schema": {"type": "string", "enum": ["*"]},
                "description": "ContextDB strict creation; existing registrations return 412.",
            }
        ]
    }
    delete_condition = {
        "parameters": [
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
                "description": 'Workspace identity ETag: "workspace_id:version".',
            }
        ]
    }

    @app.put(path, response_model=BankProfileResponse, openapi_extra=create_condition)
    async def create(
        bank_id: str, body: CreateBankRequest, request: Request, request_context: RequestContext = Depends(admin)
    ) -> BankProfileResponse:
        return await write(bank_id, body, request, request_context, put=True)

    @app.patch(path, response_model=BankProfileResponse)
    async def update(
        bank_id: str, body: CreateBankRequest, request: Request, request_context: RequestContext = Depends(admin)
    ) -> BankProfileResponse:
        return await write(bank_id, body, request, request_context, put=False)

    @app.delete(path, response_model=DeleteResponse, openapi_extra=delete_condition)
    async def delete(
        bank_id: str, request: Request, request_context: RequestContext = Depends(admin)
    ) -> DeleteResponse:
        condition = _workspace_condition(request)
        lifecycle = Lifecycle(request.state.repository, memory, tenant.context)
        result = await lifecycle.delete(
            request.state.principal,
            bank_id,
            request.state.request_id,
            expected_id=condition.workspace_id,
            expected_version=condition.version,
        )
        return deletion_response(bank_id, result)

    return app


def document_bank_contract(host: FastAPI, bank_app: FastAPI) -> None:
    """Describe plugin-mode conditions on the existing native OpenAPI paths."""
    original = host.openapi

    def openapi() -> dict[str, Any]:
        # OpenAPI is arbitrary JSON, rather than a domain object. Keep the
        # native generator (including its validation-schema patch) as authority.
        schema = original()
        path = "/v1/default/banks/{bank_id}"
        for method, source in bank_app.openapi()["paths"][path].items():
            operation = schema["paths"][path][method]
            existing = operation.setdefault("parameters", [])
            for parameter in source.get("parameters", []):
                if parameter["in"] == "header" and not any(
                    p["in"] == "header" and p["name"] == parameter["name"] for p in existing
                ):
                    existing.append(parameter)
            operation["security"] = [{"AdministratorKey": []}]
            for status in (400, 401, 403, 404, 409, 412, 428, 503):
                operation["responses"].setdefault(str(status), {"description": "ContextDB management error"})
        return schema

    # FastAPI supports replacing this instance callback; it is intentionally
    # unbound, unlike the class method described by its static annotation.
    setattr(host, "openapi", openapi)
