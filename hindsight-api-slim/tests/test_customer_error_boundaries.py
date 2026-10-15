"""Client failures preserve caller data while internal diagnostics stay in logs."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastmcp import FastMCP

from hindsight_api.api.http import create_app
from hindsight_api.engine.memory_engine import MemoryEngine
from hindsight_api.engine.providers.none_llm import LLMNotAvailableError, NoneLLM
from hindsight_api.extensions import AuthenticationError, OperationValidationError
from hindsight_api.mcp_tools import MCPToolsConfig, _run_tool, register_mcp_tools
from hindsight_api.public_errors import PUBLIC_INTERNAL_ERROR, public_error_message
from hindsight_api.worker.exceptions import RetryTaskAt
from hindsight_api.worker.poller import ClaimedTask, WorkerPoller


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError('relation "private.customer_keys" does not exist'),
        RuntimeError("hindsight_api.engine failed"),
        ValueError("internal shape mismatch"),
    ],
)
def test_unknown_failures_do_not_depend_on_brand(error: Exception) -> None:
    assert public_error_message(error) == PUBLIC_INTERNAL_ERROR


@pytest.mark.parametrize("error_type", [AuthenticationError, OperationValidationError])
def test_explicit_rejections_preserve_customer_identifiers(error_type: type[Exception]) -> None:
    error = error_type("customer-hindsight-bank is unavailable")
    assert public_error_message(error) == str(error)


@pytest.fixture
def memory() -> MagicMock:
    memory = MagicMock(spec=MemoryEngine)
    memory.audit_logger = None
    memory._operation_validator = None
    memory._config_resolver = MagicMock()
    memory._config_resolver.get_bank_config = AsyncMock(return_value={})
    memory.resolve_bank_alias = AsyncMock(side_effect=lambda bank_id, **_: bank_id)
    return memory


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method,body",
    [
        ("memories/recall", "recall_async", {"query": "test"}),
        ("reflect", "reflect_async", {"query": "test"}),
        ("memories", "retain_batch_async", {"items": [{"content": "test"}]}),
    ],
)
@pytest.mark.parametrize("rejected", [False, True])
async def test_http_errors_reach_the_client_with_the_right_boundary(
    memory: MagicMock, caplog: pytest.LogCaptureFixture, path: str, method: str, body: dict[str, Any], rejected: bool
) -> None:
    message = (
        "customer-hindsight-bank is unavailable" if rejected else 'relation "private.customer_keys" does not exist'
    )
    error = OperationValidationError(message, status_code=403) if rejected else RuntimeError(message)
    getattr(memory, method).side_effect = error
    app = create_app(memory, initialize_memory=False)
    with caplog.at_level(logging.ERROR):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(f"/v1/default/banks/customer-hindsight-bank/{path}", json=body)
    assert response.status_code == (403 if rejected else 500), response.text
    assert response.json() == {"detail": message if rejected else PUBLIC_INTERNAL_ERROR}
    getattr(memory, method).assert_awaited_once()
    if not rejected:
        assert message in caplog.text
        assert "Traceback" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("policy", ["fault", "expected", "rejection"])
async def test_mcp_value_error_policy_is_local(
    as_json: bool, policy: Literal["fault", "expected", "rejection"]
) -> None:
    error = ValueError("Document 'hindsight-notes.md' not found")
    result = await _run_tool(
        MCPToolsConfig(bank_id_resolver=lambda: "demo"),
        bank_id=None,
        as_json=as_json,
        action="reading document",
        run=AsyncMock(side_effect=error),
        value_error=policy,
    )
    result = json.loads(result) if as_json else result
    assert result == {"error": PUBLIC_INTERNAL_ERROR if policy == "fault" else str(error)}


@pytest.mark.asyncio
@pytest.mark.parametrize("multi_bank", [False, True])
@pytest.mark.parametrize(
    "tool_name,method,arguments",
    [
        ("retain", "submit_async_retain", {"content": "test"}),
        ("sync_retain", "retain_batch_async", {"content": "test"}),
        ("recall", "recall_async", {"query": "test"}),
        ("reflect", "reflect_async", {"query": "test"}),
        ("list_banks", "list_banks", {}),
    ],
)
async def test_registered_mcp_tools_hide_internal_failures(
    memory: MagicMock,
    caplog: pytest.LogCaptureFixture,
    multi_bank: bool,
    tool_name: str,
    method: str,
    arguments: dict[str, str],
) -> None:
    message = 'relation "private.customer_keys" does not exist'
    getattr(memory, method).side_effect = RuntimeError(message)
    mcp = FastMCP("customer-errors")
    register_mcp_tools(
        mcp,
        memory,
        MCPToolsConfig(
            bank_id_resolver=lambda: "customer-hindsight-bank", include_bank_id_param=multi_bank, tools={tool_name}
        ),
    )
    tool = await mcp.get_tool(tool_name)
    with caplog.at_level(logging.ERROR):
        result = await tool.fn(**arguments)
    result = json.loads(result) if isinstance(result, str) else result
    field = "message" if tool_name in {"retain", "sync_retain"} else "error"
    assert result[field] == PUBLIC_INTERNAL_ERROR
    getattr(memory, method).assert_awaited_once()
    assert message in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_worker_classifies_before_persisting_and_keeps_diagnostics(
    caplog: pytest.LogCaptureFixture, rejected: bool
) -> None:
    message = "customer-hindsight-bank denied" if rejected else 'relation "private.customer_keys" does not exist'
    error = OperationValidationError(message) if rejected else RuntimeError(message)
    poller = WorkerPoller(backend=MagicMock(), worker_id="error-test", executor=AsyncMock(side_effect=error))
    poller._mark_failed = AsyncMock()
    task = ClaimedTask(
        operation_id=str(uuid.uuid4()), task_dict={"type": "batch_retain", "bank_id": "demo"}, schema=None
    )
    with caplog.at_level(logging.ERROR):
        await poller._execute_task_inner(task, None)
    poller._mark_failed.assert_awaited_once_with(
        task.operation_id, str(error) if rejected else PUBLIC_INTERNAL_ERROR, None
    )
    assert message in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_task_failure_webhook_is_classified_at_the_producer(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, rejected: bool
) -> None:
    message = "customer-hindsight-bank denied" if rejected else 'relation "private.customer_keys" does not exist'
    error = OperationValidationError(message) if rejected else RuntimeError(message)
    engine = object.__new__(MemoryEngine)
    engine._audit_logger = None
    engine._webhook_manager = MagicMock()
    engine._webhook_manager.fire_event = AsyncMock()
    engine._get_backend = AsyncMock()
    engine._handle_consolidation = AsyncMock(side_effect=error)
    engine._has_other_pending_consolidation = AsyncMock(return_value=False)
    engine._mark_operation_failed = AsyncMock()
    conn = MagicMock()
    conn.fetchrow = AsyncMock(return_value={"status": "pending"})

    @asynccontextmanager
    async def acquire(_backend: object) -> AsyncIterator[MagicMock]:
        yield conn

    monkeypatch.setattr("hindsight_api.engine.memory_engine.acquire_with_retry", acquire)
    task = {"type": "consolidation", "operation_id": str(uuid.uuid4()), "bank_id": "customer-hindsight-bank"}
    with caplog.at_level(logging.ERROR), pytest.raises((RetryTaskAt, OperationValidationError)):
        await engine.execute_task(task)
    event = engine._webhook_manager.fire_event.call_args.args[0]
    payload = event.model_dump(mode="json")
    assert payload["data"]["error_message"] == (str(error) if rejected else PUBLIC_INTERNAL_ERROR)
    assert payload["bank_id"] == "customer-hindsight-bank"
    assert message in caplog.text
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.asyncio
async def test_missing_model_has_actionable_customer_text() -> None:
    llm = NoneLLM(provider="none", api_key="", base_url="", model="none")
    with pytest.raises(LLMNotAvailableError) as raised:
        await llm.call(messages=[])
    message = public_error_message(raised.value)
    assert "No language model is configured" in message
    assert "service administrator" in message
    assert "HINDSIGHT_API" not in message


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [False, True])
async def test_retry_preserves_classification_without_exposing_internal_cause(
    rejected: bool, caplog: pytest.LogCaptureFixture
) -> None:
    from datetime import datetime, timezone

    message = "customer-hindsight-bank denied" if rejected else 'relation "private.customer_keys" does not exist'
    error = OperationValidationError(message) if rejected else RuntimeError(message)
    retry_at = datetime.now(timezone.utc)

    async def retrying(_task: dict[str, Any]) -> None:
        try:
            raise error
        except Exception as caught:
            raise RetryTaskAt(retry_at, str(caught)) from caught

    poller = WorkerPoller(backend=MagicMock(), worker_id="retry-test", executor=retrying)
    poller._schedule_retry = AsyncMock()
    task = ClaimedTask(
        operation_id=str(uuid.uuid4()), task_dict={"type": "batch_retain", "bank_id": "demo"}, schema=None
    )
    with caplog.at_level(logging.WARNING):
        await poller._execute_task_inner(task, None)
    poller._schedule_retry.assert_awaited_once_with(
        task.operation_id, retry_at, str(error) if rejected else PUBLIC_INTERNAL_ERROR, None
    )
    assert message in caplog.text
    assert any(record.exc_info for record in caplog.records)
