"""
Configuration for contextbase-agentcore.

Supports global configuration (via configure()) and per-adapter overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_CONTEXTBASE_API_URL = ""
CONTEXTBASE_API_URL_ENV = "CONTEXTBASE_API_URL"
CONTEXTBASE_API_KEY_ENV = "CONTEXTBASE_API_KEY"
CONTEXTBASE_API_TOKEN_ENV = "CONTEXTBASE_API_TOKEN"


@dataclass
class ContextBaseAgentCoreConfig:
    """Global configuration for the AgentCore–ContextBase adapter."""

    contextbase_api_url: str = DEFAULT_CONTEXTBASE_API_URL
    """ContextBase server URL."""

    api_key: str | None = None
    """API key for ContextBase Cloud. Reads CONTEXTBASE_API_KEY or CONTEXTBASE_API_TOKEN if not set."""

    recall_budget: str = "mid"
    """Recall search depth: 'low', 'mid', or 'high'."""

    recall_max_tokens: int = 1500
    """Maximum tokens in the recalled memory block."""

    retain_async: bool = True
    """If True, retain is fire-and-forget (does not block the turn response)."""

    timeout: float = 15.0
    """HTTP timeout in seconds for ContextBase API calls."""

    tags: list[str] = field(default_factory=list)
    """Default tags added to all retained memories."""

    verbose: bool = False
    """Log memory operations."""


_global_config: ContextBaseAgentCoreConfig | None = None


def configure(
    contextbase_api_url: str | None = None,
    api_key: str | None = None,
    recall_budget: str = "mid",
    recall_max_tokens: int = 1500,
    retain_async: bool = True,
    timeout: float = 15.0,
    tags: list[str] | None = None,
    verbose: bool = False,
) -> ContextBaseAgentCoreConfig:
    """Set the global ContextBase configuration for AgentCore adapters.

    Call once at application startup, before creating any adapters.

    Example:
        from contextbase_agentcore import configure

        configure(
            contextbase_api_url="",
            api_key=os.environ["CONTEXTBASE_API_KEY"],
        )
    """
    global _global_config

    resolved_url = contextbase_api_url or os.environ.get(CONTEXTBASE_API_URL_ENV) or DEFAULT_CONTEXTBASE_API_URL
    resolved_key = api_key or os.environ.get(CONTEXTBASE_API_KEY_ENV) or os.environ.get(CONTEXTBASE_API_TOKEN_ENV)

    _global_config = ContextBaseAgentCoreConfig(
        contextbase_api_url=resolved_url,
        api_key=resolved_key,
        recall_budget=recall_budget,
        recall_max_tokens=recall_max_tokens,
        retain_async=retain_async,
        timeout=timeout,
        tags=tags or [],
        verbose=verbose,
    )
    return _global_config


def get_config() -> ContextBaseAgentCoreConfig | None:
    """Return the current global config, or None if not yet configured."""
    return _global_config


def reset_config() -> None:
    """Reset the global config to None. Useful in tests."""
    global _global_config
    _global_config = None
