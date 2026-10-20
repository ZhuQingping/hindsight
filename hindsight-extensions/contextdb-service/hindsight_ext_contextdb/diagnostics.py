"""Project operator-only Webhook diagnostics out of business task status reads."""

from __future__ import annotations

import json

from pydantic import JsonValue, TypeAdapter

_JSON = TypeAdapter(JsonValue)
_SENSITIVE_FIELDS = frozenset({"task_payload", "result_metadata", "error_message", "details"})


def business_operation_json(payload: str | bytes) -> str:
    """Preserve native status/list shapes while withholding delivery credentials.

    Webhook receivers may echo Authorization in their response body, which native
    delivery tasks store in result_metadata. Error text can carry that body too.
    This projection is deliberately limited to Webhook task diagnostics; normal
    retain status/results and memory content keep their native representation.
    """
    value = _JSON.validate_json(payload)
    _project(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _project(value: JsonValue) -> None:
    if isinstance(value, list):
        for item in value:
            _project(item)
    elif isinstance(value, dict):
        if value.get("operation_type") == "webhook_delivery" or value.get("task_type") == "webhook_delivery":
            for name in _SENSITIVE_FIELDS:
                if name in value:
                    value[name] = None
        # Only walk structural task containers, never customer result metadata.
        for name in ("operations", "child_operations"):
            nested = value.get(name)
            if nested is not None:
                _project(nested)
