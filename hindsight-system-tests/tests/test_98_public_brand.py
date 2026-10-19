"""Customers see agentstratum over real protocols; their words remain their words.

Use the unchanged SDK for a retain/read round trip and raw HTTP for discovery
surfaces the SDK does not own (OpenAPI, MCP initialization, and Prometheus).
No engine imports or database access: a response filter that edits stored text
must fail the same story that verifies the service identity.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hindsight_system_tests.payloads import consolidation, extracted, fact

pytestmark = pytest.mark.asyncio


def _rpc_payload(response: httpx.Response):
    """MCP may return JSON or a finite SSE response to an RPC POST."""
    response.raise_for_status()
    if "text/event-stream" not in response.headers.get("content-type", ""):
        return response.json()
    for event in response.text.split("\n\n"):
        data = "\n".join(line[6:] for line in event.splitlines() if line.startswith("data: "))
        if data:
            payload = json.loads(data)
            if "result" in payload or "error" in payload:
                return payload
    raise AssertionError("MCP response contains no JSON-RPC result")


async def test_discovery_and_monitoring_expose_the_product_identity(hindsight_server):
    async with httpx.AsyncClient(base_url=hindsight_server.url, timeout=30, follow_redirects=True) as http:
        schema = await http.get("/openapi.json")
        schema.raise_for_status()
        assert schema.json()["info"]["title"] == "agentstratum HTTP API"
        assert "hindsight" not in schema.text.casefold()

        health = await http.get("/health")
        health.raise_for_status()
        assert "hindsight" not in health.text.casefold()

        metrics = await http.get("/metrics")
        metrics.raise_for_status()
        assert "agentstratum_" in metrics.text
        assert "hindsight" not in metrics.text.casefold()


async def test_mcp_initialization_and_tool_schemas_are_customer_branded(hindsight_server):
    async with httpx.AsyncClient(base_url=hindsight_server.url, timeout=30, follow_redirects=True) as http:
        headers = {"Accept": "application/json, text/event-stream"}
        initialized = await http.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "customer-protocol-test", "version": "1.0"},
                },
            },
        )
        payload = _rpc_payload(initialized)
        assert payload["result"]["serverInfo"]["name"] == "agentstratum-mcp-server"
        assert "hindsight" not in json.dumps(payload).casefold()
        session_id = initialized.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        headers["MCP-Protocol-Version"] = payload["result"]["protocolVersion"]
        notified = await http.post(
            "/mcp/",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        notified.raise_for_status()
        tools = _rpc_payload(
            await http.post(
                "/mcp/",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
        )
        assert tools["result"]["tools"]
        assert "hindsight" not in json.dumps(tools).casefold()
        if session_id:
            closed = await http.delete("/mcp/", headers=headers)
            assert closed.status_code in (200, 202, 204, 405)


async def test_unchanged_sdk_preserves_customer_content_and_accepts_product_config(client, bank_id, llm, settled):
    content = "Alice uses hindsight as a word, HINDSIGHT as a label, and Hindsight as a title."
    document_id = "customer-hindsight.txt"
    llm.on_step("extract_facts").returns(extracted(fact(content, who="Alice", entities=["Alice"])))
    llm.on_step("consolidate").returns(consolidation())
    await client.acreate_bank(bank_id=bank_id, name="customer hindsight bank")
    await client.banks.update_bank_config(
        bank_id,
        {
            "updates": {"AGENTSTRATUM_API_ENABLE_RERANKING": False},
        },
    )
    assert (await client.banks.get_bank_config(bank_id)).config["enable_reranking"] is False
    await client.aretain(bank_id=bank_id, content=content, document_id=document_id)
    await settled(bank_id)
    document = await client.documents.get_document(bank_id, document_id)
    assert document.id == document_id
    assert document.original_text == content
    listing = await client.banks.list_banks(q=bank_id)
    assert next(bank for bank in listing.banks if bank.bank_id == bank_id).name == "customer hindsight bank"
