"""MCP uses the requested workspace before native config filtering and auditing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from contextbase_client import ContextBase
from contextbase_client_api.models.bank_config_update import BankConfigUpdate
from fastmcp import Client

from .support.clients import MemberClients
from .support.deployment import ContextDBDeployment

pytestmark = pytest.mark.asyncio


async def test_native_config_ceilings_and_concurrent_targets(
    contextdb_deployment: ContextDBDeployment, contextdb_clients: MemberClients
) -> None:
    deployment, clients = contextdb_deployment, contextdb_clients
    key = deployment.headers["Authorization"].removeprefix("Bearer ")
    log_start = len(deployment.server.logs())
    admin = ContextBase(base_url=deployment.server.url, api_key=key)
    try:
        # Admin is allowed to read overrides; business config projection remains
        # unchanged. These two ceilings distinguish actual schemas and root union.
        await admin.aupdate_bank_config(clients.bank_id, mcp_enabled_tools=["get_bank", "recall"])
        await admin.aupdate_bank_config(clients.other_bank_id, mcp_enabled_tools=["list_memories"])

        async def probe(bank: str, expected: set[str], tool: str, arguments: dict[str, Any]) -> None:
            async with Client(f"{deployment.server.url}/mcp/{bank}/", auth=key) as mcp:
                assert {item.name for item in await mcp.list_tools()} == expected
                assert not (await mcp.call_tool(tool, arguments)).is_error
                denied = await mcp.call_tool("retain", {"content": "disabled"}, raise_on_error=False)
                assert denied.is_error

        await asyncio.gather(
            probe(clients.bank_id, {"get_bank", "recall"}, "recall", {"query": "empty workspace"}),
            probe(clients.other_bank_id, {"list_memories"}, "list_memories", {}),
        )
        async with Client(deployment.server.url + "/mcp/", auth=key) as mcp:
            assert {item.name for item in await mcp.list_tools()} >= {"get_bank", "recall", "list_memories"}
            assert not (await mcp.call_tool("list_memories", {"bank_id": clients.other_bank_id})).is_error
            assert not (
                await mcp.call_tool("recall", {"bank_id": clients.bank_id, "query": "empty workspace"})
            ).is_error
            assert (
                await mcp.call_tool(
                    "recall", {"bank_id": clients.other_bank_id, "query": "disabled"}, raise_on_error=False
                )
            ).is_error
        for bearer in [clients.own_key, clients.read_only_key]:
            async with Client(f"{deployment.server.url}/mcp/{clients.bank_id}/", auth=bearer) as mcp:
                assert "recall" in {tool.name for tool in await mcp.list_tools()}
                assert not (await mcp.call_tool("recall", {"query": "empty workspace"})).is_error
        logs = deployment.server.logs()[log_start:]
        assert "Failed to load bank config" not in logs
        assert "Audit config resolution failed" not in logs
    finally:
        try:
            # These fresh Banks remain in the session deployment's directory.
            # Later stories must not inherit this test's tool restrictions.
            # The convenience method omits None; use the generated SDK to send
            # an explicit null without resetting unrelated config fields.
            restored = await asyncio.gather(
                admin.banks.update_bank_config(clients.bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": None})),
                admin.banks.update_bank_config(
                    clients.other_bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": None})
                ),
            )
            assert all(config.overrides.get("mcp_enabled_tools") is None for config in restored)
        finally:
            await admin.aclose()
