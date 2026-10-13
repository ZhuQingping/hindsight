"""Native REST/MCP error wrappers cannot erase an uncertain-work cleanup barrier.

Fault injection adds/removes a queue trigger only in this fixture's unique PG.
Memory and management outcomes use public SDK/MCP/REST contracts, not SQL reads.
"""

from __future__ import annotations

import asyncio
import json
import secrets

import asyncpg
import httpx
import pytest
from fastmcp import Client
from hindsight_client_api.exceptions import ApiException

from .test_100_contextdb_service import ContextDBDeployment, MemberClients

pytest_plugins = ["tests.test_100_contextdb_service"]
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("transport", ["rest", "mcp"])
async def test_wrapped_native_queue_fault_retains_barrier_and_prevents_purge(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, transport: str
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    connection = await asyncpg.connect(deployment.database_url)
    schema = "ctxdb_ws_" + clients.bank_id  # Registered server-generated ID, never a customer-selected DSN/schema.
    try:
        await connection.execute(
            f'CREATE FUNCTION "{schema}".test_reject_enqueue() RETURNS trigger LANGUAGE plpgsql '
            "AS $$ BEGIN RAISE EXCEPTION 'synthetic queue write failure'; END; $$"
        )
        await connection.execute(
            f'CREATE TRIGGER test_reject_enqueue BEFORE INSERT ON "{schema}".async_operations '
            f'FOR EACH ROW EXECUTE FUNCTION "{schema}".test_reject_enqueue()'
        )
        if transport == "rest":
            with pytest.raises(ApiException) as error:
                await clients.own.aretain(
                    clients.bank_id, "FaultBarrier rejected before queue commit.", retain_async=True
                )
            assert error.value.status == 500
        else:
            async with Client(f"{deployment.server.url}/mcp/{clients.bank_id}/", auth=clients.own_key) as mcp:
                result = await mcp.call_tool("retain", {"content": "FaultBarrier rejected before queue commit."})
                assert not result.is_error  # Historical native protocol packs its domain error in JSON.
                payload = json.loads(result.content[0].text)
                assert payload["status"] == "error"
                assert "synthetic queue write failure" in payload["message"]
        # The trigger is gone before deletion. Its presence cannot be the reason
        # deletion waits; only the service's retained admission blocks cleanup.
        await connection.execute(f'DROP TRIGGER test_reject_enqueue ON "{schema}".async_operations')
        await connection.execute(f'DROP FUNCTION "{schema}".test_reject_enqueue()')
        assert (await clients.own.operations.list_operations(clients.bank_id)).total == 0
        assert not (await clients.own.arecall(clients.bank_id, "FaultBarrier")).results
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers
        ) as management:
            response = await management.delete(
                f"/workspaces/{clients.bank_id}", headers={"Idempotency-Key": secrets.token_hex(8)}
            )
            assert response.status_code == 202
            operation_id = response.json()["operation_id"]
            deadline = asyncio.get_running_loop().time() + 10
            while True:
                operation = (await management.get(f"/operations/{operation_id}")).json()
                assert operation["state"] != "succeeded", "Unknown execution was incorrectly declared safe to purge"
                assert operation["state"] != "failed", operation
                if operation["error_code"] == "waiting_for_admissions":
                    break
                assert asyncio.get_running_loop().time() < deadline
                await asyncio.sleep(0.1)
            workspace = await management.get(f"/workspaces/{clients.bank_id}")
            assert workspace.json()["state"] == "deleting"
    finally:
        await connection.close()
