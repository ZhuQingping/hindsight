"""Shared ContextBase client resolution logic."""

from importlib import metadata
from typing import Any, Optional

from hindsight_client import Hindsight

from .config import get_config
from .errors import HindsightError

try:
    _VERSION = metadata.version("contextbase-ag2")
except metadata.PackageNotFoundError:
    _VERSION = "0.0.0"
_USER_AGENT = f"contextbase-ag2/{_VERSION}"


def resolve_client(
    client: Optional[Hindsight],
    contextbase_api_url: Optional[str],
    api_key: Optional[str],
) -> Hindsight:
    """Resolve a ContextBase client from explicit args or global config."""
    if client is not None:
        return client

    config = get_config()
    url = contextbase_api_url or (config.contextbase_api_url if config else None)
    key = api_key or (config.api_key if config else None)

    if url is None:
        raise HindsightError(
            "No ContextBase API URL configured. Pass client= or contextbase_api_url=, or call configure() first."
        )

    kwargs: dict[str, Any] = {"base_url": url, "timeout": 30.0, "user_agent": _USER_AGENT}
    if key:
        kwargs["api_key"] = key
    if not kwargs.get("base_url"):
        raise ValueError("Configure the ContextBase API URL explicitly before connecting.")
    return Hindsight(**kwargs)
