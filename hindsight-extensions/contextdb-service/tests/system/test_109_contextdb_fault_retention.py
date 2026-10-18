"""Native queue faults preserve REST/MCP error behavior without a deletion barrier.

Fault injection adds/removes a queue trigger only in this fixture's unique PG.
Memory and management outcomes use public SDK/MCP/REST contracts, not SQL reads.
"""

from __future__ import annotations

import json

import asyncpg
import httpx
import pytest
from fastmcp import Client
from hindsight_client_api.exceptions import ApiException

from .support.clients import MemberClients, workspace_condition_headers
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("transport", ["rest", "mcp"])
async def test_native_queue_fault_does_not_poison_later_management_cleanup(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, transport: str
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    connection = await asyncpg.connect(deployment.database_url)
    schema = "ctxdb_ws_" + clients.bank_id  # Name came from the managed workspace directory.
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
        # The injected failure has ended and no background task was committed.
        # Once the cause is removed, normal synchronous cleanup must succeed.
        await connection.execute(f'DROP TRIGGER test_reject_enqueue ON "{schema}".async_operations')
        await connection.execute(f'DROP FUNCTION "{schema}".test_reject_enqueue()')
        assert (await clients.own.operations.list_operations(clients.bank_id)).total == 0
        assert not (await clients.own.arecall(clients.bank_id, "FaultBarrier")).results
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=100
        ) as management:
            response = await management.delete(
                f"/workspaces/{clients.bank_id}",
                headers=await workspace_condition_headers(management, f"/workspaces/{clients.bank_id}"),
            )
            assert response.status_code == 204, response.text
            assert (await management.get(f"/workspaces/{clients.bank_id}")).status_code == 404
    finally:
        await connection.close()
