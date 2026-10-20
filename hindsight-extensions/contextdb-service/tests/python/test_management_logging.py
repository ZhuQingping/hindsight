"""Management failures retain server diagnostics without changing public errors."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, Mock

import asyncpg
import httpx
import pytest
from fastapi import FastAPI

from hindsight_ext_contextdb import http
from hindsight_ext_contextdb.config import Settings
from hindsight_ext_contextdb.models import ServiceError
from hindsight_ext_contextdb.repository import Repository


@pytest.mark.parametrize("stage", ["authenticate_admin", "list_users"])
@pytest.mark.parametrize(
    "error,status,code,message",
    [
        (OSError("synthetic connection diagnostic"), 503, "metadata_unavailable", "Metadata service unavailable"),
        (
            asyncpg.PostgresError("synthetic database diagnostic"),
            503,
            "metadata_unavailable",
            "Metadata service unavailable",
        ),
        (
            RuntimeError("synthetic internal diagnostic"),
            500,
            "management_failed",
            "Management request failed; query the resource before retrying",
        ),
        (
            ServiceError(403, "admin_required", "Administrator required"),
            403,
            "admin_required",
            "Administrator required",
        ),
    ],
)
async def test_management_error_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error: Exception,
    status: int,
    code: str,
    message: str,
) -> None:
    settings = Settings(instance_id="test", cloud_tenant_id="tenant", pepper="synthetic-test-pepper-32-bytes-long")
    monkeypatch.setattr(http.Settings, "from_environment", lambda: settings)
    repository = Mock(spec=Repository)
    repository.authenticate_admin = AsyncMock()
    repository.list_users = AsyncMock()
    getattr(repository, stage).side_effect = error
    monkeypatch.setattr(http, "repository_for", AsyncMock(return_value=repository))
    app = FastAPI()
    app.include_router(http.ContextDBHttpExtension({}).get_router(Mock()), prefix="/ext")
    with caplog.at_level(logging.ERROR, logger=http.__name__):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/ext/contextdb/v1/users", headers={"Authorization": "Bearer synthetic-request-credential"}
            )
    assert response.status_code == status
    request_id = response.headers["X-Request-ID"]
    assert response.json() == {"code": code, "message": message, "request_id": request_id, "fields": []}
    assert response.headers["Cache-Control"] == "no-store"
    records = [record for record in caplog.records if record.name == http.__name__]
    if isinstance(error, ServiceError):
        assert records == []
    else:
        assert len(records) == 1
        record = records[0]
        assert request_id in record.getMessage()
        assert record.exc_info is not None
        assert record.exc_info[1] is error
        assert record.exc_info[2] is not None
        assert str(error) in caplog.text
        assert str(error) not in response.text
    assert "synthetic-request-credential" not in caplog.text
