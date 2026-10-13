"""Shared deployment settings for the three independent extension slots."""

from __future__ import annotations

import ipaddress
import json
import os
from typing import Protocol, cast

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .repository import Repository
from .security import ControlKey, ControlPlaneKeyAuth


class ControlKeyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_id: str = Field(pattern="^[0-9a-f]{32}$")
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class Settings(BaseModel):
    instance_id: str = Field(min_length=1, max_length=128)
    cloud_tenant_id: str = Field(min_length=1, max_length=128)
    pepper: str = Field(min_length=32, repr=False)
    control_keys: list[ControlKeyConfig] = Field(min_length=1, max_length=2)
    control_networks: list[str] = Field(default_factory=lambda: ["127.0.0.1/32", "::1/128"], min_length=1)

    @field_validator("control_networks")
    @classmethod
    def validate_control_networks(cls, values: list[str]) -> list[str]:
        return [str(ipaddress.ip_network(value.strip())) for value in values]

    @classmethod
    def from_environment(cls) -> Settings:
        # An isolated migration child can survive a killed API parent and its
        # metadata session lock. Support that mode only after core exposes child
        # termination/fencing; fail closed rather than promise fenced teardown.
        if os.environ.get("HINDSIGHT_API_MIGRATION_ISOLATION", "false").strip().lower() == "true":
            raise ValueError("ContextDB lifecycle currently requires MIGRATION_ISOLATION=false")
        # A shared legacy MCP token wins before TenantExtension.authenticate_mcp.
        # Reject it rather than silently converting a scoped deployment to shared auth.
        if os.environ.get("HINDSIGHT_API_MCP_AUTH_TOKEN"):
            raise ValueError("ContextDB requires dynamic MCP member authentication; remove MCP_AUTH_TOKEN")
        raw = os.environ.get("CONTEXTDB_CONTROL_KEYS", "[]")
        try:
            entries = json.loads(raw)
            return cls(
                instance_id=os.environ.get("CONTEXTDB_INSTANCE_ID", ""),
                cloud_tenant_id=os.environ.get("CONTEXTDB_CLOUD_TENANT_ID", ""),
                pepper=os.environ.get("CONTEXTDB_KEY_PEPPER", ""),
                control_keys=entries,
                control_networks=os.environ.get("CONTEXTDB_CONTROL_NETWORKS", "127.0.0.1/32,::1/128").split(","),
            )
        except (ValueError, TypeError):
            # Pydantic errors may include the raw input. Never echo deployment
            # credentials when an operator pastes a startup error into a ticket.
            raise ValueError(
                "Invalid ContextDB deployment settings; check IDs, pepper and control Key digests"
            ) from None

    def control_auth(self) -> ControlPlaneKeyAuth:
        return ControlPlaneKeyAuth(
            self.cloud_tenant_id,
            [ControlKey(item.key_id, bytes.fromhex(item.sha256)) for item in self.control_keys],
        )


class PoolOwner(Protocol):
    async def _get_pool(self) -> asyncpg.Pool: ...


async def repository_for(engine: object, settings: Settings) -> Repository:
    # HttpExtension receives the engine, but ExtensionContext has no public pool
    # accessor. Keep this unavoidable host-private adapter in one place, rather
    # than exposing new core APIs or creating a second per-request connection pool.
    pool = await cast(PoolOwner, engine)._get_pool()
    return Repository(pool, settings.instance_id, settings.cloud_tenant_id, settings.pepper)
