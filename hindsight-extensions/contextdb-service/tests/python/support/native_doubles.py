"""Only the native host capabilities these policy tests need."""

from dataclasses import dataclass

import asyncpg


@dataclass
class PoolHost:
    pool: asyncpg.Pool
    _operation_validator: object | None = None
    tenant_extension: object | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        return self.pool
