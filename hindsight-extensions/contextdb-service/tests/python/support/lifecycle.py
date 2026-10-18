"""PG-backed lifecycle doubles, independent of pytest collection."""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock

from hindsight_api import MemoryEngine
from hindsight_api.extensions.context import ExtensionContext
from hindsight_ext_contextdb.lifecycle import Lifecycle
from hindsight_ext_contextdb.repository import Repository


def lifecycle_for(repository: Repository) -> Lifecycle:
    context = Mock(spec=ExtensionContext)
    memory = Mock(spec=MemoryEngine)

    async def migrate(schema: str) -> None:
        # Single-connection availability proves no metadata transaction spans DDL.
        await repository.pool.execute(
            f'CREATE SCHEMA "{schema}"; CREATE TABLE "{schema}".banks(bank_id text PRIMARY KEY)'
        )

    async def update(bank_id: str, *, name: str, request_context) -> None:
        await repository.pool.execute(f'INSERT INTO "ctxdb_ws_{bank_id}".banks VALUES($1)', bank_id)

    async def delete(bank_id: str, *, request_context) -> None:
        await repository.pool.execute(f'DELETE FROM "ctxdb_ws_{bank_id}".banks WHERE bank_id=$1', bank_id)

    context.run_migration = AsyncMock(side_effect=migrate)
    memory.update_bank = AsyncMock(side_effect=update)
    memory.get_bank_profile = AsyncMock(return_value=object())
    memory.delete_bank = AsyncMock(side_effect=delete)
    return Lifecycle(repository, cast(MemoryEngine, memory), cast(ExtensionContext, context))
