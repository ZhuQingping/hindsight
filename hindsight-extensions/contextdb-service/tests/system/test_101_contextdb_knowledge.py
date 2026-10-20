"""One read permission covers nonempty knowledge and memory in its own workspace.

Reuse the dedicated PG0 deployment and both Worker variants from story 100.
All customer operations use the published SDK/MCP clients; no engine or SQL
access is used to fabricate a page or bypass its background refresh.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastmcp import Client
from hindsight_client import Hindsight
from hindsight_client_api.api.audit_api import AuditApi
from hindsight_client_api.api.llm_traces_api import LLMTracesApi
from hindsight_client_api.exceptions import ApiException, ForbiddenException
from hindsight_client_api.models.create_knowledge_page_response import (
    CreateKnowledgePageResponse,
)
from hindsight_system_tests import LLMStub, wait_until_settled
from hindsight_system_tests.payloads import extracted, fact

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment
from .support.knowledge import ANSWER

pytestmark = pytest.mark.asyncio


async def test_knowledge_reader_key_reads_nonempty_page_over_rest_and_mcp(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    nonempty_page: CreateKnowledgePageResponse,
) -> None:
    clients = contextdb_clients
    tree = await clients.knowledge_reader.aget_knowledge_base_tree(clients.bank_id)
    assert [(node.id, node.name, node.mental_model_id) for node in tree.roots] == [
        (nonempty_page.page_id, "Lighthouse team", nonempty_page.mental_model_id)
    ]
    page = await clients.knowledge_reader.aget_knowledge_page(clients.bank_id, nonempty_page.page_id)
    assert page.body == ANSWER + "\n"
    results = await clients.knowledge_reader.asearch_knowledge_base(clients.bank_id, "Lighthouse")
    assert [(item.id, item.name, item.snippet, item.score) for item in results.results] == [
        (nonempty_page.page_id, "Lighthouse team", ANSWER, 1.0)
    ]
    bundle = await clients.knowledge_reader.aexport_knowledge_base(clients.bank_id)
    assert any(item.content.endswith(ANSWER + "\n") for item in bundle.files if item.path != "index.md")

    # This is the generated SDK's credential, not a manually fabricated identity.
    credential = clients.knowledge_reader_key
    async with Client(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=credential) as mcp:
        names = {tool.name for tool in await mcp.list_tools()}
        assert {"get_knowledge_base_tree", "get_knowledge_page", "search_knowledge_base"} <= names
        assert {"recall", "reflect", "get_mental_model", "get_bank"} <= names
        assert {"retain", "create_knowledge_page", "create_bank", "delete_bank", "list_banks"}.isdisjoint(names)
        result = await mcp.call_tool("get_knowledge_page", {"page_id": nonempty_page.page_id})
        assert not result.is_error
        content = json.loads(result.content[0].text)
        assert content["id"] == nonempty_page.page_id
        assert content["markdown"] == page.markdown


async def test_reader_sees_memory_but_native_trace_is_disabled_and_admin_owns_archives(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    nonempty_page: CreateKnowledgePageResponse,
) -> None:
    clients = contextdb_clients
    # Audit/trace lack wrapper accessors, so use their published generated SDKs
    # on the very same authenticated client, not an ad-hoc HTTP request.
    traces = await LLMTracesApi(clients.own._api_client).list_llm_requests(clients.bank_id)
    # First-release ContextDB explicitly disables detached native trace writes:
    # they are not fenced against physical reuse of a readable workspace schema.
    # The authorized endpoint remains available, with no newly persisted rows.
    assert traces.total == 0 and traces.items == []
    knowledge = clients.knowledge_reader
    model = await knowledge.aget_mental_model(clients.bank_id, nonempty_page.mental_model_id)
    assert model.id == nonempty_page.mental_model_id
    visible = await knowledge.memory.list_memories(clients.bank_id, document_id="lighthouse", limit=100)
    assert [item.text for item in visible.items] == ["Alice builds Lighthouse | Involving: Alice"]
    configuration = await knowledge.banks.get_bank_config(clients.bank_id)
    assert configuration.bank_id == clients.bank_id
    assert configuration.config == configuration.overrides == {}
    assert (await LLMTracesApi(knowledge._api_client).list_llm_requests(clients.bank_id)).total == traces.total
    # Management audit can contain Webhook credentials; business content reads
    # must not grant access to those administrator records.
    with pytest.raises(ForbiddenException):
        await AuditApi(knowledge._api_client).list_audit_logs(clients.bank_id)
    # Native archives carry operational configuration (including webhook
    # credentials). Reading content does not grant backup/export authority.
    with pytest.raises(ForbiddenException):
        await knowledge.aexport_documents(bank_id=clients.bank_id)
    with pytest.raises(ForbiddenException):
        await knowledge.aexport_bank(bank_id=clients.bank_id)
    with pytest.raises(ForbiddenException):
        await knowledge.document_transfer.download_file(f"banks/{clients.bank_id}/known-export.zip")
    administrator = Hindsight(
        base_url=contextdb_deployment.server.url,
        api_key=contextdb_deployment.headers["Authorization"].removeprefix("Bearer "),
    )
    try:
        await AuditApi(administrator._api_client).list_audit_logs(clients.bank_id)
        with pytest.raises(ApiException) as rejected:
            await administrator.banks.update_bank_config(clients.bank_id, {"updates": {"audit_log_enabled": True}})
        assert rejected.value.status == 400
        # The public wrapper polls the real native worker then downloads its ZIP.
        # Inspecting the returned artifact proves the admin exported this bank,
        # rather than merely accepting a queued task or returning an empty blob.
        for archive in (
            await administrator.aexport_documents(bank_id=clients.bank_id),
            await administrator.aexport_bank(bank_id=clients.bank_id),
        ):
            with zipfile.ZipFile(io.BytesIO(archive)) as backup:
                manifest = json.loads(backup.read("manifest.json"))
                assert manifest["source_bank_id"] == clients.bank_id
                documents = [backup.read(name) for name in backup.namelist() if name.startswith("documents/")]
                assert documents and any(b"Alice builds Lighthouse" in content for content in documents)
    finally:
        await administrator.aclose()
    for bank in (clients.other_bank_id,):
        with pytest.raises(ForbiddenException):
            await knowledge.memory.list_memories(bank, limit=100)
        with pytest.raises(ForbiddenException):
            await LLMTracesApi(knowledge._api_client).list_llm_requests(bank)
        with pytest.raises(ForbiddenException):
            await knowledge.aexport_documents(bank_id=bank)
        with pytest.raises(ForbiddenException):
            await knowledge.aexport_bank(bank_id=bank)
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
    page = await clients.knowledge_reader.aget_knowledge_page(clients.bank_id, nonempty_page.page_id)
    assert page.name == "Engineering team"
    assert page.body == ANSWER + "\n"
    tree = await clients.knowledge_reader.aget_knowledge_base_tree(clients.bank_id)
    assert [node.id for node in tree.roots] == [folder.id]
    assert [node.id for node in tree.roots[0].children] == [nonempty_page.page_id]
    await clients.own.adelete_knowledge_node(clients.bank_id, folder.id)
    assert (await clients.knowledge_reader.aget_knowledge_base_tree(clients.bank_id)).roots == []
    # Deleting derived content must not delete the retained evidence underneath.
    memories = await clients.own.memory.list_memories(clients.bank_id, document_id="lighthouse", limit=100)
    assert [item.text for item in memories.items] == ["Alice builds Lighthouse | Involving: Alice"]
