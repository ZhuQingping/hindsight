"""Shared ContextBase client resolution logic."""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any

from hindsight_client import Hindsight

from .config import CONTEXTBASE_API_KEY_ENV, DEFAULT_CONTEXTBASE_API_URL, AiderConfig

try:
    _VERSION = metadata.version("contextbase-aider")
except metadata.PackageNotFoundError:
    _VERSION = "0.0.0"
_USER_AGENT = f"contextbase-aider/{_VERSION}"


def resolve_client(config: AiderConfig) -> Hindsight:
    """Build a ContextBase client from config, falling back to ``CONTEXTBASE_API_KEY``."""
    url = config.contextbase_api_url or DEFAULT_CONTEXTBASE_API_URL
    key = config.contextbase_api_token or os.environ.get(CONTEXTBASE_API_KEY_ENV)
    kwargs: dict[str, Any] = {"base_url": url, "timeout": 30.0, "user_agent": _USER_AGENT}
    if key:
        kwargs["api_key"] = key
    if not kwargs.get("base_url"):
        raise ValueError("Configure the ContextBase API URL explicitly before connecting.")
    return Hindsight(**kwargs)
