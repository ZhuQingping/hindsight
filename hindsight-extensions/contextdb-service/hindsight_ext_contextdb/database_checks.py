"""Shared metadata checks for offline initialization and online startup.

Callers retain ownership of their connection, transaction and pool lifetime.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import asyncpg

from . import METADATA_FORMAT_ID, METADATA_VERSION
from .models import ServiceError


@contextmanager
def metadata_errors() -> Iterator[None]:
    """Hide extension metadata diagnostics; callers keep native execution outside."""
    try:
        yield
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
        raise ServiceError(503, "metadata_unavailable", "Management metadata unavailable") from None


async def verify_background_write_policy(reader: asyncpg.Pool | asyncpg.Connection) -> None:
    # API policy disallows webhook creation, but an older deployment may
    # already have enabled rows. Reject before workers can enqueue delivery
    # payloads outside the supported first-release diagnostic policy.
    for workspace in await reader.fetch("SELECT schema_name FROM ctxdb_meta.workspaces"):
        schema = workspace["schema_name"].replace('"', '""')
        table = f'"{schema}".webhooks'
        if await reader.fetchval("SELECT to_regclass($1)", table) and await reader.fetchval(
            f"SELECT EXISTS(SELECT 1 FROM {table} WHERE enabled)"
        ):
            raise ValueError(
                "Disable existing native webhooks with the old version before ContextDB startup or upgrade"
            )
        banks = f'"{schema}".banks'
        if await reader.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema=$1 AND table_name='banks' AND column_name='config')",
            workspace["schema_name"],
        ):
            if await reader.fetchval(
                f"SELECT EXISTS(SELECT 1 FROM {banks} WHERE config->'audit_log_enabled'='true'::jsonb)"
            ):
                raise ValueError("Disable existing native Bank audit logging before ContextDB startup or upgrade")


async def verify_binding(reader: asyncpg.Pool | asyncpg.Connection, instance_id: str, cloud_tenant_id: str) -> None:
    bindings = await reader.fetch("SELECT instance_id,cloud_tenant_id FROM ctxdb_meta.deployment_info")
    if (
        len(bindings) != 1
        or bindings[0]["instance_id"] != instance_id
        or bindings[0]["cloud_tenant_id"] != cloud_tenant_id
    ):
        raise RuntimeError("ContextDB database belongs to another deployment; check instance and tenant IDs")


async def verify_format(reader: asyncpg.Pool | asyncpg.Connection) -> None:
    marker = await reader.fetchval("SELECT to_regclass('ctxdb_meta.deployment_info')")
    if marker is None:
        raise RuntimeError("Unsupported ContextDB metadata schema; run the offline deployment migration first")
    versions = await reader.fetch("SELECT singleton,metadata_version,format_id FROM ctxdb_meta.deployment_info")
    if (
        len(versions) != 1
        or not versions[0]["singleton"]
        or versions[0]["metadata_version"] != METADATA_VERSION
        or versions[0]["format_id"] != METADATA_FORMAT_ID
    ):
        raise RuntimeError("Unsupported ContextDB metadata schema; run the offline deployment migration first")
    if await reader.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='ctxdb_meta' AND table_name='workspaces' AND column_name IN ('name','name_key'))"
    ):
        raise RuntimeError("Unsupported development workspace layout; provision a fresh first-release database")
    if await reader.fetchval(
        "SELECT to_regclass('ctxdb_meta.management_operations') IS NOT NULL OR to_regclass('ctxdb_meta.request_admissions') IS NOT NULL"
    ):
        raise RuntimeError("Unsupported development lifecycle layout; provision a fresh first-release database")
