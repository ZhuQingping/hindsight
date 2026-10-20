"""Request-local authorization and trusted calls through native extension slots.

These contexts carry identity only. They hold no database connection, record
executors, cancel tasks, or protect concurrent workspace deletion.
"""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from hindsight_api.models import RequestContext

from .models import BusinessPrincipal, Permission, Scope, Workspace
from .security import key_digest

if TYPE_CHECKING:
    from .config import Settings


@dataclass
class AuthenticatedRequest:
    principal: BusinessPrincipal
    bank_id: str
    instance_id: str
    cloud_tenant_id: str
    digest: bytes = field(repr=False)
    active: bool = True


_authenticated: ContextVar[AuthenticatedRequest | None] = ContextVar("contextdb_authentication", default=None)


@contextmanager
def authenticated_request(
    credential: str,
    principal: BusinessPrincipal,
    bank_id: str,
    settings: Settings,
) -> Iterator[None]:
    """Share one target authentication within a request, never across messages."""
    request = AuthenticatedRequest(
        principal, bank_id, settings.instance_id, settings.cloud_tenant_id, key_digest(credential, settings.pepper)
    )
    token = _authenticated.set(request)
    try:
        yield
    finally:
        # Child tasks inherit ContextVars. Finishing this request must also
        # invalidate any inherited snapshot without tracking those executors.
        request.active = False
        _authenticated.reset(token)


def authenticated_principal(
    credential: str | None, bank_id: str | None, instance_id: str, cloud_tenant_id: str, pepper: str
) -> BusinessPrincipal | None:
    request = _authenticated.get()
    if (
        request is None
        or not request.active
        or credential is None
        or bank_id != request.bank_id
        or instance_id != request.instance_id
        or cloud_tenant_id != request.cloud_tenant_id
    ):
        return None
    return request.principal if hmac.compare_digest(key_digest(credential, pepper), request.digest) else None


@dataclass(repr=False)
class ManagementCall:
    workspace_id: str
    bank_id: str
    schema_name: str
    action: Literal["create_workspace", "delete_workspace"]
    request_context: RequestContext
    owner: asyncio.Task[object] | None
    active: bool = True


_management: ContextVar[ManagementCall | None] = ContextVar("contextdb_management_call", default=None)


@contextmanager
def workspace_management(
    workspace: Workspace, action: Literal["create_workspace", "delete_workspace"]
) -> Iterator[RequestContext]:
    """Called only after management authentication and a short state transition.

    Reuse the native internal context, but require this exact object and task
    for lifecycle privileges. Client headers and background jobs cannot mint
    that authority. There is no lease or promise about executor termination.
    """
    from hindsight_api.engine.memory_engine import _current_schema

    context = RequestContext(internal=True, tenant_id=workspace.workspace_id, allowed_bank_ids=[workspace.bank_id])
    call = ManagementCall(
        workspace.workspace_id, workspace.bank_id, workspace.schema_name, action, context, asyncio.current_task()
    )
    schema_token = _current_schema.set(workspace.schema_name)
    token = _management.set(call)
    try:
        yield context
    finally:
        call.active = False
        _management.reset(token)
        _current_schema.reset(schema_token)


def management_call(context: RequestContext, bank_id: str, schema: str | None) -> ManagementCall | None:
    call = _management.get()
    if (
        call is not None
        and call.active
        and call.request_context is context
        and call.owner is asyncio.current_task()
        and call.bank_id == bank_id
        and call.schema_name == schema
        and call.workspace_id == context.tenant_id
    ):
        return call
    return None


def permission_scopes(permission: Permission) -> frozenset[Scope]:
    """The same scope projection for target authorization and tool discovery."""
    scopes = {Scope.MEMORY_READ, Scope.KNOWLEDGE_READ, Scope.REFLECT}
    if permission == Permission.READ_WRITE:
        scopes.add(Scope.MEMORY_WRITE)
    return frozenset(scopes)


def discovery_scopes(principal: BusinessPrincipal, workspaces: Iterable[Workspace]) -> frozenset[Scope]:
    """Advertise scopes for currently visible UUIDs; never authorize execution.

    The caller supplies this message's unscoped principal and active directory.
    Actual tool calls still authenticate their target using the live credential.
    """
    visible_ids = {workspace.workspace_id for workspace in workspaces}
    if principal.access_mode == "all":
        return permission_scopes(principal.permission) if visible_ids else frozenset()
    return frozenset(
        scope
        for grant in principal.workspace_permissions
        if grant.workspace_id in visible_ids
        for scope in permission_scopes(grant.permission)
    )
