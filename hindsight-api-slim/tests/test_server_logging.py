"""Server stdout is operator-only and must retain actionable exception diagnostics."""

import io
import json
import logging
import sys
from collections.abc import Iterator
from contextvars import ContextVar
from types import ModuleType

import pytest

from hindsight_api.config import HindsightConfig


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    provider_logger = logging.getLogger("google_genai.models")
    provider_level = provider_logger.level
    try:
        yield
    finally:
        for handler in root.handlers[:]:
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.handlers[:] = handlers
        root.setLevel(level)
        provider_logger.setLevel(provider_level)


@pytest.mark.parametrize("log_format", ["text", "json"])
def test_default_stdout_preserves_exception_chain(
    log_format: str, monkeypatch: pytest.MonkeyPatch, restore_logging: None
) -> None:
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.delenv("CONTEXTBASE_INTERNAL_LOG_FILE", raising=False)
    # The formatter only needs the tenant context; avoid loading models or a database in this unit test.
    engine = ModuleType("hindsight_api.engine.memory_engine")
    monkeypatch.setattr(
        engine, "_current_schema", ContextVar("logging_test_schema", default="tenant-test"), raising=False
    )
    monkeypatch.setitem(sys.modules, engine.__name__, engine)

    # Exercise the real logging setup without initializing unrelated model/provider settings.
    config = object.__new__(HindsightConfig)
    config.log_format = log_format
    config.log_json_fields = None
    config.log_level = "info"
    config.configure_logging()

    try:
        try:
            raise ValueError("failure in hindsight_api.provider")
        except ValueError as cause:
            raise RuntimeError("provider request failed") from cause
    except RuntimeError:
        logging.getLogger("hindsight_api.worker").exception("Hindsight provider failed")

    rendered = output.getvalue()
    if log_format == "json":
        record = json.loads(rendered)
        assert record["logger"] == "hindsight_api.worker"
        assert record["message"] == "Hindsight provider failed"
        assert record["severity"] == "ERROR"
        assert record["tenant"] == "tenant-test"
        traceback = record["exception"]
    else:
        assert "hindsight_api.worker - Hindsight provider failed" in rendered
        traceback = rendered
    assert "Traceback (most recent call last)" in traceback
    assert "test_default_stdout_preserves_exception_chain" in traceback
    assert "ValueError: failure in hindsight_api.provider" in traceback
    assert "The above exception was the direct cause" in traceback
    assert "RuntimeError: provider request failed" in traceback


def test_text_stdout_preserves_stack_info_and_log_level(monkeypatch: pytest.MonkeyPatch, restore_logging: None) -> None:
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    config = object.__new__(HindsightConfig)
    config.log_format = "text"
    config.log_level = "warning"
    config.configure_logging()
    logger = logging.getLogger("hindsight_api.worker")
    logger.info("below configured level")
    logger.warning("operator stack", stack_info=True)
    rendered = output.getvalue()
    assert "below configured level" not in rendered
    assert "operator stack" in rendered
    assert "Stack (most recent call last)" in rendered
    assert "test_text_stdout_preserves_stack_info_and_log_level" in rendered
