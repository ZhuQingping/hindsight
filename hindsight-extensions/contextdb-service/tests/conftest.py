"""Dedicated PG fixture: unique name, temporary data directory, no dev DB access."""

from __future__ import annotations

import secrets
import socket
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from hindsight_ext_contextdb.repository import Repository
from pg0 import Pg0


@pytest.fixture(autouse=True)
def disable_unfenced_native_diagnostics(monkeypatch):
    monkeypatch.setenv("HINDSIGHT_API_LLM_TRACE_ENABLED", "false")
    monkeypatch.setenv("HINDSIGHT_API_AUDIT_LOG_ENABLED", "false")


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    name = f"ctxdb-meta-test-{secrets.token_hex(6)}"
    # pg0's automatic registry port selection races across concurrent test runs.
    # Let the OS select a temporary port; never reuse a developer's default PG.
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    database = Pg0(name=name, port=port, data_dir=str(tmp_path_factory.mktemp(name)), database="contextdb_test")
    try:
        info = database.start()
        assert info.uri is not None
        yield info.uri
    finally:
        # Stop only this fixture's unique instance. No broad filesystem cleanup,
        # no pg0 default instance, and no access to the machine's existing server.
        database.stop()


@pytest_asyncio.fixture
async def repository(database_url: str) -> AsyncIterator[Repository]:
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=8)
    assert pool is not None
    try:
        # Bootstrap failures must close the pool too, not only errors after yield.
        ddl = Path(__file__).parents[1] / "hindsight_ext_contextdb" / "schema.sql"
        async with pool.acquire() as conn:
            await conn.execute("DROP SCHEMA IF EXISTS ctxdb_meta CASCADE")
            for schema in await conn.fetch("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ctxdb_ws_%'"):
                await conn.execute('DROP SCHEMA "' + schema["nspname"] + '" CASCADE')
            await conn.execute(ddl.read_text())
            # This database belongs exclusively to the fixture. Reset control metadata
            # between tests, not memory tables and never a user-provided connection URL.
            await conn.execute(
                "TRUNCATE ctxdb_meta.deployment_info,ctxdb_meta.users,ctxdb_meta.workspaces,ctxdb_meta.audit_events CASCADE"
            )
        from .test_repository import ADMIN_SECRET

        repo = Repository(
            pool,
            "instance-test",
            "tenant-test",
            "synthetic-test-pepper-32-bytes-long",
        )
        await pool.execute(
            "INSERT INTO ctxdb_meta.deployment_info(instance_id,cloud_tenant_id,metadata_version,format_id) VALUES('instance-test','tenant-test',1,'contextdb-first-release')"
        )
        from hindsight_ext_contextdb.bootstrap import initialize_administrator

        async with pool.acquire() as conn, conn.transaction():
            await initialize_administrator(conn, ADMIN_SECRET, repo.pepper)
        await repo.verify_schema()
        yield repo
    finally:
        await pool.close()
