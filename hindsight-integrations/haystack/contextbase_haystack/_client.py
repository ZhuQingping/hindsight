"""Shared ContextBase client resolution logic."""

import os
from importlib import metadata
from typing import Any, Optional

from contextbase_client import ContextBase

from .config import CONTEXTBASE_API_KEY_ENV, DEFAULT_CONTEXTBASE_API_URL, get_config

try:
    _VERSION = metadata.version("contextbase-haystack")
except metadata.PackageNotFoundError:
    _VERSION = "0.0.0"
_USER_AGENT = f"contextbase-haystack/{_VERSION}"

TIMEOUT_DEFAULT = 30.0


def resolve_client(
    client: Optional[ContextBase],
    contextbase_api_url: Optional[str],
    api_key: Optional[str],
) -> ContextBase:
    """Resolve a ContextBase client from explicit args or global config.

    Falls back to the default API URL and the ``CONTEXTBASE_API_KEY`` env var when
    neither an explicit argument nor a prior ``configure()`` call supplied them,
    so the tools work with nothing but the env var set. Self-hosted users
    override the URL. The API key is optional at construction time — a missing
    key only fails when a call is actually made.
    """
    if client is not None:
        return client

    config = get_config()
    url = contextbase_api_url or (config.contextbase_api_url if config else DEFAULT_CONTEXTBASE_API_URL)
    # Read CONTEXTBASE_API_KEY directly so the no-configure() path still honours
    # the env var — the base ContextBase client doesn't fall back to it on its own.
    key = api_key or (config.api_key if config else None) or os.environ.get(CONTEXTBASE_API_KEY_ENV)

    kwargs: dict[str, Any] = {"base_url": url, "timeout": TIMEOUT_DEFAULT, "user_agent": _USER_AGENT}
    if key:
        kwargs["api_key"] = key
    if not kwargs.get("base_url"):
        raise ValueError("Configure the ContextBase API URL explicitly before connecting.")
    return ContextBase(**kwargs)
