"""Force metadata setup failure without starting PostgreSQL."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from .support import metadata


async def test_metadata_bootstrap_failure_closes_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = Mock()
    connection = Mock()
    connection.execute = AsyncMock(side_effect=RuntimeError("synthetic metadata failure"))
    acquire = Mock()
    acquire.__aenter__ = AsyncMock(return_value=connection)
    acquire.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = acquire
    pool.close = AsyncMock()
    monkeypatch.setattr(metadata.asyncpg, "create_pool", AsyncMock(return_value=pool))
    owner = metadata.repository_owner("postgresql://synthetic-unused")
    with pytest.raises(RuntimeError, match="synthetic metadata failure"):
        async with owner:
            pytest.fail("Failed setup must not yield a repository")
    pool.close.assert_awaited_once()
