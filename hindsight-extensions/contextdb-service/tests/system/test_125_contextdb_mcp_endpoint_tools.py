"""Single-Bank discovery cannot inherit root-only tools from global registration."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import aclosing

import pytest
from contextbase_client import ContextBase
from contextbase_client_api.models.bank_config_update import BankConfigUpdate
from fastmcp import Client
from hindsight_system_tests.server import StubServer

from .support.clients import clients_owner
from .support.deployment import ContextDBDeployment, DeploymentOptions, deployment_owner

pytestmark = pytest.mark.asyncio


@pytest.fixture(params=["embedded-worker", "standalone-worker"])
def catalog_deployment(
    request: pytest.FixtureRequest,
    stub_server: StubServer,
    tmp_path_factory: pytest.TempPathFactory,
    global_tools: tuple[str, ...],
) -> Iterator[ContextDBDeployment]:
    # Each global configuration owns its API/PG/Worker; never restart or alter
    # the shared deployment used by unrelated stories.
    with deployment_owner(
        DeploymentOptions(worker_mode=request.param, mcp_enabled_tools=global_tools),
        stub_server.url,
        tmp_path_factory.mktemp("contextdb-mcp-catalog"),
    ) as deployment:
        yield deployment


@pytest.mark.parametrize(
    "global_tools", [("list_banks",), ("list_banks", "create_bank")], ids=["catalog", "management"]
)
async def test_single_endpoint_hides_root_catalog_under_global_only_registration(
    catalog_deployment: ContextDBDeployment,
) -> None:
    deployment = catalog_deployment
    async with (
        clients_owner(deployment) as clients,
        aclosing(
            ContextBase(
                base_url=deployment.server.url,
                api_key=deployment.headers["Authorization"].removeprefix("Bearer "),
            )
        ) as admin,
        Client(deployment.server.url + f"/mcp/{clients.bank_id}/", auth=clients.read_only_key) as single,
        Client(deployment.server.url + "/mcp/", auth=clients.read_only_key) as root,
    ):
        for policy in (None, ["list_banks"], []):
            await admin.banks.update_bank_config(
                clients.bank_id, BankConfigUpdate(updates={"mcp_enabled_tools": policy})
            )
            assert await single.list_tools() == []
            assert (await single.call_tool("list_banks", {}, raise_on_error=False)).is_error
            assert {tool.name for tool in await root.list_tools()} == ({"list_banks"} if policy != [] else set())
            result = await root.call_tool("list_banks", {}, raise_on_error=False)
            assert result.is_error is (policy == [])
            if policy != []:
                listed = json.loads(result.content[0].text)
                assert listed["total"] == 1
                assert [bank["bank_id"] for bank in listed["banks"]] == [clients.bank_id]
