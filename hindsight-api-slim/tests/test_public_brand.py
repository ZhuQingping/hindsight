"""Check real protocol encodings and distinguish diagnostic text from customer data."""

import hashlib
import hmac
import json
import logging
import subprocess
import sys
import time

import pytest
from aiohttp import web
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hindsight_api.config import HindsightConfig, load_dotenv_for_entrypoint, normalize_config_key
from hindsight_api.engine.memory_engine import MemoryEngine
from hindsight_api.public_errors import PUBLIC_INTERNAL_ERROR, public_error_message
from hindsight_api.public_logging import PublicLogFormatter
from hindsight_api.telemetry_export import CustomerSpanExporter
from hindsight_api.webhooks.manager import WebhookManager
from hindsight_api.webhooks.url_guard import GuardedWebhookClient, parse_allowlist


def test_public_config_is_an_actual_mapping(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("AGENTSTRATUM_API_PORT=9123\n")
    monkeypatch.setenv("HINDSIGHT_API_PORT", "8888")
    monkeypatch.setenv("AGENTSTRATUM_API_PORT", "9999")
    load_dotenv_for_entrypoint()
    assert HindsightConfig.from_env().port == 9123
    assert normalize_config_key("AGENTSTRATUM_API_LLM_PROVIDER") == "llm_provider"


def test_diagnostics_hide_implementation_identity():
    assert public_error_message(RuntimeError("HINDSIGHT_API_LLM_MODEL failed")) == PUBLIC_INTERNAL_ERROR
    assert public_error_message(ValueError("Invalid budget")) == "Invalid budget"


def test_console_keeps_original_record_for_internal_sink():
    record = logging.LogRecord(
        "hindsight_api.worker", logging.ERROR, __file__, 1, "Hindsight provider failed", (), None
    )
    rendered = PublicLogFormatter(logging.Formatter("%(name)s %(message)s")).format(record)
    assert "hindsight" not in rendered.casefold()
    assert record.name == "hindsight_api.worker"
    assert record.getMessage() == "Hindsight provider failed"


def test_automatic_exception_events_are_safe_but_customer_content_is_unchanged():
    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(CustomerSpanExporter(sink)))
    tracer = provider.get_tracer("agentstratum.test")
    with pytest.raises(RuntimeError):
        with tracer.start_as_current_span("agentstratum.operation") as span:
            span.set_attribute("gen_ai.input.messages", "Customer says Hindsight is useful")
            span.add_event("customer.content", {"body": "hindsight"})
            raise RuntimeError("failure in hindsight_api.engine")
    recorded = sink.get_finished_spans()[0]
    assert recorded.attributes["gen_ai.input.messages"] == "Customer says Hindsight is useful"
    assert recorded.events[0].attributes["body"] == "hindsight"
    exception = next(event for event in recorded.events if event.name == "exception")
    assert "exception.stacktrace" not in exception.attributes
    assert "hindsight" not in json.dumps(dict(exception.attributes)).casefold()
    assert recorded.status.description == PUBLIC_INTERNAL_ERROR
    assert recorded.context.trace_id == span.get_span_context().trace_id
    provider.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("secret", ["a-secret", None])
async def test_real_webhook_receiver_gets_new_headers_and_untouched_body(secret):
    received = []

    async def receive(request):
        received.append((request.headers.copy(), await request.read()))
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_post("/event", receive)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = GuardedWebhookClient(parse_allowlist(["127.0.0.1"]))
    engine = object.__new__(MemoryEngine)
    engine._webhook_client = client
    engine._webhook_manager = object.__new__(WebhookManager)
    original = '{"content": "Customer Hindsight notes", "bank_id": "hindsight-user-bank"}'
    try:
        await engine._handle_webhook_delivery(
            {
                "url": f"http://127.0.0.1:{port}/event",
                "event_type": "retain.completed",
                "secret": secret,
                "payload": original,
                "http_config": {
                    "headers": {
                        "x-agentstratum-event": "forged",
                        "X-AGENTSTRATUM-SIGNATURE": "forged",
                        "x-agentstratum-signature-v2": "forged",
                        "x-hub-signature-256": "forged",
                    }
                },
            }
        )
    finally:
        await client.close()
        await runner.cleanup()
    headers, body = received[0]
    assert body == original.encode()
    assert headers.getall("X-Agentstratum-Event") == ["retain.completed"]
    assert all("hindsight" not in name.casefold() for name in headers)
    if secret:
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert headers.getall("X-Agentstratum-Signature") == [expected]
        assert headers["X-Hub-Signature-256"] == expected
        timestamp, mac = headers["X-Agentstratum-Signature-V2"].split(",")
        timestamp = timestamp.removeprefix("t=")
        assert abs(time.time() - int(timestamp)) < 5
        expected_v2 = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(mac.removeprefix("v1="), expected_v2)
    else:
        assert "X-Agentstratum-Signature" not in headers
        assert "X-Agentstratum-Signature-V2" not in headers
        assert "X-Hub-Signature-256" not in headers


def test_actual_prometheus_exposition_uses_the_dashboard_prefix():
    # An isolated provider avoids replacing the suite's global OTel registry.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from hindsight_api.metrics import initialize_metrics, MetricsCollector; "
            "from prometheus_client import generate_latest; "
            "initialize_metrics(); collector = MetricsCollector(); "
            "collector.record_operation_result('recall', 'customer-bank', True, 0.1); "
            "print(generate_latest().decode())",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    assert "agentstratum_operation_duration" in result.stdout
    assert "hindsight" not in result.stdout.casefold()


@pytest.mark.parametrize("message", ["HINDSIGHT_API_MODEL invalid", "hindsight_api.engine failed"])
def test_failed_webhook_event_filters_only_diagnostics(message):
    from datetime import datetime, timezone

    from hindsight_api.webhooks.models import ConsolidationEventData, WebhookEvent, WebhookEventType

    event = WebhookEvent(
        event=WebhookEventType.CONSOLIDATION_COMPLETED,
        bank_id="customer-hindsight-bank",
        operation_id="op",
        status="failed",
        timestamp=datetime.now(timezone.utc),
        data=ConsolidationEventData(error_message=message),
    )
    payload = event.model_dump(mode="json")
    assert payload["data"]["error_message"] == PUBLIC_INTERNAL_ERROR
    assert payload["bank_id"] == "customer-hindsight-bank"
