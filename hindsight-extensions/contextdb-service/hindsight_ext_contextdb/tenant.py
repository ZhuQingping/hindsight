"""Dynamic member credentials select a workspace schema on REST and MCP alike."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from hindsight_api.extensions.operation_validator import OperationValidationError
from hindsight_api.extensions.tenant import AuthenticationError, Tenant, TenantContext, TenantExtension
from hindsight_api.models import RequestContext

from .config import Settings, repository_for
from .models import ServiceError
from .repository import Repository


class ContextDBTenantExtension(TenantExtension):
    def __init__(self, config: dict[str, str]) -> None:
        super().__init__(config)
        self.settings = Settings.from_environment()
        self.metadata_pool: asyncpg.Pool | None = None
        self._metadata_lock = asyncio.Lock()
        self.http_lifecycle_owner = False
        self.transport_guard_installed = False
        self.queue_owner_id = secrets.token_hex(16)

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
            self.metadata_pool, self.settings.instance_id, self.settings.cloud_tenant_id, self.settings.pepper
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
        if not isinstance(getattr(engine, "_operation_validator", None), ContextDBOperationValidator):
            raise RuntimeError("ContextDB tenant routing requires its bank/operation validator")
        return engine

    async def authenticate(self, context: RequestContext) -> TenantContext:
        engine = self._engine()
        self._require_transport_guard()
        repository = await repository_for(engine, self.settings)
        try:
            principal = await repository.authenticate(context.api_key, record_use=True)
        except ServiceError as error:
            raise AuthenticationError(error.message) from None
        context.api_key_id = principal.key_id
        context.tenant_id = principal.workspace_id
        context.allowed_bank_ids = [principal.workspace_id]
        return TenantContext(principal.schema_name)

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

    async def get_allowed_config_fields(self, context: RequestContext, bank_id: str) -> set[str]:
        return set()

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
            async with durable_admission(repository, bank_id, schema, "queue", self.queue_owner_id) as ticket:
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
            row = await connection.fetchrow(
                "SELECT state FROM ctxdb_meta.workspaces WHERE workspace_id=$1 AND schema_name=$2 "
                "AND instance_id=$3 AND cloud_tenant_id=$4 FOR KEY SHARE",
                bank_id,
                schema,
                self.settings.instance_id,
                self.settings.cloud_tenant_id,
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
                    bank_id,
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
