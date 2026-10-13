"""Pure MCP protocol regressions: hidden engine faults, not refusals, signal admission.

In-process FastMCP clients exercise native registration and JSON serialization
without PostgreSQL, a live deployment, credentials or a service-only tool API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastmcp import Client, FastMCP
from hindsight_api import MemoryEngine
from hindsight_api.api import mcp as native_mcp
from hindsight_api.extensions import AuthenticationError
from hindsight_api.extensions.operation_validator import OperationValidationError
from hindsight_api.mcp_tools import MCPToolsConfig, register_mcp_tools
from mcp.types import TextContent
from pydantic import BaseModel
from starlette.requests import Request


@dataclass(frozen=True)
class ToolCall:
    name: str
    engine_method: str
    # Tool arguments are genuinely dynamic across these unrelated public tools.
    arguments: dict[str, Any]


class ToolFailure(BaseModel):
    error: str | None = None
    status: str | None = None
    message: str | None = None


FAULT_CASES = [
    ToolCall("retain", "submit_async_retain", {"content": "synthetic fault probe"}),
    ToolCall("sync_retain", "retain_batch_async", {"content": "synthetic fault probe"}),
    ToolCall("recall", "recall_async", {"query": "synthetic fault probe"}),
    ToolCall("reflect", "reflect_async", {"query": "synthetic fault probe"}),
    ToolCall("list_banks", "list_banks", {}),
    ToolCall("create_bank", "ensure_bank_profile", {"bank_id": "synthetic-bank"}),
    ToolCall("get_bank_stats", "get_bank_stats", {}),
    ToolCall("get_document", "get_document", {"document_id": "synthetic-document"}),
]


def _memory() -> MagicMock:
    memory = MagicMock(spec=MemoryEngine)
    memory._config_resolver = MagicMock()
    memory._config_resolver.get_bank_config = AsyncMock(return_value={})
    memory._operation_validator = None
    memory.resolve_bank_alias = AsyncMock(side_effect=lambda bank_id, **_: bank_id)
    # No audit I/O is necessary for the tool-error protocol itself.
    memory.audit_logger = MagicMock()
    memory.audit_logger.action_allowed.return_value = False
    return memory


async def _call(memory: MagicMock, tool: ToolCall, *, multi_bank: bool, reporter: Mock | None) -> ToolFailure:
    server = FastMCP("fault-reporting-probe")
    config = MCPToolsConfig(
        bank_id_resolver=lambda: "synthetic-bank",
        include_bank_id_param=multi_bank,
        tools={tool.name},
        failure_reporter=reporter,
    )
    register_mcp_tools(server, cast(MemoryEngine, memory), config)
    async with Client(server) as client:
        result = await client.call_tool(tool.name, tool.arguments, raise_on_error=False)
    # Native tools historically encode failures as success-shaped JSON; this
    # test deliberately verifies that the extension need not parse that content.
    assert not result.is_error
    assert len(result.content) == 1
    content = result.content[0]
    assert isinstance(content, TextContent)
    return ToolFailure.model_validate_json(content.text)


@pytest.mark.parametrize("multi_bank", [False, True], ids=["session-bank", "explicit-bank"])
@pytest.mark.parametrize("tool", FAULT_CASES, ids=lambda tool: tool.name)
@pytest.mark.parametrize("reported", [False, True], ids=["default-noop", "server-reporter"])
async def test_unexpected_fault_reports_without_changing_protocol(
    multi_bank: bool, tool: ToolCall, reported: bool
) -> None:
    memory = _memory()
    engine_call = AsyncMock(side_effect=RuntimeError("synthetic uncertain engine write"))
    setattr(memory, tool.engine_method, engine_call)
    reporter = Mock() if reported else None
    failure = await _call(memory, tool, multi_bank=multi_bank, reporter=reporter)
    assert (failure.error or failure.message) == "synthetic uncertain engine write"
    engine_call.assert_awaited_once()
    if reporter is not None:
        reporter.assert_called_once_with()  # No exception, memory or credential payload.


@pytest.mark.parametrize("multi_bank", [False, True], ids=["session-bank", "explicit-bank"])
@pytest.mark.parametrize("tool", FAULT_CASES, ids=lambda tool: tool.name)
@pytest.mark.parametrize("kind", ["scope", "authentication"])
async def test_permission_refusal_does_not_report_fault(multi_bank: bool, tool: ToolCall, kind: str) -> None:
    memory = _memory()
    refusal = (
        OperationValidationError("synthetic read-only refusal")
        if kind == "scope"
        else AuthenticationError("synthetic revoked before gate")
    )
    engine_call = AsyncMock(side_effect=refusal)
    setattr(memory, tool.engine_method, engine_call)
    reporter = Mock()
    failure = await _call(memory, tool, multi_bank=multi_bank, reporter=reporter)
    assert (failure.error or failure.message) == str(refusal)
    engine_call.assert_awaited_once()
    reporter.assert_not_called()


@pytest.mark.parametrize("multi_bank", [False, True], ids=["session-bank", "explicit-bank"])
async def test_successful_retain_does_not_report_fault(multi_bank: bool) -> None:
    memory = _memory()
    memory.submit_async_retain = AsyncMock(return_value={"operation_id": "synthetic-operation"})
    reporter = Mock()
    result = await _call(memory, FAULT_CASES[0], multi_bank=multi_bank, reporter=reporter)
    assert result.status == "accepted"
    memory.submit_async_retain.assert_awaited_once()
    reporter.assert_not_called()


@pytest.mark.parametrize("multi_bank", [False, True], ids=["session-bank", "explicit-bank"])
async def test_unclassified_value_error_is_still_a_fault(multi_bank: bool) -> None:
    memory = _memory()
    memory.get_document = AsyncMock(side_effect=ValueError("synthetic engine corruption"))
    reporter = Mock()
    failure = await _call(memory, FAULT_CASES[-1], multi_bank=multi_bank, reporter=reporter)
    assert failure.error == "synthetic engine corruption"
    reporter.assert_called_once_with()


@pytest.mark.parametrize("multi_bank", [False, True], ids=["session-bank", "explicit-bank"])
@pytest.mark.parametrize("kind", ["not-found", "expected-value", "rejected-value", "bad-timestamp"])
async def test_expected_negative_answers_do_not_report_fault(multi_bank: bool, kind: str) -> None:
    memory = _memory()
    if kind == "not-found":
        tool = ToolCall("get_document", "get_document", {"document_id": "missing"})
        memory.get_document = AsyncMock(return_value=None)
    elif kind == "expected-value":
        tool = ToolCall("create_knowledge_folder", "create_knowledge_folder", {"name": "duplicate"})
        memory.create_knowledge_folder = AsyncMock(side_effect=ValueError("synthetic duplicate folder"))
    elif kind == "rejected-value":
        tool = ToolCall("update_bank", "update_bank", {"name": "invalid"})
        memory.update_bank = AsyncMock(side_effect=ValueError("synthetic invalid profile"))
    else:
        tool = ToolCall("retain", "submit_async_retain", {"content": "probe", "timestamp": "invalid"})
        memory.submit_async_retain = AsyncMock()
    reporter = Mock()
    failure = await _call(memory, tool, multi_bank=multi_bank, reporter=reporter)
    assert failure.error or failure.message
    reporter.assert_not_called()
    if kind == "bad-timestamp":
        memory.submit_async_retain.assert_not_awaited()


def test_http_reporter_resolves_current_message_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    first = Mock()
    second = Mock()
    requests = [
        Request({"type": "http", "hindsight.request_context_failure": first}),
        Request({"type": "http", "hindsight.request_context_failure": second}),
        Request({"type": "http"}),
    ]
    monkeypatch.setattr(native_mcp, "get_http_request", Mock(side_effect=requests))
    for _ in requests:
        native_mcp._report_request_failure()
    first.assert_called_once_with()
    second.assert_called_once_with()


def test_http_reporter_is_noop_without_http_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(native_mcp, "get_http_request", Mock(side_effect=RuntimeError("no HTTP transport")))
    native_mcp._report_request_failure()
