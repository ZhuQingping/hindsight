"""Cross-review: each stateful MCP message restores its own knowledge scope.

These cases combine the independently changed MCP identity restoration with a
real nonempty page, so a cached writer identity cannot hide behind an empty tree.
They reuse only isolated PG0 fixtures and published SDK/MCP operations.
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from hindsight_client_api.models.create_knowledge_page_response import CreateKnowledgePageResponse
from pydantic import BaseModel, ConfigDict

from .test_100_contextdb_service import ContextDBDeployment, MemberClients
from .test_104_contextdb_mcp_identity import MutableBearer

pytest_plugins = ["tests.test_100_contextdb_service", "tests.test_101_contextdb_knowledge"]
pytestmark = pytest.mark.asyncio


class KnowledgeDenial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: str


async def test_stateful_mcp_switches_knowledge_scope_without_retaining_writer_identity(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    nonempty_page: CreateKnowledgePageResponse,
) -> None:
    clients = contextdb_clients
    credential = clients.knowledge_only._api_client.configuration.access_token
    assert isinstance(credential, str)
    auth = MutableBearer(clients.own_key)
    transport = StreamableHttpTransport(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=auth)
    async with Client(transport) as mcp:
        session_id = transport.get_session_id()
        assert session_id is not None
        assert "retain" in {tool.name for tool in await mcp.list_tools()}
        auth.credential = credential
        names = {tool.name for tool in await mcp.list_tools()}
        assert {"retain", "get_mental_model", "get_bank_profile", "list_banks"}.isdisjoint(names)
        assert "get_knowledge_page" in names
        page = await mcp.call_tool("get_knowledge_page", {"page_id": nonempty_page.page_id})
        assert not page.is_error
        expected = await clients.knowledge_only.aget_knowledge_page(clients.bank_id, nonempty_page.page_id)
        assert json.loads(page.content[0].text)["markdown"] == expected.markdown
        for name, arguments in (
            ("get_mental_model", {"mental_model_id": nonempty_page.mental_model_id}),
            ("retain", {"content": "Forbidden cached writer identity"}),
        ):
            denied = await mcp.call_tool(name, arguments, raise_on_error=False)
            assert denied.is_error

        # Restoring must be request-local in both directions, not permanently
        # downgrade the session when a weaker Key was used once.
        auth.credential = clients.own_key
        assert "create_knowledge_folder" in {tool.name for tool in await mcp.list_tools()}
        created = await mcp.call_tool("create_knowledge_folder", {"name": "Restored writer"})
        assert not created.is_error
        assert transport.get_session_id() == session_id
    tree = await clients.knowledge_only.aget_knowledge_base_tree(clients.bank_id)
    assert {node.name for node in tree.roots} == {"Lighthouse team", "Restored writer"}
    assert (await clients.own.memory.list_memories(clients.bank_id, document_id="lighthouse", limit=100)).total == 1


async def test_stateful_mcp_knowledge_page_cannot_reuse_old_workspaces_identity(
    contextdb_deployment: ContextDBDeployment,
    contextdb_clients: MemberClients,
    nonempty_page: CreateKnowledgePageResponse,
) -> None:
    clients = contextdb_clients
    auth = MutableBearer(clients.own_key)
    transport = StreamableHttpTransport(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=auth)
    async with Client(transport) as mcp:
        session_id = transport.get_session_id()
        assert session_id is not None
        other_key = clients.other_bank._api_client.configuration.access_token
        assert isinstance(other_key, str)
        auth.credential = other_key
        denied = await mcp.call_tool("get_knowledge_page", {"page_id": nonempty_page.page_id}, raise_on_error=False)
        # Native knowledge tools encode domain refusal in their JSON payload;
        # assert an error-only shape, not MCP's transport isError bit.
        refusal = KnowledgeDenial.model_validate_json(denied.content[0].text)
        assert refusal.error == "Operation validation failed: Key cannot access another workspace Bank"
        assert transport.get_session_id() == session_id
    assert (await clients.other_bank.aget_knowledge_base_tree(clients.other_bank_id)).roots == []
