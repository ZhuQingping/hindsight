"""Shared ContextBase client resolution logic."""

from __future__ import annotations

import os
from typing import Any

from contextbase_client import ContextBase

from ._version import __version__
from .config import CONTEXTBASE_API_KEY_ENV, DEFAULT_CONTEXTBASE_API_URL, get_config

_USER_AGENT = f"contextbase-claude-agent-sdk/{__version__}"


def resolve_client(
    client: ContextBase | None,
    contextbase_api_url: str | None,
    api_key: str | None,
) -> ContextBase:
    """Resolve a ContextBase client from explicit args or global config.

    Falls back to the default API URL and the ``CONTEXTBASE_API_KEY`` env var
    when neither an explicit argument nor a prior ``configure()`` call supplied
    them, so the tools and hooks work with nothing but the env var set.
    Self-hosted users override the URL. The API key is optional at construction
    time — a missing key only fails when a call is actually made.
    """
    if client is not None:
        return client

    config = get_config()
    url = contextbase_api_url or (config.contextbase_api_url if config else DEFAULT_CONTEXTBASE_API_URL)
    # Read CONTEXTBASE_API_KEY directly so the no-configure() path still honours
    # the env var — the base ContextBase client doesn't fall back to it on its own.
    key = api_key or (config.api_key if config else None) or os.environ.get(CONTEXTBASE_API_KEY_ENV)

    kwargs: dict[str, Any] = {"base_url": url, "timeout": 30.0, "user_agent": _USER_AGENT}
    if key:
        kwargs["api_key"] = key
    if not kwargs.get("base_url"):
        raise ValueError("Configure the ContextBase API URL explicitly before connecting.")
    return ContextBase(**kwargs)
