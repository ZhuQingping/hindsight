"""Synchronous workspace management using native Bank lifecycle semantics."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hindsight_api.extensions.context import ExtensionContext

from .authorization import workspace_management
from .database_checks import metadata_errors
from .models import BusinessPrincipal, NativeDeletion, ServiceError, Workspace, WorkspaceCreate
from .repository import Repository

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine
    from hindsight_api.api.http import BankProfileResponse, CreateBankRequest


@dataclass
class WorkspaceCreated:
    workspace: Workspace
    profile: BankProfileResponse


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

    async def create_bank(
        self,
        principal: BusinessPrincipal,
        bank_id: str,
        request: CreateBankRequest,
        request_id: str,
        *,
        create_only: bool,
        description: str = "",
    ) -> WorkspaceCreated:
        from .bank_contract import validate_creation_config

        await validate_creation_config(self.memory, bank_id, request)
        body = WorkspaceCreate(name=bank_id, description=description)
        with metadata_errors():
            workspace = await self.repository.create_workspace(principal, body, request_id, create_only=create_only)
        try:
            with metadata_errors():
                await self.repository.verify_workspace_schema(workspace.schema_name)
            # Native migrations own their DDL connections. No metadata transaction
            # or shielded executor is held while awaiting their native behavior.
            with workspace_management(workspace, "create_workspace") as context:
                await self.context.run_migration(workspace.schema_name)
                profile = await self.memory.update_bank(
                    workspace.bank_id,
                    name=request.name,
                    config_updates=request.get_config_updates() or None,
                    request_context=context,
                )
                if await self.memory.get_bank_profile(workspace.bank_id, request_context=context) is None:
                    raise ServiceError(503, "workspace_initialization_failed", "Workspace Bank initialization failed")
            # Validate the native result before activating the registered identity.
            from .bank_contract import profile_response

            response = profile_response(workspace.bank_id, profile)
            with metadata_errors():
                active = await self.repository.finish_workspace_creation(workspace, principal, request_id)
            return WorkspaceCreated(active, response)
        except Exception:
            await self._failed(workspace)
            raise

    async def delete(
        self, principal: BusinessPrincipal, bank_id: str, request_id: str, *, expected_id: str, expected_version: int
    ) -> NativeDeletion:
        with metadata_errors():
            workspace = await self.repository.delete_workspace(
                principal, bank_id, request_id, expected_id=expected_id, expected_version=expected_version
            )
        try:
            result = NativeDeletion()
            with metadata_errors():
                await self.repository.verify_workspace_schema(workspace.schema_name)
                bank_exists = await self.repository.bank_exists(workspace)
            # A failed migration may have only part of the native schema. An
            # absent Bank requires no native cleanup; drop only verified residue.
            if bank_exists:
                with workspace_management(workspace, "delete_workspace") as context:
                    result = NativeDeletion.model_validate(
                        await self.memory.delete_bank(workspace.bank_id, request_context=context)
                    )
            # Native delete owns its best-effort file/index semantics. Do not add
            # a stricter second file deletion or wait for native background work.
            with metadata_errors():
                await self.repository.finish_workspace_deletion(workspace, principal, request_id)
            return result
        except Exception:
            await self._failed(workspace)
            raise
