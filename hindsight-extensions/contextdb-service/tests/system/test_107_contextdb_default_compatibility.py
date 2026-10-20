"""The optional extension must leave an ordinary anonymous OSS server working."""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from fastmcp import Client
from hindsight_client import Hindsight
from hindsight_system_tests import wait_until_settled
from hindsight_system_tests.payloads import extracted, fact, observes
from hindsight_system_tests.server import (
    HindsightServer,
    free_port,
    start_hindsight_server,
)
from pg0 import Pg0

pytestmark = pytest.mark.asyncio


@pytest.fixture
def ordinary_server(stub_server, tmp_path) -> Iterator[HindsightServer]:
    database = Pg0(
        name=f"ordinary-contextdb-regression-{tmp_path.name}",
        port=free_port(),
        data_dir=str(tmp_path / "pg"),
        database="ordinary_story",
    )
    server = None
    try:
        info = database.start()
        assert info.uri is not None
        server = start_hindsight_server(
            stub_url=stub_server.url,
            log_path=tmp_path / "server.log",
            database_url=info.uri,
            python_executable=sys.executable,
            extra_env={"HINDSIGHT_API_MCP_ENABLED": "true"},
        )
        yield server
    finally:
        if server is not None:
            server.stop()
        database.stop()


async def test_default_oss_rest_worker_and_stateful_mcp_still_work(ordinary_server, llm) -> None:
    answer = "CompatibilityAgent works in an ordinary OSS deployment."
    llm.on_step("extract_facts").returns(extracted(fact(answer, who="CompatibilityAgent")))
    llm.on_step("consolidate").answers_with(observes(answer))
    client = Hindsight(base_url=ordinary_server.url)
    try:
        retained = await client.aretain("ordinary-bank", answer, retain_async=True)
        assert retained.operation_id is not None
        await wait_until_settled(client, "ordinary-bank")
        operation = await client.operations.get_operation_status("ordinary-bank", retained.operation_id)
        assert operation.status == "completed"
        assert (await client.arecall("ordinary-bank", "CompatibilityAgent")).results
        async with Client(f"{ordinary_server.url}/mcp/ordinary-bank/") as mcp:
            assert "recall" in {tool.name for tool in await mcp.list_tools()}
            recalled = await mcp.call_tool("recall", {"query": "CompatibilityAgent"})
            assert not recalled.is_error
            assert "CompatibilityAgent" in recalled.content[0].text
    finally:
        await client.aclose()
