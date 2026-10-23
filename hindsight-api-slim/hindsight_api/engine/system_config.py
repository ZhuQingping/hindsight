"""Persist and load file-storage configuration from the database.

A thin key-value store (``ctxdb_meta.system_config`` table) backs the runtime
file-storage config so changes made through the admin API survive process
restarts.

The table is created on demand with ``CREATE TABLE IF NOT EXISTS`` so no
migration is needed — the first read or write after startup brings it into
existence. The ``ctxdb_meta`` schema is created alongside it if missing, so
this works even before the ContextDB extension has bootstrapped.
"""

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

#: Key under which the file-storage config blob is stored.
CONFIG_KEY = "file_storage_config"

#: The config fields that are persisted (must match config.py's
#: _FILE_STORAGE_CONFIG_FIELDS minus the ``file_storage_`` prefix).
_PERSISTED_FIELDS = (
    "file_storage_type",
    "file_storage_s3_bucket",
    "file_storage_s3_region",
    "file_storage_s3_endpoint",
    "file_storage_s3_access_key_id",
    "file_storage_s3_secret_access_key",
)

#: Fields whose values are secrets and should never be logged.
_SECRET_FIELDS = frozenset(
    {
        "file_storage_s3_access_key_id",
        "file_storage_s3_secret_access_key",
    }
)


async def _ensure_table(conn: "asyncpg.Connection") -> None:
    """Create the ctxdb_meta.system_config table if it does not exist yet."""
    await conn.execute(
        """
        CREATE SCHEMA IF NOT EXISTS ctxdb_meta;
        CREATE TABLE IF NOT EXISTS ctxdb_meta.system_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
        """
    )


async def load_file_storage_config(pool: "asyncpg.Pool") -> dict[str, str | None] | None:
    """Load persisted file-storage config from the database.

    Returns ``None`` when no row exists (first boot, or never configured via API).
    """
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        row = await conn.fetchrow(
            "SELECT value FROM ctxdb_meta.system_config WHERE key = $1", CONFIG_KEY
        )
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt file_storage_config in ctxdb_meta.system_config, ignoring")
        return None


async def save_file_storage_config(
    pool: "asyncpg.Pool", config: dict[str, str | None]
) -> None:
    """Persist file-storage config to the database (upsert).

    ``config`` is a full snapshot — every persisted field is written, fields set
    to ``None`` clear the value.  Only fields in ``_PERSISTED_FIELDS`` are stored;
    unknown keys are dropped.
    """
    filtered = {k: v for k, v in config.items() if k in _PERSISTED_FIELDS}
    payload = json.dumps(filtered)
    async with pool.acquire() as conn:
        await _ensure_table(conn)
        await conn.execute(
            """
            INSERT INTO ctxdb_meta.system_config (key, value, updated_at)
            VALUES ($1, $2, now())
            ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = now()
            """,
            CONFIG_KEY,
            payload,
        )
    safe = {
        k: ("***" if k in _SECRET_FIELDS and v else v)
        for k, v in filtered.items()
    }
    logger.info("Persisted file storage config: %s", safe)
