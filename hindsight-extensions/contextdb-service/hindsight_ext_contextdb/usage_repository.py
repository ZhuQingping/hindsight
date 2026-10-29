"""Plugin-owned usage storage and bounded cleanup, independent of request credentials."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
from time import monotonic
from typing import Literal
from uuid import UUID

import asyncpg
from pydantic import BaseModel, field_validator

from .models import ServiceError
from .routing import bank_target

ObjectType = Literal["memory", "knowledge_page"]


@dataclass(frozen=True)
class UsageTarget:
    workspace_id: str
    bank_id: str
    schema_name: str

    def __post_init__(self) -> None:
        if (
            re.fullmatch(r"[0-9a-f]{32}", self.workspace_id) is None
            or re.fullmatch(r"[a-z0-9][a-z0-9_]{0,53}", self.bank_id) is None
            or self.schema_name != f"ctxdb_ws_{self.bank_id}"
        ):
            raise ValueError("Invalid usage workspace binding")

    def table(self, name: str = "ctxdb_usage_stats") -> str:
        if re.fullmatch(r"[a-z_][a-z0-9_]*", name) is None:
            raise ValueError("Invalid usage table name")
        return f'"{self.schema_name}"."{name}"'


@dataclass(frozen=True)
class UsageDelta:
    object_type: ObjectType
    object_id: str
    count: int
    last_recalled_at: datetime

    def __post_init__(self) -> None:
        if self.object_type not in {"memory", "knowledge_page"} or not 0 < len(self.object_id) <= 64:
            raise ValueError("Invalid usage object")
        if self.object_type == "memory" and str(UUID(self.object_id)) != self.object_id:
            raise ValueError("Memory usage requires a canonical UUID")
        if self.count <= 0 or self.last_recalled_at.tzinfo is None:
            raise ValueError("Usage requires a positive count and timezone-aware event time")


class UsageItem(BaseModel):
    object_id: str
    recall_count: int
    last_recalled_at: datetime | None

    @field_validator("last_recalled_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("Usage timestamps must include a timezone")
        return value


@dataclass(frozen=True, order=True)
class _Position:
    object_type: str = ""
    object_id: str = ""


@dataclass
class _Sweep:
    target: UsageTarget
    position: _Position = _Position()
    upper: _Position | None = None


def _unavailable() -> ServiceError:
    return ServiceError(503, "usage_unavailable", "Recall usage statistics are unavailable")


async def provision_usage_tables(conn: asyncpg.Connection, schema: str) -> None:
    """Called only on the controlled per-workspace migration path, never on a request."""
    # CLI upgrade also calls this without an enclosing migration transaction.
    # Keep directory validation and DDL atomic in both entry paths.
    async with conn.transaction():
        row = await conn.fetchrow(
            "SELECT workspace_id,bank_id,schema_name FROM ctxdb_meta.workspaces "
            "WHERE schema_name=$1 AND state IN ('creating','active') FOR SHARE",
            schema,
        )
        if row is None:
            raise ServiceError(409, "usage_workspace", "Usage requires a registered workspace schema")
        target = UsageTarget(**dict(row))
        ddl = files("hindsight_ext_contextdb").joinpath("usage_schema.sql").read_text()
        await conn.execute(ddl.replace("{schema}", f'"{target.schema_name}"'))


async def upgrade_usage_table(conn: asyncpg.Connection, schema: str) -> None:
    """Explicit offline migration; normal provisioning must never drop a live column."""
    async with conn.transaction():
        await conn.execute("SET LOCAL lock_timeout='1s'; SET LOCAL statement_timeout='30s'")
        row = await conn.fetchrow(
            "SELECT workspace_id,bank_id,schema_name FROM ctxdb_meta.workspaces "
            "WHERE schema_name=$1 AND state IN ('creating','active') FOR SHARE",
            schema,
        )
        if row is None:
            raise ServiceError(409, "usage_workspace", "Usage requires a registered workspace schema")
        target = UsageTarget(**dict(row))
        if await conn.fetchval("SELECT to_regclass($1)", target.table()) is not None:
            # Serialize inspection and DDL. The operator must already have stopped
            # and drained API/Worker; the short timeout bounds an accidental live run.
            await conn.execute(f"LOCK TABLE {target.table()} IN ACCESS EXCLUSIVE MODE")
            columns = await conn.fetch(
                "SELECT a.attname FROM pg_index i "
                "CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,position) "
                "JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum "
                "WHERE i.indrelid=$1::regclass AND i.indisprimary ORDER BY k.position",
                target.table(),
            )
            primary = [column["attname"] for column in columns]
            legacy = ["workspace_id", "bank_id", "object_type", "object_id"]
            current = ["bank_id", "object_type", "object_id"]
            has_identity = await conn.fetchval(
                "SELECT EXISTS(SELECT FROM pg_attribute WHERE attrelid=$1::regclass "
                "AND attname='workspace_id' AND NOT attisdropped)",
                target.table(),
            )
            if primary not in (legacy, current) or (primary == legacy) != has_identity:
                raise ServiceError(409, "usage_schema", "Unexpected usage primary key; inspect before upgrading")
            if primary == legacy:
                mismatched = await conn.fetchval(
                    f"SELECT EXISTS(SELECT FROM {target.table()} "
                    "WHERE workspace_id IS DISTINCT FROM $1 OR bank_id IS DISTINCT FROM $2)",
                    target.workspace_id,
                    target.bank_id,
                )
                if mismatched:
                    raise ServiceError(409, "usage_identity_mismatch", "Usage contains another workspace identity")
                # A valid legacy primary key plus one checked identity guarantees
                # the new key cannot collapse rows. Never merge foreign generations.
                await conn.execute(
                    f"ALTER TABLE {target.table()} DROP CONSTRAINT ctxdb_usage_stats_pkey, "
                    "DROP COLUMN workspace_id, "
                    "ADD CONSTRAINT ctxdb_usage_stats_pkey PRIMARY KEY (bank_id,object_type,object_id)"
                )
        await provision_usage_tables(conn, schema)


class UsageRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool
        self._page: list[UsageTarget] = []
        self._directory_after = ""
        self._sweep: _Sweep | None = None
        self.last_sweep_completed: datetime | None = None

    @staticmethod
    async def _bound(conn: asyncpg.Connection, target: UsageTarget) -> bool:
        # Hold this row through the write: deletion changes its state before
        # reusing a schema name, so an old event cannot race into the successor.
        return bool(
            await conn.fetchval(
                "SELECT true FROM ctxdb_meta.workspaces "
                "WHERE workspace_id=$1 AND bank_id=$2 AND schema_name=$3 AND state='active' FOR SHARE",
                target.workspace_id,
                target.bank_id,
                target.schema_name,
            )
        )

    @staticmethod
    async def _timeouts(conn: asyncpg.Connection) -> None:
        await conn.execute("SET LOCAL lock_timeout='100ms'; SET LOCAL statement_timeout='900ms'")

    async def write(self, target: UsageTarget, entries: list[UsageDelta]) -> bool:
        """One attempt only; the caller must not replay an uncertain commit."""
        if len(entries) > 500:
            raise ValueError("Usage batch exceeds 500 objects")
        if not entries:
            return True
        combined: dict[_Position, UsageDelta] = {}
        for entry in entries:
            key = _Position(entry.object_type, entry.object_id)
            old = combined.get(key)
            combined[key] = UsageDelta(
                entry.object_type,
                entry.object_id,
                entry.count + (old.count if old else 0),
                max(entry.last_recalled_at, old.last_recalled_at) if old else entry.last_recalled_at,
            )
        ordered = [combined[key] for key in sorted(combined)]
        async with asyncio.timeout(1), self.pool.acquire(timeout=0.1) as conn, conn.transaction():
            await self._timeouts(conn)
            if not await self._bound(conn, target):
                return False
            await conn.execute(
                f"INSERT INTO {target.table()} AS stats "
                "(bank_id,object_type,object_id,recall_count,last_recalled_at) "
                "SELECT $1,u.* FROM unnest($2::text[],$3::text[],$4::bigint[],$5::timestamptz[]) "
                "AS u(object_type,object_id,recall_count,last_recalled_at) "
                "ON CONFLICT (bank_id,object_type,object_id) DO UPDATE SET "
                "recall_count=stats.recall_count+EXCLUDED.recall_count, "
                "last_recalled_at=GREATEST(stats.last_recalled_at,EXCLUDED.last_recalled_at)",
                target.bank_id,
                [entry.object_type for entry in ordered],
                [entry.object_id for entry in ordered],
                [entry.count for entry in ordered],
                [entry.last_recalled_at for entry in ordered],
            )
        return True

    async def reset(self, target: UsageTarget) -> None:
        """Offline post-restore reset; callers must stop and drain API/Worker first."""
        async with asyncio.timeout(1), self.pool.acquire(timeout=0.1) as conn, conn.transaction():
            await self._timeouts(conn)
            if not await self._bound(conn, target):
                raise ServiceError(409, "usage_workspace", "Usage workspace binding changed")
            # A native schema restore may contain another generation's UUID or
            # Bank. Clear the whole plugin table before reopening this schema.
            await conn.execute(f"TRUNCATE TABLE {target.table()}")

    @staticmethod
    async def _existing(
        conn: asyncpg.Connection,
        target: UsageTarget,
        object_type: ObjectType,
        ids: list[str],
        *,
        include_archive: bool = True,
    ) -> set[str]:
        if not ids:
            return set()
        if object_type == "knowledge_page":
            return {
                row["id"]
                for row in await conn.fetch(
                    f"SELECT id FROM {target.table('knowledge_pages')} "
                    "WHERE bank_id=$1 AND kind='page' AND id=ANY($2::text[])",
                    target.bank_id,
                    ids,
                )
            }
        from hindsight_api.engine.memories import get_memories

        store = get_memories()
        # PostgresMemories uses the schema ContextVar rather than our callback.
        # Background jobs therefore need their own explicit bank_target scope.
        with bank_target(target.bank_id, schema_name=target.schema_name):
            present = await store.live_memory_ids(
                conn=conn, fq_table=target.table, bank_id=target.bank_id, unit_ids=ids
            )
            if include_archive:
                for unit_id in ids:
                    if unit_id not in present and await UsageRepository._archived(conn, target, unit_id):
                        present.add(unit_id)
        return present

    @staticmethod
    async def _archived(conn: asyncpg.Connection, target: UsageTarget, unit_id: str) -> bool:
        from hindsight_api.engine.memories import get_memories

        with bank_target(target.bank_id, schema_name=target.schema_name):
            return (
                await get_memories().get_archived_memory(
                    conn=conn, fq_table=target.table, bank_id=target.bank_id, unit_id=unit_id
                )
                is not None
            )

    async def read(self, target: UsageTarget, object_type: ObjectType, ids: list[str]) -> list[UsageItem]:
        if object_type not in {"memory", "knowledge_page"} or len(ids) > 100:
            raise ValueError("Invalid usage lookup")
        unique = list(dict.fromkeys(ids))
        if any(not 0 < len(key) <= 64 for key in unique):
            raise ValueError("Invalid usage object identity")
        if object_type == "memory" and any(str(UUID(key)) != key for key in unique):
            raise ValueError("Memory usage lookup requires canonical UUIDs")
        try:
            async with (
                asyncio.timeout(1),
                self.pool.acquire(timeout=0.1) as conn,
                conn.transaction(isolation="repeatable_read"),
            ):
                await self._timeouts(conn)
                if not await self._bound(conn, target):
                    raise ServiceError(404, "workspace_not_found", "Workspace not found")
                # Query even for an empty/unknown ID set so a missing table is
                # never reported as a healthy zero-count statistics service.
                rows = await conn.fetch(
                    f"SELECT object_id,recall_count,last_recalled_at FROM {target.table()} "
                    "WHERE bank_id=$1 AND object_type=$2 AND object_id=ANY($3::text[])",
                    target.bank_id,
                    object_type,
                    unique,
                )
                present = await self._existing(conn, target, object_type, unique)
                found = {row["object_id"]: UsageItem(**dict(row)) for row in rows}
                return [
                    found.get(key, UsageItem(object_id=key, recall_count=0, last_recalled_at=None))
                    for key in unique
                    if key in present
                ]
        except (asyncpg.PostgresError, OSError, TimeoutError):
            raise _unavailable() from None

    async def _next_target(self, conn: asyncpg.Connection) -> UsageTarget | None:
        if not self._page:
            rows = await conn.fetch(
                "SELECT workspace_id,bank_id,schema_name FROM ctxdb_meta.workspaces "
                "WHERE state='active' AND workspace_id>$1 ORDER BY workspace_id LIMIT 32",
                self._directory_after,
            )
            if not rows:
                self._directory_after = ""
                self.last_sweep_completed = datetime.now(timezone.utc)
                return None
            self._page = [UsageTarget(**dict(row)) for row in rows]
            self._directory_after = self._page[-1].workspace_id
        return self._page.pop(0)

    async def cleanup(self) -> None:
        try:
            await self._cleanup()
        except (asyncpg.UndefinedTableError, asyncpg.InvalidSchemaNameError, asyncpg.InsufficientPrivilegeError):
            # A permanently broken space must not starve later healthy spaces.
            # Retry it on the next directory cycle; transient failures instead
            # keep their exact position and resume the current slice.
            self._sweep = None
            raise

    async def _cleanup(self) -> None:
        """One bounded slice; retain only one workspace cursor plus one directory page."""
        async with (
            asyncio.timeout(1),
            self.pool.acquire(timeout=0.1) as conn,
            conn.transaction(isolation="repeatable_read"),
        ):
            await self._timeouts(conn)
            if self._sweep is None:
                target = await self._next_target(conn)
                if target is None:
                    return
                # Selecting the directory entry is not object-scan progress.
                # Retain it on failure so a transient error cannot skip a space.
                self._sweep = _Sweep(target)
                sweep = _Sweep(target)
            else:
                # Never advance in-memory progress before the transaction commits.
                sweep = _Sweep(self._sweep.target, self._sweep.position, self._sweep.upper)
            target = sweep.target
            if not await self._bound(conn, target):
                self._sweep = None
                return
            if sweep.upper is None:
                upper = await conn.fetchrow(
                    f"SELECT object_type,object_id FROM {target.table()} WHERE bank_id=$1 "
                    "ORDER BY object_type DESC,object_id DESC LIMIT 1",
                    target.bank_id,
                )
                if upper is None:
                    self._sweep = None
                    return
                sweep.upper = _Position(**dict(upper))
            rows = await conn.fetch(
                f"SELECT object_type,object_id FROM {target.table()} WHERE bank_id=$1 "
                "AND (object_type,object_id)>($2,$3) AND (object_type,object_id)<=($4,$5) "
                "ORDER BY object_type,object_id LIMIT 20",
                target.bank_id,
                sweep.position.object_type,
                sweep.position.object_id,
                sweep.upper.object_type,
                sweep.upper.object_id,
            )
            deadline = monotonic() + 0.65  # Leave room to delete confirmed rows and commit.
            present: dict[str, set[str]] = {}
            for kind in ("memory", "knowledge_page"):
                present[kind] = await self._existing(
                    conn,
                    target,
                    kind,
                    [row["object_id"] for row in rows if row["object_type"] == kind],
                    include_archive=False,
                )
            checked: list[_Position] = []
            missing: list[_Position] = []
            for row in rows:
                if monotonic() >= deadline:
                    break
                position = _Position(**dict(row))
                exists = position.object_id in present[position.object_type]
                if not exists and position.object_type == "memory":
                    exists = await self._archived(conn, target, position.object_id)
                checked.append(position)
                if not exists:
                    missing.append(position)
            if missing:
                await conn.execute(
                    f"DELETE FROM {target.table()} WHERE bank_id=$1 "
                    "AND (object_type,object_id) IN (SELECT * FROM unnest($2::text[],$3::text[]))",
                    target.bank_id,
                    [key.object_type for key in missing],
                    [key.object_id for key in missing],
                )
            if checked:
                sweep.position = checked[-1]
            # Equality is sufficient and does not assume Python ordering equals
            # the database collation for imported knowledge-page identities.
            finished = not rows or (bool(checked) and sweep.position == sweep.upper)
        self._sweep = None if finished else sweep
