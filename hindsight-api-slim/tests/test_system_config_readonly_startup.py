"""An existing metadata table must load without issuing initialization DDL."""

from unittest.mock import AsyncMock

import pytest

from hindsight_api.engine.system_config import _ensure_table


@pytest.mark.asyncio
async def test_existing_table_does_not_issue_ddl():
    conn = AsyncMock()
    conn.fetchval.return_value = True
    await _ensure_table(conn)
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_table_keeps_first_start_creation():
    conn = AsyncMock()
    conn.fetchval.return_value = False
    await _ensure_table(conn)
    conn.execute.assert_awaited_once()
    assert "CREATE TABLE IF NOT EXISTS ctxdb_meta.system_config" in conn.execute.await_args.args[0]
