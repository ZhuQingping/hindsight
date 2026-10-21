"""Dedicated PG fixture: unique name, temporary data directory, no dev DB access."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.repository import Repository

from .support.http import ManagementClient, management_client
from .support.metadata import postgres_owner, repository_owner


@pytest.fixture(autouse=True)
def disable_unfenced_native_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINDSIGHT_API_LLM_TRACE_ENABLED", "false")
    monkeypatch.setenv("HINDSIGHT_API_AUDIT_LOG_ENABLED", "false")


@pytest.fixture
def configured(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("CONTEXTDB_INSTANCE_ID", repository.instance_id)
    monkeypatch.setenv("CONTEXTDB_CLOUD_TENANT_ID", repository.cloud_tenant_id)
    monkeypatch.setenv("CONTEXTDB_KEY_PEPPER", repository.pepper)
    monkeypatch.delenv("HINDSIGHT_API_MCP_AUTH_TOKEN", raising=False)
    return Settings.from_environment()


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    with postgres_owner(tmp_path_factory.mktemp("contextdb-metadata")) as url:
        yield url


@pytest_asyncio.fixture
async def repository(database_url: str) -> AsyncIterator[Repository]:
    async with repository_owner(database_url) as repo:
        yield repo


@pytest_asyncio.fixture
async def management(repository: Repository, configured: Settings) -> AsyncIterator[ManagementClient]:
    async with management_client(repository) as client:
        yield client
