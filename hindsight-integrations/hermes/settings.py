"""ContextBase plugin constants and pure config normalizers (no I/O, no origin imports)."""

from __future__ import annotations

import contextlib
import json
import logging
import math
from typing import Any, List
from urllib.parse import urlsplit

# Log under the plugin package's own logger name (loader-path independent).
logger = logging.getLogger(__name__.rpartition(".")[0])

_DEFAULT_API_URL = ""
_MIN_CLIENT_VERSION = "1.0.0"
_DEFAULT_TIMEOUT = 120  # seconds — cloud API can take 30-40s per request
# ``metadata.source`` on retained memories is OPT-IN (AGENTS.md forbids
# on-by-default attribution tags): ``retain_source`` / CONTEXTBASE_RETAIN_SOURCE.
_DEFAULT_RETAIN_SOURCE = ""
# Named retain strategy applied to every item this plugin stores. Empty means the bank
# decides (its ``retain_default_strategy``, else unmissioned ``concise`` extraction).
# The bank must already define the name under ``retain_strategies``.
_DEFAULT_RETAIN_STRATEGY = ""
# ContextBase brand mark (eye ringed by graph nodes) for the recall/retain indicators.
_CONTEXTBASE_GLYPH = "👁️"
# ContextBase 0.5.0 added ``update_mode='append'``; older APIs would silently
# overwrite prior turns under a stable document_id, so they keep the per-process id.
# Mirrors the OpenClaw integration — ContextBase 0.5.0 added `update_mode='append'` semantics on retain
# (the upstream append-mode change).
_MIN_VERSION_FOR_UPDATE_MODE_APPEND = "0.5.0"
_VALID_BUDGETS = {"low", "mid", "high"}
_OBSERVATION_SCOPE_KEYWORDS = {"per_tag", "combined", "all_combinations", "shared"}


def _parse_int_setting(value: Any, default: int) -> int:
    """Parse an integer config/env value, falling back on invalid input."""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer ContextBase setting %r; using default %s", value, default)
        return default


def _parse_float_setting(value: Any, default: float) -> float:
    """Parse a float config/env value, falling back on invalid input."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Invalid number for ContextBase setting %r; using default %s", value, default)
        return default


def _normalize_string_list(value: Any) -> List[str]:
    """Normalize a list-valued setting (retain tags, bank lists) to a deduplicated list of
    non-empty strings. Accepts a list, a JSON-encoded list (``'["a", "b"]'``) or
    comma-separated text (``"a, b"``): the settings panel stores ``KIND_TEXT`` fields as
    text, while a hand-written ``config.json`` usually holds a real list."""
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    if isinstance(value, str):
        text = value.strip()
        parsed = None
        if text.startswith("["):
            with contextlib.suppress(Exception):
                parsed = json.loads(text)
        raw_items = parsed if isinstance(parsed, list) else text.split(",")
    normalized: list[str] = []
    for item in raw_items:
        entry = str(item).strip()
        if entry and entry not in normalized:
            normalized.append(entry)
    return normalized


def _normalize_min_scores(value: Any) -> dict[str, float] | None:
    """Normalize ``recall_min_scores`` to ``{score_name: floor}``, or ``None`` for no floor.

    Accepts a mapping or a JSON object string. The score names are ContextBase's own
    (``reranker``, ``semantic``, ...), so they are not validated here: the server decides
    which exist. A floor that is not a finite number is dropped with a warning instead of
    being sent, so a typo can never turn into an invalid recall request."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            logger.warning("Invalid recall_min_scores %r (not valid JSON); no score floor applied", value)
            return None
    if not isinstance(value, dict):
        logger.warning("Invalid recall_min_scores %r (expected an object); no score floor applied", value)
        return None
    floors: dict[str, float] = {}
    for name, floor in value.items():
        if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not math.isfinite(floor):
            logger.warning("Ignoring recall_min_scores[%r]=%r: a floor must be a finite number", name, floor)
            continue
        floors[str(name)] = float(floor)
    return floors or None


def _clears_min_scores(result: Any, floors: dict[str, float]) -> bool:
    """Whether a recall result reports every score named in *floors* and clears each (``>=``).

    Recall fuses four retrieval arms and returns a result surfaced by any of them, so the
    ``semantic`` and ``keyword`` scores are ``None`` on a result the other arms found. The
    server only guarantees ``reranker`` and ``final`` floors (a ``semantic`` floor prunes just
    its own arm), so a result that does not report a stage named in a floor is rejected here:
    that is what lets a ``semantic`` floor abstain on an off-topic query. A result carrying no
    ``scores`` at all (a server that does not report them) is kept, there being nothing to judge it by."""
    scores = getattr(result, "scores", None)
    if scores is None:
        return True
    return all((value := getattr(scores, name, None)) is not None and value >= floor for name, floor in floors.items())


def _normalize_observation_scopes(value: Any) -> Any:
    """Normalize observation_scopes to a keyword string, ``list[list[str]]`` (one inner
    list per consolidation pass), or ``None`` (ContextBase's ``combined`` default).
    Accepts a keyword, a JSON-encoded list, a flat tag list (one scope) or a list of
    tag-lists; anything unrecognized -> ``None`` so we never send an invalid payload."""
    if isinstance(value, str):
        text = value.strip()
        if text in _OBSERVATION_SCOPE_KEYWORDS:
            return text
        if text.startswith("["):
            try:
                return _normalize_observation_scopes(json.loads(text))
            except Exception:
                return None
        return None
    if not isinstance(value, (list, tuple)):
        return None
    if all(isinstance(entry, str) for entry in value):  # flat tag list -> one scope
        value = [value]
    scopes = [
        [str(tag).strip() for tag in entry if str(tag).strip()]
        if isinstance(entry, (list, tuple))
        else [entry.strip()]
        if isinstance(entry, str) and entry.strip()
        else []
        for entry in value
    ]
    return [s for s in scopes if s] or None


def validate_api_url(value: str) -> str:
    """Require a service endpoint and preserve any API path prefix."""
    value = value.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "ContextBase API URL is required and must be an HTTP(S) endpoint without credentials, query or fragment."
        )
    return value.rstrip("/")
