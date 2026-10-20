"""A dynamically issued member Key works through the published memory client.

Management calls below belong to fixture provisioning, because the upstream SDK
does not expose optional extension APIs. Memory assertions and background waiting
go exclusively through the published Hindsight client, never SQL or an engine.
The deployment has a unique PG instance and leaves the developer's runtime alone.
"""

from __future__ import annotations

import httpx
import pytest
from hindsight_client_api.exceptions import ForbiddenException
from hindsight_system_tests import reflect_loop
from hindsight_system_tests.payloads import consolidation, extracted, fact
from hindsight_system_tests.waiting import wait_until_settled

from .support.clients import MemberClients, workspace_condition_headers
from .support.deployment import ContextDBDeployment


@pytest.mark.asyncio
async def test_dynamic_keys_shared_bank_and_worker_schema_isolation(contextdb_clients: MemberClients, llm) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    accepted = await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    assert accepted.operation_id is not None
    await wait_until_settled(clients.own, clients.bank_id)
    operations = await clients.own.operations.list_operations(clients.bank_id, limit=100)
    assert any(
        operation.operation_id == accepted.operation_id and operation.status == "completed"
        for operation in operations.operations
    )
    own = await clients.own.arecall(bank_id=clients.bank_id, query="What does Alice build?")
    shared = await clients.same_bank.arecall(bank_id=clients.bank_id, query="What does Alice build?")
    assert [item.text for item in own.results] == ["Alice builds Lighthouse | Involving: Alice"]
    assert [item.id for item in own.results] == [item.id for item in shared.results]
    other = await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="What does Alice build?")
    assert other.results == []
    with pytest.raises(ForbiddenException):
        await clients.other_bank.arecall(bank_id=clients.bank_id, query="What does Alice build?")


@pytest.mark.asyncio
async def test_mcp_uses_member_key_and_hides_bank_management(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    from fastmcp import Client

    clients = contextdb_clients
    async with Client(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=clients.own_key) as mcp:
        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        assert "recall" in names
        assert "retain" in names
        assert "create_bank" not in names
        assert "delete_bank" not in names
        result = await mcp.call_tool("recall", {"query": "What is in this empty Bank?"})
        assert not result.is_error


@pytest.mark.asyncio
async def test_read_permission_unifies_memory_and_knowledge_without_writes(contextdb_clients: MemberClients) -> None:
    clients = contextdb_clients
    for reader in (clients.read_only, clients.knowledge_reader):
        with pytest.raises(ForbiddenException):
            await reader.aretain(bank_id=clients.bank_id, content="Forbidden write")
        assert (await reader.arecall(bank_id=clients.bank_id, query="Empty workspace")).results == []
        assert (await reader.aget_knowledge_base_tree(clients.bank_id)).roots == []


@pytest.mark.asyncio
async def test_read_permission_runs_the_native_reflect_reasoning_loop(contextdb_clients: MemberClients, llm) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    await wait_until_settled(clients.own, clients.bank_id)
    reflect_loop(llm, answer="Alice builds Lighthouse.")
    response = await clients.read_only.areflect(
        bank_id=clients.bank_id, query="What does Alice build?", include_facts=True
    )
    assert response.text == "Alice builds Lighthouse."
    assert response.based_on is not None


@pytest.mark.asyncio
async def test_workspace_deletion_revokes_access_without_touching_another_schema(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    llm,
) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="Lighthouse").returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    llm.on_step("extract_facts", contains="Atlas").returns(
        extracted(fact("Carol builds Atlas", who="Carol", entities=["Carol", "Atlas"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    await clients.own.aretain(bank_id=clients.bank_id, content="Alice builds Lighthouse.", retain_async=True)
    await clients.other_bank.aretain(bank_id=clients.other_bank_id, content="Carol builds Atlas.", retain_async=True)
    await wait_until_settled(clients.own, clients.bank_id)
    await wait_until_settled(clients.other_bank, clients.other_bank_id)
    async with httpx.AsyncClient(
        base_url=contextdb_deployment.server.url + "/ext/contextdb/v1",
        headers=contextdb_deployment.headers,
        timeout=100,
    ) as management:
        response = await management.delete(
            f"/workspaces/{clients.bank_id}",
            headers=await workspace_condition_headers(management, f"/workspaces/{clients.bank_id}"),
        )
        assert response.status_code == 204, response.text
        assert response.content == b""
        assert (await management.get(f"/workspaces/{clients.bank_id}")).status_code == 404
    with pytest.raises(ForbiddenException):
        await clients.own.arecall(bank_id=clients.bank_id, query="Lighthouse")
    other = await clients.other_bank.arecall(bank_id=clients.other_bank_id, query="What does Carol build?")
    assert [item.text for item in other.results] == ["Carol builds Atlas | Involving: Carol"]
