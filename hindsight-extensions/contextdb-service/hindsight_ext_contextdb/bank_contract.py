"""Map native engine results without changing the native Bank wire models.

Import this module after the host HTTP module has finished constructing its
extension slots, not while those slots are imported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hindsight_api.api.http import (
    BankProfileResponse,
    CreateBankRequest,
    DeleteResponse,
    DispositionTraits,
    load_default_bank_template_manifest,
)
from pydantic import BaseModel, Field, ValidationError

from .models import NativeDeletion, WorkspaceDescription

if TYPE_CHECKING:
    from hindsight_api import MemoryEngine


class ManagedBankRequest(CreateBankRequest):
    # Management description is independent of the model's mission/config.
    description: WorkspaceDescription = Field(
        default="", description="Management description, accepted only for a new Bank; independent of mission."
    )


async def validate_creation_config(memory: MemoryEngine, bank_id: str, request: CreateBankRequest) -> None:
    """Reject input errors before allocating a UUID or schema, without target reads."""
    updates = request.get_config_updates()
    if not updates:
        return
    resolver = memory._config_resolver
    assert resolver is not None
    try:
        manifest = load_default_bank_template_manifest()
    except (ValueError, ValidationError):
        # Match native creation: malformed server templates are ignored, rather
        # than making an otherwise valid client request fail at this boundary.
        manifest = None
    projected: dict[str, Any] = {}
    defaults = manifest.bank.get_config_updates() if manifest and manifest.bank else {}
    if defaults:
        projected = (
            await resolver.validate_bank_config_updates(
                bank_id, defaults, projected_bank_overrides={}, check_permissions=False
            )
        ).updates
    # Admin auth has already succeeded, but there is no target identity yet.
    # Only preflight semantics here; update_bank retains all permission and
    # write-time checks. ContextDB has no tenant-level config overrides.
    # Explicit projection prevents the resolver from loading a nonexistent Bank.
    await resolver.validate_bank_config_updates(
        bank_id, updates, projected_bank_overrides=projected, check_permissions=False
    )


class NativeProfile(BaseModel):
    name: str
    disposition: DispositionTraits
    mission: str | None = None


def profile_response(bank_id: str, result: object) -> BankProfileResponse:
    profile = NativeProfile.model_validate(result)
    mission = profile.mission or ""
    return BankProfileResponse(
        bank_id=bank_id, name=profile.name, disposition=profile.disposition, mission=mission, background=mission
    )


def deletion_response(bank_id: str, counts: NativeDeletion) -> DeleteResponse:
    return DeleteResponse(
        success=True,
        message=f"Bank '{bank_id}' and all associated data deleted successfully",
        deleted_count=counts.memory_units_deleted + counts.entities_deleted + counts.documents_deleted,
    )
