"""Stateful MCP requests use the current Key, not initialize's captured identity.

The transport's mutable bearer is intentional: real session reuse/credential
rotation must not carry a stronger Key's permissions into a later HTTP message.
All memory assertions use published SDK/MCP clients on the isolated deployment.
"""

from __future__ import annotations

from collections.abc import Generator

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from hindsight_client_api.exceptions import ForbiddenException

from hindsight_system_tests import LLMStub, wait_until_settled
from hindsight_system_tests.payloads import consolidation, extracted, fact

from . import test_100_contextdb_service as service_story
from .test_100_contextdb_service import (  # noqa: F401
    ContextDBDeployment,
    MemberClients,
)

contextdb_deployment = service_story.contextdb_deployment
contextdb_clients = service_story.contextdb_clients

pytest_plugins = ["tests.test_100_contextdb_service"]
pytestmark = pytest.mark.asyncio


class MutableBearer(httpx.Auth):
    """Change only the credential, retaining the established MCP session ID."""

    def __init__(self, credential: str) -> None:
        self.credential = credential

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self.credential}"
        yield request


async def test_stateful_session_cannot_keep_a_stronger_keys_write_scope(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    clients = contextdb_clients
    auth = MutableBearer(clients.own_key)
    transport = StreamableHttpTransport(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=auth)
    async with Client(transport) as mcp:
        assert "retain" in {tool.name for tool in await mcp.list_tools()}
        session_id = transport.get_session_id()
        assert session_id is not None, "This regression must exercise stateful MCP"
        read_only_key = clients.read_only._api_client.configuration.access_token
        assert isinstance(read_only_key, str)
        auth.credential = read_only_key
        names = {tool.name for tool in await mcp.list_tools()}
        assert "recall" in names
        assert "retain" not in names
        result = await mcp.call_tool("retain", {"content": "Forbidden session write"}, raise_on_error=False)
        assert result.is_error
        assert transport.get_session_id() == session_id
    # MCP may hide the forbidden tool; REST independently pins the scope's 403
    # and proves the test did not accidentally issue a writable replacement Key.
    with pytest.raises(ForbiddenException):
        await clients.read_only.aretain(bank_id=clients.bank_id, content="Forbidden session write")
    assert (await clients.own.memory.list_memories(clients.bank_id, limit=100)).total == 0


async def test_stateful_session_cannot_reuse_another_workspaces_identity(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients, llm: LLMStub
) -> None:
    clients = contextdb_clients
    llm.on_step("extract_facts", contains="SessionSentinel").returns(
        extracted(fact("Alice builds SessionSentinel", who="Alice", entities=["Alice", "SessionSentinel"]))
    )
    llm.on_step("consolidate").returns(consolidation())
    retained = await clients.own.aretain(
        bank_id=clients.bank_id, content="Alice builds SessionSentinel.", retain_async=True
    )
    assert retained.operation_id is not None
    await wait_until_settled(clients.own, clients.bank_id)
    auth = MutableBearer(clients.own_key)
    transport = StreamableHttpTransport(f"{contextdb_deployment.server.url}/mcp/{clients.bank_id}/", auth=auth)
    async with Client(transport) as mcp:
        session_id = transport.get_session_id()
        assert session_id is not None
        other_key = clients.other_bank._api_client.configuration.access_token
        assert isinstance(other_key, str)
        auth.credential = other_key
        result = await mcp.call_tool("recall", {"query": "What does Alice build?"}, raise_on_error=False)
        # Routing rejects the CURRENT message before native recall or admission.
        # This is a transport ToolError, not the old single-space JSON payload.
        assert result.is_error
        assert "Key cannot access this workspace" in result.content[0].text
        assert transport.get_session_id() == session_id
    # The original schema's real memory must not leak, and the rejected request
    # must not manufacture a Bank in the replacement Key's schema.
    memories = await clients.own.memory.list_memories(clients.bank_id, limit=100)
    assert [item.text for item in memories.items] == ["Alice builds SessionSentinel | Involving: Alice"]
    assert (await clients.other_bank.memory.list_memories(clients.other_bank_id, limit=100)).total == 0
