"""ASGI management client over real metadata and controlled native calls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import cast
from unittest.mock import AsyncMock, Mock

import httpx
from fastapi import FastAPI
from hindsight_api import MemoryEngine
from hindsight_ext_contextdb.http import ContextDBHttpExtension
from hindsight_ext_contextdb.repository import Repository
from hindsight_ext_contextdb.tenant import ContextDBTenantExtension

from .identities import (
    ADMIN_SECRET,
)
from .native_doubles import PoolHost


@dataclass
class ManagementClient:
    client: httpx.AsyncClient
    headers: dict[str, str] = field(repr=False)
    app: FastAPI
    admin_headers: dict[str, str] = field(repr=False)
    memory: PoolHost


@asynccontextmanager
async def management_client(repository: Repository) -> AsyncIterator[ManagementClient]:
    extension = ContextDBHttpExtension({})
    app = FastAPI()
    tenant = Mock(spec=ContextDBTenantExtension)
    tenant.context = Mock()
    tenant.context.run_migration = AsyncMock()
    host = PoolHost(repository.pool, tenant_extension=tenant)
    host.update_bank = AsyncMock()
    host.get_bank_profile = AsyncMock(return_value=object())
    host.delete_bank = AsyncMock()
    app.include_router(extension.get_router(cast(MemoryEngine, host)), prefix="/ext")
    transport = httpx.ASGITransport(app=app, client=("192.0.2.10", 23001))
    headers = {"Authorization": f"Bearer {ADMIN_SECRET}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test/ext/contextdb/v1") as client:
        yield ManagementClient(client, headers, app, headers, host)
