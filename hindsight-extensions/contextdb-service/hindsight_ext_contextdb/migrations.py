"""Atomically install the first released metadata schema or validate its reuse.

Unreleased development catalogs are rejected without modification. Future
released versions must add explicit, ordered migrations from this v1 baseline.
Native workspace schemas and their Alembic history are never modified here.
"""

from pathlib import Path

import asyncpg

from . import METADATA_FORMAT_ID, METADATA_VERSION
from .bootstrap import initialize_administrator
from .database_checks import verify_background_write_policy, verify_binding, verify_format

ROOT = Path(__file__).parent


async def migrate_connection(
    conn: asyncpg.Connection,
    instance_id: str,
    cloud_tenant_id: str,
    *,
    pepper: str,
    admin_secret: str,
) -> None:
    """Initialize offline; existing deployments retain credentials and identity."""
    if len(pepper) < 32:
        raise ValueError("A deployment pepper of at least32 characters is required")
    async with conn.transaction():
        if not await conn.fetchval("SELECT to_regnamespace('ctxdb_meta')"):
            await conn.execute((ROOT / "schema.sql").read_text())
            await conn.execute(
                "INSERT INTO ctxdb_meta.deployment_info(instance_id,cloud_tenant_id,metadata_version,format_id) VALUES($1,$2,$3,$4)",
                instance_id,
                cloud_tenant_id,
                METADATA_VERSION,
                METADATA_FORMAT_ID,
            )
        else:
            try:
                await verify_format(conn)
            except RuntimeError as error:
                raise ValueError(
                    "Unsupported ContextDB metadata: use a new database for the first-release v1 schema; "
                    "development schemas are not automatically upgraded or renumbered"
                ) from error
            await verify_binding(conn, instance_id, cloud_tenant_id)
            if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM ctxdb_meta.users WHERE role='admin')"):
                raise ValueError("System administrator is missing; use controlled offline recovery")
        await initialize_administrator(conn, admin_secret, pepper)
        await verify_format(conn)
        await verify_binding(conn, instance_id, cloud_tenant_id)
        await verify_background_write_policy(conn)
