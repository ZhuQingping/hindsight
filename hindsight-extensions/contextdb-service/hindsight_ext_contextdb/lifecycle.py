"""Synchronous workspace management using native Bank lifecycle semantics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hindsight_api.extensions.context import ExtensionContext

from .authorization import workspace_management
from .models import BusinessPrincipal, ServiceError, Workspace, WorkspaceCreate
from .repository import Repository

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine

logger = logging.getLogger(__name__)


class Lifecycle:
    def __init__(self, repository: Repository, memory: MemoryEngine, context: ExtensionContext) -> None:
        self.repository = repository
        self.memory = memory
        self.context = context

    async def _failed(self, workspace: Workspace) -> None:
        # Keep the original error even when PG is unavailable. Cancellation is
        # intentionally not caught: creating/deleting then means result unknown.
        try:
            await self.repository.fail_workspace(workspace)
        except Exception:
            logger.warning("Unable to record failed workspace state: %s", workspace.workspace_id)

    async def create(self, principal: BusinessPrincipal, body: WorkspaceCreate, request_id: str) -> Workspace:
        workspace = await self.repository.create_workspace(principal, body, request_id)
        try:
            await self.repository.verify_workspace_schema(workspace.schema_name)
            # Native migrations own their DDL connections. No metadata transaction
            # or shielded executor is held while awaiting their native behavior.
            with workspace_management(workspace, "create_workspace") as context:
                await self.context.run_migration(workspace.schema_name)
                await self.memory.update_bank(workspace.bank_id, name=workspace.name, request_context=context)
                if await self.memory.get_bank_profile(workspace.bank_id, request_context=context) is None:
                    raise ServiceError(503, "workspace_initialization_failed", "Workspace Bank initialization failed")
            return await self.repository.finish_workspace_creation(workspace, principal, request_id)
        except Exception:
            await self._failed(workspace)
            raise

    async def delete(
        self, principal: BusinessPrincipal, bank_id: str, request_id: str, *, expected_id: str, expected_version: int
    ) -> None:
        workspace = await self.repository.delete_workspace(
            principal, bank_id, request_id, expected_id=expected_id, expected_version=expected_version
        )
        try:
            await self.repository.verify_workspace_schema(workspace.schema_name)
            # A failed migration may have only part of the native schema. An
            # absent Bank requires no native cleanup; drop only verified residue.
            if await self.repository.bank_exists(workspace):
                with workspace_management(workspace, "delete_workspace") as context:
                    await self.memory.delete_bank(workspace.bank_id, request_context=context)
            # Native delete owns its best-effort file/index semantics. Do not add
            # a stricter second file deletion or wait for native background work.
            await self.repository.finish_workspace_deletion(workspace, principal, request_id)
        except Exception:
            await self._failed(workspace)
            raise
