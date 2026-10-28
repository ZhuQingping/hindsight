"""Isolated PostgreSQL verifies plugin usage storage, not memory extraction behaviour."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import asyncpg
import pytest
from hindsight_api.engine.memory_engine import get_current_schema

from hindsight_ext_contextdb.models import ServiceError
from hindsight_ext_contextdb.usage_repository import (
    UsageDelta,
    UsageRepository,
    UsageTarget,
    provision_usage_tables,
)

from .support.identities import ready_workspace


@dataclass
class StoreDouble:
    live: dict[str, set[str]] = field(default_factory=dict)
    archived: dict[str, set[str]] = field(default_factory=dict)
    schemas: list[str] = field(default_factory=list)
    isolations: list[str] = field(default_factory=list)
    calls: int = 0

    async def live_memory_ids(self, *, conn, fq_table, bank_id, unit_ids):
        schema = get_current_schema()
        assert schema == f"ctxdb_ws_{bank_id}"
        self.schemas.append(schema)
        self.isolations.append(await conn.fetchval("SHOW transaction_isolation"))
        self.calls += 1
        return set(unit_ids) & self.live.get(schema, set())

    async def get_archived_memory(self, *, conn, fq_table, bank_id, unit_id):
        schema = get_current_schema()
        assert schema == f"ctxdb_ws_{bank_id}"
        self.schemas.append(schema)
        self.isolations.append(await conn.fetchval("SHOW transaction_isolation"))
        self.calls += 1
        return object() if unit_id in self.archived.get(schema, set()) else None


@pytest.fixture
def store(monkeypatch):
    value = StoreDouble()
    monkeypatch.setattr("hindsight_api.engine.memories.get_memories", lambda: value)
    return value


async def target_for(repository, name="usage") -> UsageTarget:
    workspace = await ready_workspace(repository, name)
    target = UsageTarget(workspace.workspace_id, workspace.bank_id, workspace.schema_name)
    async with repository.pool.acquire() as conn:
        await conn.execute(f'CREATE SCHEMA "{target.schema_name}"')
        # Only a tiny directory double is required for the storage contract.
        # Real native content/lifecycle behaviour belongs to blackbox stories.
        await conn.execute(
            f"CREATE TABLE {target.table('knowledge_pages')} (id text PRIMARY KEY,bank_id text,kind text)"
        )
        await provision_usage_tables(conn, target.schema_name)
    return target


def delta(identity: str, count=1, at=None, kind="knowledge_page") -> UsageDelta:
    return UsageDelta(kind, identity, count, at or datetime.now(timezone.utc))


async def page(repository, target, identity, kind="page"):
    await repository.pool.execute(
        f"INSERT INTO {target.table('knowledge_pages')} VALUES($1,$2,$3)", identity, target.bank_id, kind
    )


async def test_provision_idempotent_registered_schema_and_english_comments(repository):
    target = await target_for(repository)
    async with repository.pool.acquire() as conn:
        await provision_usage_tables(conn, target.schema_name)
        for invalid in ("public", "ctxdb_meta", "ctxdb_ws_unknown", 'x"; DROP SCHEMA public CASCADE; --'):
            with pytest.raises(ServiceError):
                await provision_usage_tables(conn, invalid)
        comments = await conn.fetch(
            "SELECT d.description FROM pg_description d "
            "WHERE d.objoid=$1::regclass OR d.objoid IN "
            "(SELECT oid FROM pg_constraint WHERE conrelid=$1::regclass)",
            target.table(),
        )
        assert len(comments) >= 10
        assert all(row["description"].isascii() for row in comments)
        assert await conn.fetchval("SELECT to_regclass('public.ctxdb_usage_stats')") is None
        assert await conn.fetchval("SELECT to_regclass('ctxdb_meta.ctxdb_usage_stats')") is None


async def test_creating_workspace_provision_before_active(repository):
    target = await target_for(repository)
    await repository.pool.execute(
        "UPDATE ctxdb_meta.workspaces SET state='creating' WHERE workspace_id=$1", target.workspace_id
    )
    async with repository.pool.acquire() as conn:
        await provision_usage_tables(conn, target.schema_name)
    assert not await UsageRepository(repository.pool).write(target, [delta("a")])


async def test_atomic_concurrent_addition_and_out_of_order_event_time(repository):
    target = await target_for(repository)
    await page(repository, target, "one")
    usage = UsageRepository(repository.pool)
    now = datetime.now(timezone.utc)
    await asyncio.gather(*(usage.write(target, [delta("one", at=now - timedelta(seconds=i))]) for i in range(25)))
    result = await usage.read(target, "knowledge_page", ["one"])
    assert result[0].recall_count == 25
    assert result[0].last_recalled_at == now
    await usage.write(target, [delta("one", 2, now), delta("one", 3, now)])
    assert (await usage.read(target, "knowledge_page", ["one"]))[0].recall_count == 30


async def test_read_existing_zero_unknown_deleted_and_folder(repository):
    target = await target_for(repository)
    await page(repository, target, "never")
    await page(repository, target, "known")
    await page(repository, target, "folder", "folder")
    usage = UsageRepository(repository.pool)
    await usage.write(target, [delta("known", 4), delta("deleted", 3)])
    result = await usage.read(target, "knowledge_page", ["known", "never", "unknown", "deleted", "folder", "known"])
    assert [(item.object_id, item.recall_count) for item in result] == [("known", 4), ("never", 0)]
    assert result[1].last_recalled_at is None


async def test_missing_table_is_unavailable_not_zero(repository):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    await repository.pool.execute(f"DROP TABLE {target.table()}")
    with pytest.raises(ServiceError) as caught:
        await usage.read(target, "knowledge_page", [])
    assert caught.value.status == 503
    assert caught.value.code == "usage_unavailable"
    with pytest.raises(asyncpg.UndefinedTableError):
        await usage.write(target, [delta("one")])


async def test_uuid_rebinding_and_inactive_workspace_drop_old_batches(repository):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    await repository.pool.execute(
        "UPDATE ctxdb_meta.workspaces SET state='deleting' WHERE workspace_id=$1", target.workspace_id
    )
    assert not await usage.write(target, [delta("one")])
    await repository.pool.execute(
        "UPDATE ctxdb_meta.workspaces SET state='active',workspace_id=$2 WHERE workspace_id=$1",
        target.workspace_id,
        uuid4().hex,
    )
    assert not await usage.write(target, [delta("one")])
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0


async def test_workspace_lock_bounds_wait_without_inserting(repository):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    async with repository.pool.acquire() as conn, conn.transaction():
        await conn.fetchrow(
            "SELECT workspace_id FROM ctxdb_meta.workspaces WHERE workspace_id=$1 FOR UPDATE", target.workspace_id
        )
        with pytest.raises(asyncpg.LockNotAvailableError):
            await usage.write(target, [delta("one")])
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0


async def test_offline_reset_removes_restored_foreign_bank_rows(repository):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    await usage.write(target, [delta("one")])
    # Restore can copy foreign identities into this plugin table; a WHERE on
    # the new identity would incorrectly leave those rows behind.
    await repository.pool.execute(
        f"INSERT INTO {target.table()} VALUES('old_bank','knowledge_page','old',5,now())",
    )
    await usage.reset(target)
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0
    with pytest.raises(ServiceError):
        await usage.reset(UsageTarget(uuid4().hex, target.bank_id, target.schema_name))


async def test_memory_reads_keep_archive_and_restore_context(repository, store):
    target = await target_for(repository)
    live, archived, missing = (str(uuid4()) for _ in range(3))
    store.live[target.schema_name] = {live}
    store.archived[target.schema_name] = {archived}
    usage = UsageRepository(repository.pool)
    await usage.write(target, [delta(key, kind="memory") for key in (live, archived, missing)])
    before = get_current_schema()
    result = await usage.read(target, "memory", [live, archived, missing])
    assert [item.object_id for item in result] == [live, archived]
    assert get_current_schema() == before
    assert set(store.isolations) == {"repeatable read"}
    store.live[target.schema_name].add(archived)
    store.archived[target.schema_name].clear()
    await usage.write(target, [delta(archived, kind="memory")])
    assert (await usage.read(target, "memory", [archived]))[0].recall_count == 2


async def test_cleanup_keeps_archived_deletes_permanent_and_cleans_subtree(repository, store):
    target = await target_for(repository)
    live, archived, missing = (str(uuid4()) for _ in range(3))
    store.live[target.schema_name] = {live}
    store.archived[target.schema_name] = {archived}
    usage = UsageRepository(repository.pool)
    await usage.write(target, [delta(key, kind="memory") for key in (live, archived, missing)])
    await usage.write(target, [delta("page_deleted"), delta("descendant_deleted")])
    before = get_current_schema()
    await usage.cleanup()
    assert get_current_schema() == before
    rows = await repository.pool.fetch(f"SELECT object_id FROM {target.table()}")
    assert {row["object_id"] for row in rows} == {live, archived}
    assert set(store.isolations) == {"repeatable read"}


async def test_cleanup_twenty_object_limit_fixed_upper_and_next_space_small_ids(repository, store):
    first = await target_for(repository, "a_space")
    second = await target_for(repository, "b_space")
    # Pin directory order for the concrete A-large/B-small cursor counterexample.
    ordered = sorted((first, second), key=lambda target: target.workspace_id)
    large, small = ordered
    usage = UsageRepository(repository.pool)
    await usage.write(large, [delta(f"old{i:02}") for i in range(25)])
    await usage.write(small, [delta("a")])
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {large.table()}") == 5
    # Higher IDs arriving during a sweep cannot extend its initial upper bound.
    await usage.write(large, [delta(f"zz_new{i:02}") for i in range(25)])
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {large.table()}") == 25
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {small.table()}") == 0
    for _ in range(4):
        await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {large.table()}") == 0


async def test_cleanup_uses_each_space_context_and_bounds_archive_queries(repository, store):
    first = await target_for(repository, "first")
    second = await target_for(repository, "second")
    usage = UsageRepository(repository.pool)
    for target in (first, second):
        await usage.write(target, [delta(str(uuid4()), kind="memory") for _ in range(21)])
    before = get_current_schema()
    await usage.cleanup()
    assert store.calls == 21  # One live batch, then at most twenty archive lookups.
    for _ in range(3):
        await usage.cleanup()
    assert set(store.schemas) == {first.schema_name, second.schema_name}
    assert get_current_schema() == before


async def test_failed_cleanup_rolls_back_and_does_not_advance_object_cursor(repository, store, monkeypatch):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    await usage.write(target, [delta(str(uuid4()), kind="memory") for _ in range(21)])
    original = store.get_archived_memory
    calls = 0

    async def fail_after_some_reads(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("synthetic interrupted archive read")
        return await original(**kwargs)

    monkeypatch.setattr(store, "get_archived_memory", fail_after_some_reads)
    with pytest.raises(OSError):
        await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 21
    monkeypatch.setattr(store, "get_archived_memory", original)
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 1
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0


async def test_repeatable_read_cannot_misclassify_archive_to_live_move(repository, monkeypatch):
    target = await target_for(repository)
    usage = UsageRepository(repository.pool)
    identity = str(uuid4())
    await usage.write(target, [delta(identity, kind="memory")])
    # A tiny transactional Store double exposes the snapshot property without
    # duplicating native memory-table DDL or asserting extracted content by SQL.
    await repository.pool.execute(
        f"CREATE TABLE {target.table('usage_source_states')} (id text PRIMARY KEY,location text)"
    )
    await repository.pool.execute(f"INSERT INTO {target.table('usage_source_states')} VALUES($1,'archive')", identity)

    class MovingStore:
        async def live_memory_ids(self, *, conn, fq_table, bank_id, unit_ids):
            assert get_current_schema() == target.schema_name
            assert await conn.fetchval("SHOW transaction_isolation") == "repeatable read"
            live = await conn.fetch(
                f"SELECT id FROM {target.table('usage_source_states')} WHERE location='live' AND id=ANY($1::text[])",
                unit_ids,
            )
            # Another transaction restores the object between the two Store
            # reads. READ COMMITTED would see neither old archive nor new live.
            await repository.pool.execute(
                f"UPDATE {target.table('usage_source_states')} SET location='live' WHERE id=$1", identity
            )
            return {row["id"] for row in live}

        async def get_archived_memory(self, *, conn, fq_table, bank_id, unit_id):
            archived = await conn.fetchval(
                f"SELECT true FROM {target.table('usage_source_states')} WHERE id=$1 AND location='archive'", unit_id
            )
            return object() if archived else None

    monkeypatch.setattr("hindsight_api.engine.memories.get_memories", MovingStore)
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT recall_count FROM {target.table()}") == 1


def test_usage_identity_and_time_validation():
    for bad in (
        ("x", "ok", "ctxdb_ws_ok"),
        ("a" * 32, 'injected"', "ctxdb_ws_injected"),
        ("a" * 32, "ok", "public"),
    ):
        with pytest.raises(ValueError):
            UsageTarget(*bad)
    with pytest.raises(ValueError):
        delta("not-a-uuid", kind="memory")
    with pytest.raises(ValueError):
        delta("zero", 0)
    with pytest.raises(ValueError):
        delta("naive", at=datetime(2026, 1, 1))


async def test_structurally_broken_workspace_does_not_starve_other_cleanup(repository, store):
    first = await target_for(repository, "broken")
    second = await target_for(repository, "healthy")
    usage = UsageRepository(repository.pool)
    await usage.write(second, [delta("deleted")])
    await repository.pool.execute(f"DROP TABLE {first.table()}")
    # Force deterministic directory order without depending on random UUIDs.
    usage._page = [first, second]
    with pytest.raises(asyncpg.UndefinedTableError):
        await usage.cleanup()
    await usage.cleanup()
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {second.table()}") == 0


async def test_automatic_multi_workspace_writer_with_real_postgres(repository):
    from hindsight_ext_contextdb.usage import UsageCollector

    targets = [await target_for(repository, f"space{index}") for index in range(10)]
    collector = UsageCollector(UsageRepository(repository.pool))
    for target in targets:
        collector.record(target, "knowledge_page", ["page"])
    collector.start()
    try:
        async with asyncio.timeout(4.5):
            while collector.metrics.flushed < len(targets):
                await asyncio.sleep(0.01)
        assert collector.metrics.flushed == len(targets)
        assert collector.metrics.dropped == collector.metrics.uncertain == 0
    finally:
        await collector.close()
