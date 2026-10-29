"""A service restart disables usage without breaking memory/knowledge or losing counters."""

import httpx
import pytest
from contextbase_client import ContextBase
from fastmcp import Client

from .support.clients import clients_owner
from .support.deployment import DeploymentOptions, deployment_owner
from .support.knowledge import create_nonempty_page
from .test_121_contextdb_usage import _retain_memory, _usage, _wait_for_count


@pytest.fixture(params=["embedded-worker", "standalone-worker"])
def switch_deployment(request, stub_server, tmp_path):
    with deployment_owner(DeploymentOptions(worker_mode=request.param), stub_server.url, tmp_path) as deployment:
        yield deployment


@pytest.mark.asyncio
async def test_switch_off_on_preserves_data_keys_and_counts(switch_deployment, stub_server, llm):
    deployment = switch_deployment
    async with clients_owner(deployment) as clients:
        memory_id = await _retain_memory(clients, llm)
        page_id = (await create_nonempty_page(clients, llm)).page_id
        await clients.read_only.arecall(bank_id=clients.bank_id, query="UsageSentinel")
        await clients.knowledge_reader.asearch_knowledge_base(clients.bank_id, "Lighthouse")
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=30
        ) as management:
            before_memory = await _wait_for_count(management, clients.bank_id, "memory", memory_id, 1)
            before_page = await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 1)
        deployment.restart_api(stub_server.url, recall_usage_enabled=False)
        async with httpx.AsyncClient(base_url=deployment.server.url, timeout=30) as http:
            identity = await http.get("/ext/contextdb/v1/admin/identity", headers=deployment.headers)
            assert identity.json()["capabilities"] == {"recall_usage": False}
            path = f"/ext/contextdb/v1/workspaces/{clients.bank_id}/usage"
            params = {"object_type": "memory", "ids": memory_id}
            off = await http.get(path, params=params, headers=deployment.headers)
            assert off.status_code == 404 and off.json()["code"] == "usage_disabled"
            assert (await http.get(path, params=params)).status_code == 401
            off = await http.get(path, params=params, headers={"Authorization": "Bearer " + clients.own_key})
            assert off.status_code == 404 and off.json()["code"] == "usage_disabled"
            denied = await http.get(path, params=params, headers={"Authorization": "Bearer " + clients.other_key})
            assert denied.status_code == 403
        sdk = ContextBase(base_url=deployment.server.url, api_key=clients.own_key)
        try:
            assert memory_id in [
                r.id for r in (await sdk.arecall(bank_id=clients.bank_id, query="UsageSentinel")).results
            ]
            assert page_id in [r.id for r in (await sdk.asearch_knowledge_base(clients.bank_id, "Lighthouse")).results]
            await sdk.aget_knowledge_page(clients.bank_id, page_id)
            async with Client(deployment.server.url + "/mcp/", auth=clients.own_key) as mcp:
                assert not (
                    await mcp.call_tool("recall", {"bank_id": clients.bank_id, "query": "UsageSentinel"})
                ).is_error
                assert not (
                    await mcp.call_tool("search_knowledge_base", {"bank_id": clients.bank_id, "query": "Lighthouse"})
                ).is_error
        finally:
            await sdk.aclose()
        deployment.restart_api(stub_server.url, recall_usage_enabled=True)
        async with httpx.AsyncClient(
            base_url=deployment.server.url + "/ext/contextdb/v1", headers=deployment.headers, timeout=30
        ) as management:
            assert (await management.get("/admin/identity")).json()["capabilities"]["recall_usage"] is True
            memory = (await _usage(management, clients.bank_id, "memory", [memory_id])).items[0]
            page = (await _usage(management, clients.bank_id, "knowledge_page", [page_id])).items[0]
            assert memory == before_memory and page == before_page
            sdk = ContextBase(base_url=deployment.server.url, api_key=clients.own_key)
            try:
                await sdk.arecall(bank_id=clients.bank_id, query="UsageSentinel")
                await sdk.asearch_knowledge_base(clients.bank_id, "Lighthouse")
                await _wait_for_count(management, clients.bank_id, "memory", memory_id, 2)
                await _wait_for_count(management, clients.bank_id, "knowledge_page", page_id, 2)
            finally:
                await sdk.aclose()
