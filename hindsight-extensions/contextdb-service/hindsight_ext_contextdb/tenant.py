"""Dynamic member credentials select a workspace schema on REST and MCP alike."""

import asyncpg
from hindsight_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from hindsight_api.models import RequestContext

from .config import Settings, repository_for
from .database_checks import metadata_errors
from .models import Role, ServiceError
from .repository import Repository


class ContextDBTenantExtension(TenantExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()
        self.transport_authorization_installed = False

    async def on_startup(self) -> None:
        self._require_transport_authorization()
        repository = await repository_for(self._engine(), self.settings)
        await repository.verify_schema()

    def _require_transport_authorization(self) -> None:
        if not self.transport_authorization_installed:
            raise RuntimeError(
                "ContextDB requires the hindsight_ext_contextdb.asgi:create_app authorization entrypoint"
            )

    def _engine(self) -> object:
        from .validator import ContextDBOperationValidator

        engine = self.context.get_memory_engine()
        # Managed deployments initialize/upgrade explicitly before serving.
        # Keep schema discovery separate from startup DDL, as in the contract.
        if getattr(engine, "_run_migrations", False) is True:
            raise RuntimeError(
                "ContextDB requires HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false; upgrade existing schemas offline"
            )
        if not isinstance(getattr(engine, "_operation_validator", None), ContextDBOperationValidator):
            raise RuntimeError("ContextDB tenant routing requires its bank/operation validator")
        return engine

    @staticmethod
    def _current_mcp_credential(context: RequestContext) -> None:
        from fastmcp.server.dependencies import get_http_request

        from .security import bearer_credential

        try:
            request = get_http_request()
        except RuntimeError:
            return  # REST and Worker execution have no FastMCP HTTP request.
        context.api_key = bearer_credential(request.scope["headers"])

    async def authenticate(self, context: RequestContext) -> TenantContext:
        from .routing import target_bank

        engine = self._engine()
        self._require_transport_authorization()
        self._current_mcp_credential(context)
        try:
            with metadata_errors():
                repository = await repository_for(engine, self.settings)
                bank_id = target_bank()
                if not bank_id:
                    raise ServiceError(403, "bank_required", "A registered Bank target is required")
                principal = await repository.authenticate(context.api_key, bank_id, record_use=True)
        except ServiceError as error:
            raise AuthenticationError(error.message) from None
        context.api_key_id = principal.key_id
        context.tenant_id = principal.workspace_id
        context.allowed_bank_ids = [bank_id]
        assert principal.schema_name is not None
        assert principal.workspace_id is not None
        return TenantContext(principal.schema_name)

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        # initialize/tools-list carry no tool Bank. Authenticate the CURRENT
        # message now, then the MCP extension selects and rechecks the actual
        # tool Bank. The metadata schema is an explicit no-data sentinel when
        # the Key has no visible spaces; it is never a default memory schema.
        try:
            with metadata_errors():
                repository = await repository_for(self._engine(), self.settings)
                principal = await repository.authenticate(context.api_key, record_use=True)
                spaces = await repository.visible_workspaces(principal)
        except ServiceError as error:
            raise AuthenticationError(error.message) from None
        context.api_key_id = principal.key_id
        context.tenant_id = self.settings.cloud_tenant_id
        return TenantContext(spaces[0].schema_name if spaces else "ctxdb_meta")

    async def list_tenants(self) -> list[Tenant]:
        engine = self._engine()
        if getattr(engine, "_initialized", None) is False:
            # Core calls discovery before it has opened its pool. _get_pool() here
            # would initialize -> discover -> initialize forever. A short-lived
            # metadata connection closes before migration; runtime uses the pool.
            url = getattr(engine, "db_url", None)
            if not isinstance(url, str) or not url.startswith("postgresql"):
                raise RuntimeError("ContextDB requires a resolved PostgreSQL deployment URL")
            connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
            try:
                workspaces = await Repository.discover_workspaces(
                    connection, self.settings.instance_id, self.settings.cloud_tenant_id
                )
            finally:
                await connection.close()
        else:
            repository = await repository_for(engine, self.settings)
            workspaces = await repository.worker_workspaces()
        # Keep the native task discovery contract. This does not prove work
        # has finished; stopping access before deletion remains an operator duty.
        return [Tenant(schema=item.schema_name, tenant_id=item.workspace_id) for item in workspaces]

    async def get_allowed_config_fields(self, context: RequestContext, bank_id: str) -> set[str] | None:
        from hindsight_api.config import HindsightConfig

        allowed = (HindsightConfig.get_configurable_fields() | HindsightConfig.get_static_fields()) - {
            "audit_log_enabled"
        }
        if context.internal:
            return allowed
        self._current_mcp_credential(context)
        try:
            with metadata_errors():
                repository = await repository_for(self._engine(), self.settings)
                principal = await repository.authenticate(context.api_key, bank_id)
        except ServiceError:
            return set()
        return allowed if principal.role == Role.ADMIN else set()
