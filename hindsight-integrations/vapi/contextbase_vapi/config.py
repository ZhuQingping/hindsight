"""Global configuration for the ContextBase-Vapi integration."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_CONTEXTBASE_API_URL = ""
CONTEXTBASE_API_KEY_ENV = "CONTEXTBASE_API_KEY"


@dataclass
class ContextBaseVapiConfig:
    """Connection and default settings for the Vapi integration.

    Attributes:
        contextbase_api_url: URL of the ContextBase API server.
        api_key: API key for ContextBase authentication.
        recall_budget: Default recall budget level (low/mid/high).
        recall_max_tokens: Default maximum tokens for recall results.
    """

    contextbase_api_url: str = DEFAULT_CONTEXTBASE_API_URL
    api_key: str | None = None
    recall_budget: str = "mid"
    recall_max_tokens: int = 4096


_global_config: ContextBaseVapiConfig | None = None


def configure(
    contextbase_api_url: str | None = None,
    api_key: str | None = None,
    recall_budget: str = "mid",
    recall_max_tokens: int = 4096,
) -> ContextBaseVapiConfig:
    """Configure ContextBase connection and default settings.

    Args:
        contextbase_api_url: ContextBase API URL (default: production).
        api_key: API key. Falls back to CONTEXTBASE_API_KEY env var.
        recall_budget: Default recall budget (low/mid/high).
        recall_max_tokens: Default max tokens for recall.

    Returns:
        The configured ContextBaseVapiConfig.
    """
    global _global_config

    resolved_url = contextbase_api_url or DEFAULT_CONTEXTBASE_API_URL
    resolved_key = api_key or os.environ.get(CONTEXTBASE_API_KEY_ENV)

    _global_config = ContextBaseVapiConfig(
        contextbase_api_url=resolved_url,
        api_key=resolved_key,
        recall_budget=recall_budget,
        recall_max_tokens=recall_max_tokens,
    )

    return _global_config


def get_config() -> ContextBaseVapiConfig | None:
    """Get the current global configuration."""
    return _global_config


def reset_config() -> None:
    """Reset global configuration to None."""
    global _global_config
    _global_config = None
