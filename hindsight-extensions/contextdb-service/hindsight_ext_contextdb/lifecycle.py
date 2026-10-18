"""Recoverable workspace provisioning within the API process, not a new service."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import time
from typing import TYPE_CHECKING

from hindsight_api.extensions.context import ExtensionContext
from hindsight_api.models import RequestContext
from pydantic import BaseModel

from .admission import initializing_bank
from .models import ManagementOperation, ServiceError
from .repository import Repository

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

logger = logging.getLogger(__name__)


class OperationCount(BaseModel):
    total: int


class Lifecycle:
    def __init__(self, repository: Repository, memory: MemoryEngine, context: ExtensionContext) -> None:
        self.repository = repository
        self.memory = memory
        self.context = context
        self._task: asyncio.Task[None] | None = None
        self._last_prune = 0.0

    def start(self) -> None:
        self._task = asyncio.create_task(self.run(), name="contextdb-workspace-lifecycle")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _heartbeat(self, operation: ManagementOperation) -> None:
        while True:
            await asyncio.sleep(10)
            if not await self.repository.renew_operation(operation):
                raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")

    async def run(self) -> None:
        while True:
            try:
                if time.monotonic() - self._last_prune >= 60:
                    await self.repository.prune_operations()
                    self._last_prune = time.monotonic()
                operation = await self.repository.claim_operation()
                if operation is None:
                    await asyncio.sleep(0.5)
                    continue
                await self.execute(operation)
            except asyncio.CancelledError:
                raise
            except Exception:
                # DB failures must not permanently kill the recovery loop. Do not
                # log exceptions containing DSNs, payloads or customer credentials.
                logger.warning("ContextDB lifecycle sweep failed; retrying")
                await asyncio.sleep(1)

    async def execute(self, operation: ManagementOperation) -> None:
        try:
            # Cancel coroutine work when ownership is lost. Metadata completion
            # is fenced; a migration thread itself is not cancellable (see below).
            async with asyncio.TaskGroup() as group:
                heartbeat = group.create_task(self._heartbeat(operation))
                try:
                    completed = await self._apply(operation)
                    if completed:
                        await self.repository.complete_operation(operation)
                finally:
                    heartbeat.cancel()
        except asyncio.CancelledError:
            # Leave the durable lease for another replica after expiry. Cancelling
            # a migration thread cannot undo DDL that already committed.
            raise
        except Exception:
            logger.warning("ContextDB workspace operation failed: %s", operation.operation_id)
            await self.repository.fail_operation(operation)

    async def _apply(self, operation: ManagementOperation) -> bool:
        admission_id = secrets.token_hex(16)
        await self.repository.register_lifecycle_admission(operation, admission_id)
        try:
            return await self._apply_guarded(operation, admission_id)
        finally:
            # _apply_guarded drains shielded migration threads before returning.
            # A process crash cannot run this cleanup and deliberately leaves the
            # persisted barrier, blocking physical schema/name reuse.
            await self.repository.finish_admission(admission_id, operation.lease_token or "", interrupted=False)

    async def _apply_guarded(self, operation: ManagementOperation, admission_id: str) -> bool:
        from hindsight_api.engine.memory_engine import _current_schema

        if not operation.lease_token or not await self.repository.operation_is_owned(
            operation.operation_id, operation.lease_token, operation.action, operation.workspace_id
        ):
            raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
        workspace = await self.repository.operation_workspace(operation)
        await self.repository.verify_workspace_schema(workspace.schema_name)
        token = _current_schema.set(workspace.schema_name)
        context = RequestContext(
            internal=True,
            tenant_id=workspace.workspace_id,
            allowed_bank_ids=[workspace.bank_id],
            extra_headers={
                "ctxdb-internal-purpose": operation.action,
                "ctxdb-operation-id": operation.operation_id,
                "ctxdb-lease-token": operation.lease_token,
            },
        )
        try:
            if operation.action == "create_workspace":
                migration = asyncio.create_task(self.context.run_migration(workspace.schema_name))
                try:
                    await asyncio.shield(migration)
                except asyncio.CancelledError as cancelled:
                    # asyncio.to_thread keeps running after cancellation. Retain
                    # coroutine alive until it really exits. No long metadata
                    # transaction may span DDL: CREATE INDEX CONCURRENTLY can
                    # wait for its old snapshot and deadlock provisioning.
                    # Native migrations keep their own schema serialization;
                    # renew below prevents an expired owner from creating Bank.
                    while not migration.done():
                        # A second shutdown/lease-loss cancellation must not
                        # make stop() return while this migration still runs.
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await asyncio.shield(migration)
                    # Retrieve a possible migration exception, then preserve
                    # cancellation rather than continuing to Bank creation.
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        migration.result()
                    raise cancelled
                if not await self.repository.renew_operation(operation):
                    raise ServiceError(409, "lease_lost", "Workspace operation lease was lost")
                with initializing_bank(
                    workspace.schema_name, workspace.bank_id, operation.operation_id, operation.lease_token
                ):
                    await self.memory.update_bank(workspace.bank_id, name=workspace.name, request_context=context)
                    if await self.memory.get_bank_profile(workspace.bank_id, request_context=context) is None:
                        raise RuntimeError("Bank provisioning verification failed")
            else:
                # Legacy deleted tombstones are scheduled for physical reclaim
                # by migration. They no longer admit native engine calls.
                bank_present = workspace.state != "deleted" and (
                    await self.repository.bank_table_exists(workspace.schema_name)
                    and await self.memory.get_bank_profile(workspace.bank_id, request_context=context) is not None
                )
                if bank_present:
                    # One COUNT snapshot, not separate pending/processing reads:
                    # a processing parent can enqueue a child between two reads.
                    page = OperationCount.model_validate(
                        await self.memory.list_operations(
                            workspace.bank_id,
                            statuses=["pending", "processing"],
                            limit=1,
                            offset=0,
                            request_context=context,
                        )
                    )
                    if page.total:
                        await self.repository.defer_operation(operation, reason="waiting_for_tasks")
                        return False
                # Check committed admissions AFTER the queue snapshot: a parent
                # may finish while its continuation has already registered but
                # has not yet committed a child row. In a deleting space no new
                # queue work starts without such a processing parent.
                # Session loss/crashes retain these barriers; never time them out.
                if await self.repository.has_outstanding_admissions(workspace.workspace_id, excluding=admission_id):
                    await self.repository.defer_operation(operation, reason="waiting_for_admissions")
                    return False
                if bank_present:
                    await self.memory.delete_bank(workspace.bank_id, request_context=context)
                # Core intentionally treats file cleanup as best effort. A whole
                # workspace must not report success while its registered prefix
                # could not be reclaimed; retry remains possible without a bank row.
                from hindsight_api.engine.storage import PostgreSQLFileStorage, bank_storage_prefix

                storage = self.memory._file_storage
                if not isinstance(storage, PostgreSQLFileStorage) or await self.repository.file_table_exists(
                    workspace.schema_name
                ):
                    await storage.delete_prefix(bank_storage_prefix(workspace.bank_id, workspace.schema_name))
            return True
        finally:
            _current_schema.reset(token)
