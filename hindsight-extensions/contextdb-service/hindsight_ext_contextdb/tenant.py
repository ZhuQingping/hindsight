"""Dynamic member credentials select a workspace schema on REST and MCP alike."""

import asyncio
import secrets
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import asyncpg
from hindsight_api.extensions.operation_validator import OperationValidationError
from hindsight_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from hindsight_api.models import RequestContext

from .config import Settings, repository_for
from .models import ServiceError
from .repository import Repository

if TYPE_CHECKING:
    from .admission import AdmissionGuard


class ContextDBTenantExtension(TenantExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()
        self.metadata_pool: asyncpg.Pool | None = None
        self._metadata_lock = asyncio.Lock()
        self.http_lifecycle_owner = False
        self.admission_guard: AdmissionGuard | None = None
        self.transport_guard_installed = False
        self.queue_owner_id = secrets.token_hex(16)
        self._bank_generations: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._bank_generation_lock = asyncio.Lock()

    async def _refresh_bank_generation(self, schema: str, bank_id: str, workspace_id: str) -> None:
        """Keep native process-local profile/config entries within one workspace generation.

        Another API replica can DROP/recreate the same readable namespace while
        this process still holds its previous profile/config for the native TTL.
        Admission fences old executors; this local identity check fences their
        cached data without disabling normal same-generation cache hits.
        """
        from hindsight_api.engine import bank_info_cache
        from hindsight_api.engine.memory_engine import _current_schema

        key = (schema, bank_id)
        async with self._bank_generation_lock:
            if self._bank_generations.get(key) != workspace_id:
                token = _current_schema.set(schema)
                try:
                    await bank_info_cache.invalidate(bank_id)
                finally:
                    _current_schema.reset(token)
                self._bank_generations[key] = workspace_id
            self._bank_generations.move_to_end(key)
            # Match the native default cache bound. Eviction is conservative:
            # the next visit is a first visit and invalidates again.
            while len(self._bank_generations) > 2048:
                self._bank_generations.popitem(last=False)

    async def control_repository(self) -> Repository:
        # Management can wait for an admitted request. It must not occupy the
        # engine pool that request needs to finish. This is a separate connection
        # budget to the SAME dedicated RDS PG, not a second metadata database.
        if self.metadata_pool is None:
            async with self._metadata_lock:
                if self.metadata_pool is None:
                    url = getattr(self._engine(), "db_url", None)
                    if not isinstance(url, str):
                        raise RuntimeError("ContextDB metadata requires a resolved PostgreSQL URL")
                    self.metadata_pool = await asyncpg.create_pool(url, min_size=0, max_size=10)
        assert self.metadata_pool is not None
        return Repository(
            self.metadata_pool,
            self.settings.instance_id,
            self.settings.cloud_tenant_id,
            self.settings.pepper,
            operation_retention_hours=self.settings.operation_retention_hours,
        )

    async def on_shutdown(self) -> None:
        # Native HTTP shuts down tenant hooks before HttpExtension hooks. The
        # latter must stop its lifecycle executor before closing this pool.
        if not self.http_lifecycle_owner:
            await self.close_control_pool()

    async def close_control_pool(self) -> None:
        if self.metadata_pool is not None:
            await self.metadata_pool.close()
            self.metadata_pool = None

    async def on_startup(self) -> None:
        self._require_transport_guard()
        repository = await repository_for(self._engine(), self.settings)
        await repository.verify_schema()

    def _require_transport_guard(self) -> None:
        if not self.transport_guard_installed:
            raise RuntimeError("ContextDB customer authentication requires its HTTP admission extension")

    def _engine(self) -> object:
        from .validator import ContextDBOperationValidator

        engine = self.context.get_memory_engine()
        # Native startup migrations run outside our generation/admission guard.
        # A stale initialization thread could otherwise outlive DROP/recreate of
        # the same readable schema. Upgrade existing schemas offline; lifecycle
        # provisioning still runs explicit, durably fenced migrations at runtime.
        if getattr(engine, "_run_migrations", False) is True:
            raise RuntimeError(
                "ContextDB requires HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false; upgrade existing schemas offline"
            )
        if not isinstance(getattr(engine, "_operation_validator", None), ContextDBOperationValidator):
            raise RuntimeError("ContextDB tenant routing requires its bank/operation validator")
        return engine

    async def authenticate(self, context: RequestContext) -> TenantContext:
        from .routing import target_bank

        engine = self._engine()
        self._require_transport_guard()
        repository = await repository_for(engine, self.settings)
        bank_id = target_bank()
        try:
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
        await self._refresh_bank_generation(principal.schema_name, bank_id, principal.workspace_id)
        return TenantContext(principal.schema_name)

    async def authenticate_mcp(self, context: RequestContext) -> TenantContext:
        # initialize/tools-list carry no tool Bank. Authenticate the CURRENT
        # message now, then the MCP extension selects and rechecks the actual
        # tool Bank. The metadata schema is an explicit no-data sentinel when
        # the Key has no visible spaces; it is never a default memory schema.
        repository = await repository_for(self._engine(), self.settings)
        try:
            principal = await repository.authenticate(context.api_key, record_use=True)
            spaces = await repository.visible_workspaces(principal, readable=False)
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
        # Frozen/deleting spaces remain discoverable so already accepted jobs can
        # drain; no user request is admitted while they are frozen/deleting.
        return [Tenant(schema=item.schema_name, tenant_id=item.workspace_id) for item in workspaces]

    async def get_allowed_config_fields(self, context: RequestContext, bank_id: str) -> set[str] | None:
        from hindsight_api.config import HindsightConfig

        # Preserve the native public read surface; the resolver already strips
        # credentials and rejects static writes before applying this allow-list.
        allowed = (HindsightConfig.get_configurable_fields() | HindsightConfig.get_static_fields()) - {
            "audit_log_enabled"
        }
        if context.internal:
            return allowed
        repository = await repository_for(self._engine(), self.settings)
        try:
            await repository.authenticate_admin(context.api_key)
            await repository.authenticate(context.api_key, bank_id)
        except ServiceError:
            return set()
        return allowed

    @asynccontextmanager
    async def async_execution_scope(
        self, schema: str | None, bank_id: str, tenant_id: str | None
    ) -> AsyncIterator[None]:
        from .admission import durable_admission

        repository = await self.control_repository()
        if schema is None or tenant_id is None:
            raise ServiceError(409, "execution_generation", "Queued task lacks a workspace generation")
        workspace = await repository.internal_workspace(bank_id, schema)
        if workspace.workspace_id != tenant_id:
            raise ServiceError(409, "execution_generation", "Queued task belongs to another workspace generation")
        # register_admission locks this immutable UUID/schema and commits before
        # execution. If deletion/recreation races the lookup, old UUID admission
        # fails instead of joining the successor's identical physical namespace.
        # Frozen/deleting spaces still drain their already accepted jobs.
        async with durable_admission(repository, tenant_id, schema, "queue", self.queue_owner_id) as ticket:
            await self._refresh_bank_generation(schema, bank_id, tenant_id)
            ticket.work_started = True
            yield

    @asynccontextmanager
    async def async_submission_scope(self, schema: str, bank_id: str) -> AsyncIterator[None]:
        from .admission import durable_admission, is_admitted

        # An HTTP request already owns the shared lock. Taking it again on a
        # second connection can deadlock behind a waiting control-plane writer.
        if is_admitted(schema, bank_id):
            yield
            return
        repository = await self.control_repository()
        try:
            workspace = await repository.internal_workspace(bank_id, schema)
            async with durable_admission(
                repository, workspace.workspace_id, schema, "queue", self.queue_owner_id
            ) as ticket:
                await self._refresh_bank_generation(schema, bank_id, workspace.workspace_id)
                async with self._queue_state_scope(repository, schema, bank_id):
                    ticket.work_started = True
                    yield
        except ServiceError as error:
            raise OperationValidationError(error.message, status_code=error.status) from None

    @asynccontextmanager
    async def _queue_state_scope(self, repository: Repository, schema: str, bank_id: str) -> AsyncIterator[None]:
        from .admission import bank_initialization, protected_transaction

        # Enter BEFORE acquiring any engine connection. A queued control writer
        # may block new shared locks; doing that inside the engine transaction
        # would exhaust its pool and prevent the older HTTP reader from leaving.
        async with protected_transaction(repository.pool) as connection:
            await Repository._verify_binding(connection, self.settings.instance_id, self.settings.cloud_tenant_id)
            row = await connection.fetchrow(
                "SELECT workspace_id,state FROM ctxdb_meta.workspaces WHERE bank_id=$1 AND schema_name=$2 FOR KEY SHARE",
                bank_id,
                schema,
            )
            initialization = bank_initialization(schema, bank_id)
            if row is not None and row["state"] == "creating" and initialization is not None:
                # The workspace and operation locks cover only the short native
                # queue INSERT, never migration DDL. A stale provisioning task
                # cannot submit a default template after another owner takes over.
                owned = await repository.operation_is_owned(
                    initialization.operation_id,
                    initialization.lease_token,
                    "create_workspace",
                    row["workspace_id"],
                    connection=connection,
                    lock=True,
                )
                if not owned:
                    raise OperationValidationError("Workspace initialization lease was lost", status_code=409)
                yield
                return
            if row is None or row["state"] not in {"active", "frozen", "deleting"}:
                raise OperationValidationError("Workspace does not admit background submissions", status_code=409)
            if row["state"] != "active":
                # A running job may enqueue a continuation before its processing row
                # completes. A periodic sweep with no accepted parent cannot reopen
                # the queue after the drain observes it empty.
                processing = await connection.fetchval(
                    f"SELECT 1 FROM \"{schema}\".async_operations WHERE bank_id=$1 AND status='processing' LIMIT 1",
                    bank_id,
                )
                if not processing:
                    raise OperationValidationError("Inactive workspace queue is closed", status_code=409)
            yield
