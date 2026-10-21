"""The deployment probe must call PGroonga's actual variadic SQL signature."""

from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from asyncpg.transaction import Transaction
from hindsight_ext_contextdb.preflight import preflight


@dataclass
class PgroongaProbeConnection:
    connection: asyncpg.Connection

    def transaction(self, *, readonly: bool) -> Transaction:
        return self.connection.transaction(readonly=readonly)

    async def fetchval(self, query: str) -> Any:
        return await self.connection.fetchval(query)

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        if query == "SELECT extname FROM pg_extension":
            # The fixture has no PGroonga binary. Advertise only its catalog row;
            # the probe itself executes a real variadic PostgreSQL function below.
            return await self.connection.fetch(
                "SELECT unnest(ARRAY['vector','btree_gin','pg_trgm','pgroonga']) AS extname"
            )
        return await self.connection.fetch(query, *args)

    async def close(self) -> None:
        await self.connection.close()


@pytest.mark.parametrize("restricted_role", [False, True])
async def test_multilingual_probe_supplies_pgroonga_tokenizer_options(database_url, monkeypatch, restricted_role):
    connection = await asyncpg.connect(database_url)
    try:
        # Same required variadic signature as PGroonga 4.1. A one-argument call
        # must fail in the SQL parser instead of being accepted by a Python mock.
        await connection.execute(
            """
            CREATE FUNCTION public.pgroonga_tokenize(target text, VARIADIC options text[])
            RETURNS SETOF text LANGUAGE plpgsql AS $$
            BEGIN
              IF options <> ARRAY['tokenizer','TokenBigram'] THEN
                RAISE EXCEPTION 'The multilingual probe must exercise TokenBigram';
              END IF;
              RETURN NEXT target;
            END
            $$
            """
        )
        if restricted_role:
            await connection.execute("CREATE ROLE contextdb_preflight_reader NOLOGIN NOSUPERUSER")
        connect = asyncpg.connect

        async def connect_probe(*args: Any, **kwargs: Any) -> PgroongaProbeConnection:
            probe = await connect(*args, **kwargs)
            if restricted_role:
                await probe.execute("SET ROLE contextdb_preflight_reader")
            return PgroongaProbeConnection(probe)

        monkeypatch.setattr(asyncpg, "connect", connect_probe)
        monkeypatch.setenv("HINDSIGHT_API_DATABASE_URL", database_url)
        monkeypatch.setenv("HINDSIGHT_API_TEXT_SEARCH_EXTENSION", "pgroonga")
        report = await preflight(language="multilingual")
        assert any(item.name == "pgroonga_tokenizer" and item.status == "pass" for item in report.checks)
        assert not any(item.name == "database_probe" and item.status == "fail" for item in report.checks)
    finally:
        await connection.execute("DROP FUNCTION IF EXISTS public.pgroonga_tokenize(text,text[])")
        if restricted_role:
            await connection.execute("DROP ROLE IF EXISTS contextdb_preflight_reader")
        await connection.close()
