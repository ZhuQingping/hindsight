"""Diagnostic boundary for customer OTLP traces, including auto-instrumentation."""

from collections.abc import Sequence

from opentelemetry.sdk.trace import Event, ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import Status

from .public_errors import public_error_message


def public_span(span: ReadableSpan) -> ReadableSpan:
    """Copy diagnostic fields; leave customer prompts, results and IDs untouched."""
    events = []
    for event in span.events:
        if event.name != "exception":
            events.append(event)
            continue
        attributes = dict(event.attributes or {})
        attributes.pop("exception.stacktrace", None)
        for key in ("exception.message", "exception.type"):
            if key in attributes:
                attributes[key] = public_error_message(attributes[key])
        events.append(Event(event.name, attributes, event.timestamp))
    attributes = dict(span.attributes or {})
    for key in ("exception.stacktrace", "code.filepath", "code.file.path"):
        attributes.pop(key, None)
    for key in ("error.type", "exception.type", "exception.message"):
        if key in attributes:
            attributes[key] = public_error_message(attributes[key])
    status = span.status
    if status.description:
        status = Status(status.status_code, public_error_message(status.description))
    return ReadableSpan(
        name=span.name,
        context=span.context,
        parent=span.parent,
        resource=span.resource,
        attributes=attributes,
        events=events,
        links=span.links,
        kind=span.kind,
        status=status,
        start_time=span.start_time,
        end_time=span.end_time,
        instrumentation_scope=span.instrumentation_scope,
    )


class CustomerSpanExporter(SpanExporter):
    """Wrap the real exporter, preserving flush, shutdown and export results."""

    def __init__(self, delegate: SpanExporter) -> None:
        self.delegate = delegate

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        return self.delegate.export([public_span(span) for span in spans])

    def shutdown(self) -> None:
        self.delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self.delegate.force_flush(timeout_millis)
