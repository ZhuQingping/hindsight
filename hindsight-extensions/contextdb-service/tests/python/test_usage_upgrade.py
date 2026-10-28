"""Real PG validates the explicit legacy-column migration without touching user databases."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from hindsight_ext_contextdb.models import ServiceError
from hindsight_ext_contextdb.usage_repository import UsageDelta, UsageRepository, UsageTarget, upgrade_usage_table

from .support.identities import ready_workspace


async def legacy_table(repository):
    workspace = await ready_workspace(repository, "legacy_usage")
    target = UsageTarget(workspace.workspace_id, workspace.bank_id, workspace.schema_name)
    await repository.pool.execute(f'CREATE SCHEMA "{target.schema_name}"')
    await repository.pool.execute(
        f"CREATE TABLE {target.table()} (workspace_id varchar(32) NOT NULL,bank_id varchar(54) NOT NULL,"
        "object_type text NOT NULL,object_id varchar(64) NOT NULL,recall_count bigint NOT NULL,"
        "last_recalled_at timestamptz NOT NULL,"
        "CONSTRAINT ctxdb_usage_stats_pkey PRIMARY KEY(workspace_id,bank_id,object_type,object_id),"
        "CONSTRAINT usage_workspace_identity CHECK(workspace_id ~ '^[0-9a-f]{32}$'),"
        "CONSTRAINT usage_object_type CHECK(object_type IN ('memory','knowledge_page')),"
        "CONSTRAINT usage_object_identity CHECK(length(object_id)>0),"
        "CONSTRAINT usage_positive_count CHECK(recall_count>0))"
    )
    return target


async def test_offline_upgrade_preserves_counts_times_and_supports_repeated_execution(
    repository, database_url, tmp_path
):
    from hindsight_api.admin.cli import _backup, _restore

    target = await legacy_table(repository)
    at = datetime(2026, 10, 28, 6, tzinfo=timezone.utc)
    await repository.pool.executemany(
        f"INSERT INTO {target.table()} VALUES($1,$2,$3,$4,$5,$6)",
        [
            (target.workspace_id, target.bank_id, kind, object_id, 7, at)
            for kind, object_id in [("memory", str(uuid4())), ("knowledge_page", "page")]
        ],
    )
    before = await repository.pool.fetch(
        f"SELECT bank_id,object_type,object_id,recall_count,last_recalled_at FROM {target.table()} ORDER BY object_type"
    )
    archive = tmp_path / "legacy-usage.zip"
    await _backup(database_url, archive, target.schema_name, backup_tables=["ctxdb_usage_stats"])
    async with repository.pool.acquire() as conn:
        await upgrade_usage_table(conn, target.schema_name)
        await upgrade_usage_table(conn, target.schema_name)
    after = await repository.pool.fetch(f"SELECT * FROM {target.table()} ORDER BY object_type")
    assert before == after
    assert all("workspace_id" not in row for row in after)
    await UsageRepository(repository.pool).write(target, [UsageDelta("knowledge_page", "page", 2, at)])
    assert (
        await repository.pool.fetchval(f"SELECT recall_count FROM {target.table()} WHERE object_type='knowledge_page'")
        == 9
    )
    assert await repository.pool.fetchval("SELECT to_regclass('public.ctxdb_usage_stats')") is None
    # Native restore strips removed backup columns using its manifest; this
    # explicit reset remains required before serving a single-schema restore.
    await _restore(database_url, archive, target.schema_name, backup_tables=["ctxdb_usage_stats"])
    assert await repository.pool.fetch(f"SELECT * FROM {target.table()} ORDER BY object_type") == before
    await UsageRepository(repository.pool).reset(target)
    assert await repository.pool.fetchval(f"SELECT count(*) FROM {target.table()}") == 0


@pytest.mark.parametrize("foreign", ["workspace", "bank"])
async def test_foreign_generation_or_bank_aborts_without_rewriting_or_merging(repository, foreign):
    target = await legacy_table(repository)
    await repository.pool.execute(
        f"INSERT INTO {target.table()} VALUES($1,$2,'knowledge_page','page',5,now())",
        uuid4().hex if foreign == "workspace" else target.workspace_id,
        "other_bank" if foreign == "bank" else target.bank_id,
    )
    before = await repository.pool.fetch(f"SELECT * FROM {target.table()}")
    async with repository.pool.acquire() as conn:
        with pytest.raises(ServiceError, match="another workspace identity"):
            await upgrade_usage_table(conn, target.schema_name)
    assert await repository.pool.fetch(f"SELECT * FROM {target.table()}") == before


@pytest.mark.parametrize("key", ["object_id", "bank_id,object_type,object_id"])
async def test_unexpected_primary_key_aborts_before_ddl(repository, key):
    target = await legacy_table(repository)
    await repository.pool.execute(
        f"ALTER TABLE {target.table()} DROP CONSTRAINT ctxdb_usage_stats_pkey, ADD PRIMARY KEY ({key})"
    )
    async with repository.pool.acquire() as conn:
        with pytest.raises(ServiceError, match="Unexpected usage primary key"):
            await upgrade_usage_table(conn, target.schema_name)
    assert await repository.pool.fetchval(
        "SELECT EXISTS(SELECT FROM information_schema.columns WHERE table_schema=$1 "
        "AND table_name='ctxdb_usage_stats' AND column_name='workspace_id')",
        target.schema_name,
    )
