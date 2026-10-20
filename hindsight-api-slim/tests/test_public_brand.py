"""Check real protocol encodings and distinguish diagnostic text from customer data."""

import hashlib
import hmac
import subprocess
import sys
import time

import pytest
from aiohttp import web
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from hindsight_api.config import HindsightConfig, load_dotenv_for_entrypoint, normalize_config_key
from hindsight_api.engine.memory_engine import MemoryEngine
from hindsight_api.extensions import OperationValidationError
from hindsight_api.public_errors import PUBLIC_INTERNAL_ERROR, public_error_message
from hindsight_api.webhooks.manager import WebhookManager
from hindsight_api.webhooks.url_guard import GuardedWebhookClient, parse_allowlist


def test_public_config_is_an_actual_mapping(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED", raising=False)
    (tmp_path / ".env").write_text("CONTEXTBASE_API_PORT=9123\n")
    monkeypatch.setenv("HINDSIGHT_API_PORT", "8888")
    monkeypatch.setenv("CONTEXTBASE_API_PORT", "9999")
    load_dotenv_for_entrypoint()
    assert HindsightConfig.from_env().port == 9123
    assert normalize_config_key("CONTEXTBASE_API_LLM_PROVIDER") == "llm_provider"


def test_unknown_errors_are_generic_and_business_rejections_are_actionable():
    assert public_error_message(RuntimeError("HINDSIGHT_API_LLM_MODEL failed")) == PUBLIC_INTERNAL_ERROR
    assert (
        public_error_message(OperationValidationError("Invalid budget"))
        == "Operation validation failed: Invalid budget"
    )


def test_internal_otlp_preserves_exception_diagnostics_and_customer_content(monkeypatch: pytest.MonkeyPatch) -> None:
    from hindsight_api import tracing

    for name in ("_tracer", "_tracing_enabled", "_provider"):
        monkeypatch.setattr(tracing, name, getattr(tracing, name))
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
    sink = InMemorySpanExporter()
    monkeypatch.setattr(tracing, "OTLPSpanExporter", lambda **kwargs: sink)
    monkeypatch.setattr(tracing.trace, "set_tracer_provider", lambda provider: None)
    tracing.initialize_tracing("contextbase-test", "http://unused.example")
    provider = tracing._provider
    try:
        tracer = provider.get_tracer("contextbase.test")
        monkeypatch.setattr(tracing, "_tracer", tracer)
        with pytest.raises(RuntimeError):
            with tracing.create_operation_span("retain", "hindsight-review") as span:
                span.set_attribute("gen_ai.input.messages", "Customer says Hindsight is useful")
                span.add_event("customer.content", {"body": "hindsight"})
                span.set_attribute("code.file.path", "/srv/hindsight_api/engine.py")
                try:
                    raise ValueError("original cause in hindsight_api")
                except ValueError as cause:
                    raise RuntimeError("failure in hindsight_api.engine") from cause
        provider.force_flush()
        recorded = sink.get_finished_spans()[0]
        assert recorded.attributes["gen_ai.input.messages"] == "Customer says Hindsight is useful"
        assert recorded.events[0].attributes["body"] == "hindsight"
        exception = next(event for event in recorded.events if event.name == "exception")
        assert "ValueError: original cause in hindsight_api" in exception.attributes["exception.stacktrace"]
        assert "RuntimeError: failure in hindsight_api.engine" in exception.attributes["exception.stacktrace"]
        assert exception.attributes["exception.message"] == "failure in hindsight_api.engine"
        assert recorded.status.description == "RuntimeError: failure in hindsight_api.engine"
        assert recorded.attributes["code.file.path"] == "/srv/hindsight_api/engine.py"
        assert recorded.name == "contextbase.retain"
        assert recorded.attributes["contextbase.bank_id"] == "hindsight-review"
        assert recorded.context.trace_id == span.get_span_context().trace_id
    finally:
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
    original = '{"content": "Customer agentstratum and Hindsight notes", "bank_id": "hindsight-user-bank"}'
    try:
        await engine._handle_webhook_delivery(
            {
                "url": f"http://127.0.0.1:{port}/event",
                "event_type": "retain.completed",
                "secret": secret,
                "payload": original,
                "http_config": {
                    "headers": {
                        "x-contextbase-event": "forged",
                        "X-CONTEXTBASE-SIGNATURE": "forged",
                        "x-contextbase-signature-v2": "forged",
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
    assert headers.getall("X-ContextBase-Event") == ["retain.completed"]
    assert all("hindsight" not in name.casefold() for name in headers)
    assert all("agentstratum" not in name.casefold() for name in headers)
    if secret:
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert headers.getall("X-ContextBase-Signature") == [expected]
        assert headers["X-Hub-Signature-256"] == expected
        timestamp, mac = headers["X-ContextBase-Signature-V2"].split(",")
        timestamp = timestamp.removeprefix("t=")
        assert abs(time.time() - int(timestamp)) < 5
        expected_v2 = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(mac.removeprefix("v1="), expected_v2)
    else:
        assert "X-ContextBase-Signature" not in headers
        assert "X-ContextBase-Signature-V2" not in headers
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
    assert "contextbase_operation_duration" in result.stdout
    assert "hindsight" not in result.stdout.casefold()
    assert "agentstratum" not in result.stdout.casefold()


@pytest.mark.parametrize("message", ["HINDSIGHT_API_MODEL invalid", "hindsight_api.engine failed"])
def test_failed_webhook_event_carries_classified_diagnostics(message):
    from datetime import datetime, timezone

    from hindsight_api.webhooks.models import ConsolidationEventData, WebhookEvent, WebhookEventType

    event = WebhookEvent(
        event=WebhookEventType.CONSOLIDATION_COMPLETED,
        bank_id="customer-hindsight-bank",
        operation_id="op",
        status="failed",
        timestamp=datetime.now(timezone.utc),
        data=ConsolidationEventData(error_message=public_error_message(RuntimeError(message))),
    )
    payload = event.model_dump(mode="json")
    assert payload["data"]["error_message"] == PUBLIC_INTERNAL_ERROR
    assert payload["bank_id"] == "customer-hindsight-bank"
