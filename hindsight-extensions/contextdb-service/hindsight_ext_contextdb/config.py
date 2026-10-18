"""Shared deployment settings for the independent extension slots."""

from __future__ import annotations

import json
import os
from typing import Protocol, cast

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from .repository import Repository


class Settings(BaseModel):
    instance_id: str = Field(min_length=1, max_length=128)
    cloud_tenant_id: str = Field(min_length=1, max_length=128)
    pepper: str = Field(min_length=32, repr=False)
    model_config = ConfigDict(extra="forbid")
    operation_retention_hours: int = Field(default=168, ge=24, le=8760)

    @classmethod
    def from_environment(cls) -> Settings:
        # Native webhook delivery jobs lack an immutable workspace generation.
        # Do not accept a setting whose jobs our execution fence must reject.
        if os.environ.get("HINDSIGHT_API_WEBHOOK_URL"):
            raise ValueError("ContextDB first release does not support HINDSIGHT_API_WEBHOOK_URL")
        # Best-effort native trace/audit INSERTs are detached from the admitted
        # request. Keep them off until core exposes a generation-aware write
        # scope; ContextDB's transactional management audit is unaffected.
        if os.environ.get("HINDSIGHT_API_LLM_TRACE_ENABLED", "true").lower() != "false":
            raise ValueError("ContextDB requires HINDSIGHT_API_LLM_TRACE_ENABLED=false")
        if os.environ.get("HINDSIGHT_API_AUDIT_LOG_ENABLED", "false").lower() != "false":
            raise ValueError("ContextDB requires HINDSIGHT_API_AUDIT_LOG_ENABLED=false")
        try:
            template = json.loads(os.environ.get("HINDSIGHT_API_DEFAULT_BANK_TEMPLATE") or "{}")
            bank = template.get("bank") or {}
            if bank.get("audit_log_enabled"):
                raise ValueError("Native audit is not supported")
        except (ValueError, AttributeError, TypeError):
            raise ValueError("ContextDB default Bank template must not enable native audit logging") from None
        # An isolated migration child can survive a killed API parent and its
        # metadata session lock. Support that mode only after core exposes child
        # termination/fencing; fail closed rather than promise fenced teardown.
        if os.environ.get("HINDSIGHT_API_MIGRATION_ISOLATION", "false").strip().lower() == "true":
            raise ValueError("ContextDB lifecycle currently requires MIGRATION_ISOLATION=false")
        # A shared legacy MCP token wins before TenantExtension.authenticate_mcp.
        # Reject it rather than silently converting a scoped deployment to shared auth.
        if os.environ.get("HINDSIGHT_API_MCP_AUTH_TOKEN"):
            raise ValueError("ContextDB requires dynamic MCP member authentication; remove MCP_AUTH_TOKEN")
        if (
            os.environ.get("HINDSIGHT_API_MCP_ENABLED", "false").lower() == "true"
            and os.environ.get("HINDSIGHT_API_MCP_EXTENSION") != "hindsight_ext_contextdb.mcp:ContextDBMCPExtension"
        ):
            raise ValueError("ContextDB MCP requires hindsight_ext_contextdb.mcp:ContextDBMCPExtension")
        try:
            return cls(
                instance_id=os.environ.get("CONTEXTDB_INSTANCE_ID", ""),
                cloud_tenant_id=os.environ.get("CONTEXTDB_CLOUD_TENANT_ID", ""),
                pepper=os.environ.get("CONTEXTDB_KEY_PEPPER", ""),
                operation_retention_hours=int(os.environ.get("CONTEXTDB_OPERATION_RETENTION_HOURS", "168")),
            )
        except (ValueError, TypeError):
            # Pydantic errors may include the raw input. Never echo deployment
            # credentials when an operator pastes a startup error into a ticket.
            raise ValueError(
                "Invalid ContextDB deployment settings; check IDs, pepper and operation retention"
            ) from None


class PoolOwner(Protocol):
    async def _get_pool(self) -> asyncpg.Pool: ...


async def repository_for(engine: object, settings: Settings) -> Repository:
    # HttpExtension receives the engine, but ExtensionContext has no public pool
    # accessor. Keep this unavoidable host-private adapter in one place, rather
    # than exposing new core APIs or creating a second per-request connection pool.
    pool = await cast(PoolOwner, engine)._get_pool()
    return Repository(
        pool,
        settings.instance_id,
        settings.cloud_tenant_id,
        settings.pepper,
        operation_retention_hours=settings.operation_retention_hours,
    )
