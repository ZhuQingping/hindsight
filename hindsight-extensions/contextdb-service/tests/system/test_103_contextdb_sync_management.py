"""Synchronous management exposes resources and tolerates a lost response.

These stories do not delete while business work is running. SQL checks physical
schema ownership/cleanup only; memory correctness remains covered through SDKs.
"""

from __future__ import annotations

import secrets

import asyncpg
import httpx
import pytest

from ..lifecycle_http import bank_url, create_workspace
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


class LostManagementReply(httpx.AsyncBaseTransport):
    """Let the real API finish a write, then drop its successful HTTP response."""

    def __init__(self) -> None:
        self.transport = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.transport.handle_async_request(request)
        if request.method in {"PUT", "DELETE"} and response.status_code == 200:
            await response.aclose()
            raise httpx.ReadTimeout("Synthetic lost management response", request=request)
        return response

    async def aclose(self) -> None:
        await self.transport.aclose()


async def test_sync_workspace_contract_and_physical_cleanup(contextdb_deployment: ContextDBDeployment) -> None:
    deployment = contextdb_deployment
    name = "sync_contract_" + secrets.token_hex(5)
    schema = "ctxdb_ws_" + name
    async with httpx.AsyncClient(
        base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
    ) as management:
        created = await create_workspace(management, json={"name": name, "description": "Synchronous story"})
        assert created.status_code == 200, created.text
        resource = created.json()
        assert resource["name"] == resource["bank_id"] == name
        assert resource["description"] == "Synchronous story" and resource["state"] == "active"
        assert {"operation_id", "latest_operation_id"}.isdisjoint(resource)
        detail = await management.get("/workspaces/" + name)
        assert detail.status_code == 200 and detail.json()["workspace_id"] == resource["workspace_id"]
        assert detail.headers["etag"] == created.headers["etag"]
        assert (await create_workspace(management, json={"name": name.upper()})).status_code == 412
        assert (await management.get("/operations/" + secrets.token_hex(16))).status_code == 404
        assert (await management.delete(bank_url(management, name))).status_code == 428
        connection = await asyncpg.connect(deployment.database_url)
        try:
            assert await connection.fetchval("SELECT to_regnamespace($1) IS NOT NULL", schema)
            removed = await management.delete(bank_url(management, name), headers={"If-Match": detail.headers["etag"]})
            assert removed.status_code == 200 and removed.json()["success"] is True, removed.text
            assert (await management.get("/workspaces/" + name)).status_code == 404
            assert await connection.fetchval("SELECT to_regnamespace($1) IS NULL", schema)
            assert (
                await connection.fetchval(
                    "SELECT count(*) FROM ctxdb_meta.workspaces WHERE workspace_id=$1", resource["workspace_id"]
                )
                == 0
            )
        finally:
            await connection.close()


async def test_lost_management_response_is_resolved_by_query_without_replaying_write(
    contextdb_deployment: ContextDBDeployment,
) -> None:
    deployment = contextdb_deployment
    name = "lost_response_" + secrets.token_hex(5)
    url = deployment.server.url + "/ext/contextdb/v1"
    async with (
        httpx.AsyncClient(base_url=url, headers=deployment.headers, timeout=100) as management,
        httpx.AsyncClient(
            base_url=url, headers=deployment.headers, timeout=100, transport=LostManagementReply()
        ) as interrupted,
    ):
        with pytest.raises(httpx.ReadTimeout, match="Synthetic lost"):
            await create_workspace(interrupted, json={"name": name})
        # Query the object instead of replaying an uncertain PUT. The real API
        # already finished, so this also verifies the synchronous commit boundary.
        created = await management.get("/workspaces/" + name)
        assert created.status_code == 200 and created.json()["state"] == "active", created.text
        page = await management.get("/workspaces", params={"q": name, "limit": 100})
        assert [item["bank_id"] for item in page.json()["items"]] == [name]
        with pytest.raises(httpx.ReadTimeout, match="Synthetic lost"):
            await interrupted.delete(bank_url(interrupted, name), headers={"If-Match": created.headers["etag"]})
        assert (await management.get("/workspaces/" + name)).status_code == 404
