"""Install ContextDB transport policy around the unmodified native application."""

from __future__ import annotations

from fastapi import FastAPI

from .tenant import ContextDBTenantExtension
from .transport import WorkspaceAuthorizationMiddleware


def create_app() -> FastAPI:
    from hindsight_api.server import app

    tenant = app.state.memory.tenant_extension
    if not isinstance(tenant, ContextDBTenantExtension):
        raise RuntimeError("ContextDB requires its tenant, validator and HTTP extensions")
    # The native HTTP module has finished loading; reuse its wire models only
    # now, rather than creating a circular import during extension discovery.
    from .bank_rest import create_bank_app, document_bank_contract

    bank_app = create_bank_app(app.state.memory, tenant.settings)
    document_bank_contract(app, bank_app)
    # Installed after native MCP mounting so protocol policy covers both transports.
    # The native entrypoint deliberately fails closed with ContextDB enabled.
    app.add_middleware(
        WorkspaceAuthorizationMiddleware, memory=app.state.memory, settings=tenant.settings, bank_app=bank_app
    )
    tenant.transport_authorization_installed = True
    return app
