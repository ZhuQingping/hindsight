"""Nonempty knowledge remains readable without opening raw-memory side doors.

Reuse the dedicated PG0 deployment and both Worker variants from story 100.
All customer operations use the published SDK/MCP clients; no engine or SQL
access is used to fabricate a page or bypass its background refresh.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from hindsight_client_api.api.audit_api import AuditApi
from hindsight_client_api.api.llm_traces_api import LLMTracesApi
from hindsight_client_api.exceptions import ForbiddenException
from hindsight_client_api.models.create_knowledge_page_response import CreateKnowledgePageResponse

from hindsight_system_tests import LLMStub, reflect_loop, wait_until_settled
from hindsight_system_tests.payloads import extracted, fact, observes

from .test_100_contextdb_service import (
    ContextDBDeployment,
    MemberClients,
)

pytest_plugins = ["tests.test_100_contextdb_service"]
pytestmark = pytest.mark.asyncio

ANSWER = "Alice builds Lighthouse."


@pytest.fixture
async def nonempty_page(contextdb_clients: MemberClients, llm: LLMStub) -> CreateKnowledgePageResponse:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains=ANSWER).returns(
        extracted(fact("Alice builds Lighthouse", who="Alice", entities=["Alice", "Lighthouse"]))
    )
    # Specific later observation first: returning Alice's unchanged observation
    # for Bob is deduplicated by core and legitimately schedules no refresh.
    llm.on_step("consolidate", contains="Bob joins Lighthouse").answers_with(observes("Bob joins Lighthouse"))
    llm.on_step("consolidate").answers_with(observes("Alice builds Lighthouse"))
    reflect_loop(llm, answer=ANSWER)
    retained = await clients.own.aretain(
        bank_id=clients.bank_id, content=ANSWER, retain_async=True, document_id="lighthouse"
    )
    assert retained.operation_id is not None
    await wait_until_settled(clients.own, clients.bank_id)
    created = await clients.own.acreate_knowledge_page(
        clients.bank_id, name="Lighthouse team", source_query="What does Alice build?", trigger={"mode": "full"}
    )
    await wait_until_settled(clients.own, clients.bank_id)
    operation = await clients.own.operations.get_operation_status(clients.bank_id, created.operation_id)
    assert operation.status == "completed"
    return created


async def test_knowledge_only_key_reads_nonempty_page_over_rest_and_mcp(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    nonempty_page: CreateKnowledgePageResponse,
) -> None:
    clients = contextdb_clients
    tree = await clients.knowledge_only.aget_knowledge_base_tree(clients.bank_id)
    assert [(node.id, node.name, node.mental_model_id) for node in tree.roots] == [
        (nonempty_page.page_id, "Lighthouse team", nonempty_page.mental_model_id)
    ]
    page = await clients.knowledge_only.aget_knowledge_page(clients.bank_id, nonempty_page.page_id)
    assert page.body == ANSWER + "\n"
    results = await clients.knowledge_only.asearch_knowledge_base(clients.bank_id, "Lighthouse")
    assert [(item.id, item.name, item.snippet, item.score) for item in results.results] == [
        (nonempty_page.page_id, "Lighthouse team", ANSWER, 1.0)
    ]
    bundle = await clients.knowledge_only.aexport_knowledge_base(clients.bank_id)
    assert any(item.content.endswith(ANSWER + "\n") for item in bundle.files if item.path != "index.md")

    # This is the generated SDK's credential, not a manually fabricated identity.
    credential = clients.knowledge_only._api_client.configuration.access_token
    async with Client(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=credential) as mcp:
        names = {tool.name for tool in await mcp.list_tools()}
        assert {"get_knowledge_base_tree", "get_knowledge_page", "search_knowledge_base"} <= names
        assert {"recall", "get_mental_model", "get_bank_profile", "create_knowledge_page"}.isdisjoint(names)
        result = await mcp.call_tool("get_knowledge_page", {"page_id": nonempty_page.page_id})
        assert not result.is_error
        content = json.loads(result.content[0].text)
        assert content["id"] == nonempty_page.page_id
        assert content["markdown"] == page.markdown


async def test_knowledge_scope_does_not_open_model_traces_or_raw_exports(
    contextdb_clients: MemberClients, nonempty_page: CreateKnowledgePageResponse
) -> None:
    clients = contextdb_clients
    # Audit/trace lack wrapper accessors, so use their published generated SDKs
    # on the very same authenticated client, not an ad-hoc HTTP request.
    traces = await LLMTracesApi(clients.own._api_client).list_llm_requests(clients.bank_id)
    assert traces.total > 0
    knowledge = clients.knowledge_only
    with pytest.raises(ForbiddenException):
        await knowledge.aget_mental_model(clients.bank_id, nonempty_page.mental_model_id)
    with pytest.raises(ForbiddenException):
        await knowledge.mental_models.get_mental_model(
            clients.bank_id, nonempty_page.mental_model_id, _headers={"read_origin": "knowledge_page"}
        )
    with pytest.raises(ForbiddenException):
        await knowledge.banks.get_bank_config(clients.bank_id)
    with pytest.raises(ForbiddenException):
        await LLMTracesApi(knowledge._api_client).list_llm_requests(clients.bank_id)
    with pytest.raises(ForbiddenException):
        await AuditApi(knowledge._api_client).list_audit_logs(clients.bank_id)
    with pytest.raises(ForbiddenException):
        await knowledge.document_transfer.export_documents(clients.bank_id)
    with pytest.raises(ForbiddenException):
        await knowledge.bank_transfer.export_bank_transfer(clients.bank_id)
    with pytest.raises(ForbiddenException):
        await knowledge.document_transfer.download_file(f"banks/{clients.bank_id}/known-export.zip")
    with pytest.raises(ForbiddenException):
        await knowledge.aget_knowledge_page(clients.other_bank_id, nonempty_page.page_id)
    with pytest.raises(ForbiddenException):
        await knowledge.acreate_knowledge_folder(clients.bank_id, "Forbidden folder")
    with pytest.raises(ForbiddenException):
        await knowledge.aupdate_knowledge_node(clients.bank_id, nonempty_page.page_id, name="Forbidden rename")
    with pytest.raises(ForbiddenException):
        await knowledge.adelete_knowledge_node(clients.bank_id, nonempty_page.page_id)


async def test_knowledge_crud_and_automatic_worker_refresh_remain_coherent(
    contextdb_clients: MemberClients, nonempty_page: CreateKnowledgePageResponse, llm: LLMStub
) -> None:
    clients = contextdb_clients
    before = await clients.own.operations.list_operations(clients.bank_id, type="refresh_mental_model", limit=100)
    old_ids = {operation.operation_id for operation in before.operations}
    folder = await clients.own.acreate_knowledge_folder(clients.bank_id, "Engineering")
    await clients.own.aupdate_knowledge_node(
        clients.bank_id, nonempty_page.page_id, name="Engineering team", parent_id=folder.id
    )
    llm.on_step("extract_facts", contains="Bob").returns(
        extracted(fact("Bob joins Lighthouse", who="Bob", entities=["Bob", "Lighthouse"]))
    )
    await clients.own.aretain(
        bank_id=clients.bank_id, content="Bob joins Lighthouse.", retain_async=True, document_id="bob"
    )
    await wait_until_settled(clients.own, clients.bank_id)
    after = await clients.own.operations.list_operations(clients.bank_id, type="refresh_mental_model", limit=100)
    new_operations = [operation for operation in after.operations if operation.operation_id not in old_ids]
    assert new_operations
    assert all(operation.status == "completed" for operation in new_operations)
    page = await clients.knowledge_only.aget_knowledge_page(clients.bank_id, nonempty_page.page_id)
    assert page.name == "Engineering team"
    assert page.body == ANSWER + "\n"
    tree = await clients.knowledge_only.aget_knowledge_base_tree(clients.bank_id)
    assert [node.id for node in tree.roots] == [folder.id]
    assert [node.id for node in tree.roots[0].children] == [nonempty_page.page_id]
    await clients.own.adelete_knowledge_node(clients.bank_id, folder.id)
    assert (await clients.knowledge_only.aget_knowledge_base_tree(clients.bank_id)).roots == []
    # Deleting derived content must not delete the retained evidence underneath.
    memories = await clients.own.memory.list_memories(clients.bank_id, document_id="lighthouse", limit=100)
    assert [item.text for item in memories.items] == ["Alice builds Lighthouse | Involving: Alice"]
