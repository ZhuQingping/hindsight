"""Shared ContextBase client resolution logic."""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any

from contextbase_client import ContextBase

from .config import CONTEXTBASE_API_KEY_ENV, DEFAULT_CONTEXTBASE_API_URL, get_config

try:
    _VERSION = metadata.version("contextbase-continue")
except metadata.PackageNotFoundError:
    _VERSION = "0.0.0"
_USER_AGENT = f"contextbase-continue/{_VERSION}"


def resolve_client(
    client: ContextBase | None = None,
    contextbase_api_url: str | None = None,
    api_key: str | None = None,
) -> ContextBase:
    """Resolve a ContextBase client from explicit args or global config.

    Falls back to the configured/default API URL and the ``CONTEXTBASE_API_KEY``
    env var so the adapter works with nothing but the env var set. The API key
    is optional at construction time — a missing key only fails when a recall
    is actually made.
    """
    if client is not None:
        return client

    config = get_config()
    url = contextbase_api_url or config.contextbase_api_url or DEFAULT_CONTEXTBASE_API_URL
    key = api_key or config.api_key or os.environ.get(CONTEXTBASE_API_KEY_ENV)

    kwargs: dict[str, Any] = {"base_url": url, "timeout": 30.0, "user_agent": _USER_AGENT}
    if key:
        kwargs["api_key"] = key
    if not kwargs.get("base_url"):
        raise ValueError("Configure the ContextBase API URL explicitly before connecting.")
    return ContextBase(**kwargs)
