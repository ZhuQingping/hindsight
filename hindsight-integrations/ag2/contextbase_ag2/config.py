"""Global configuration for ContextBase-AG2 integration."""

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_CONTEXTBASE_API_URL = ""
CONTEXTBASE_API_KEY_ENV = "CONTEXTBASE_API_KEY"


@dataclass
class ContextBaseAG2Config:
    """Connection and default settings for the AG2 integration.

    Attributes:
        contextbase_api_url: URL of the ContextBase API server.
        api_key: API key for ContextBase authentication.
        budget: Default recall budget level (low/mid/high).
        max_tokens: Default maximum tokens for recall results.
        tags: Default tags applied when storing memories.
        recall_tags: Default tags to filter when searching memories.
        recall_tags_match: Tag matching mode (any/all/any_strict/all_strict).
        verbose: Enable verbose logging.
    """

    contextbase_api_url: str = DEFAULT_CONTEXTBASE_API_URL
    api_key: Optional[str] = None
    budget: str = "mid"
    max_tokens: int = 4096
    tags: Optional[list[str]] = None
    recall_tags: Optional[list[str]] = None
    recall_tags_match: str = "any"
    verbose: bool = False


_global_config: Optional[ContextBaseAG2Config] = None


def configure(
    contextbase_api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    budget: str = "mid",
    max_tokens: int = 4096,
    tags: Optional[list[str]] = None,
    recall_tags: Optional[list[str]] = None,
    recall_tags_match: str = "any",
    verbose: bool = False,
) -> ContextBaseAG2Config:
    """Configure ContextBase connection and default settings.

    Args:
        contextbase_api_url: ContextBase API URL (default: production).
        api_key: API key. Falls back to CONTEXTBASE_API_KEY env var.
        budget: Default recall budget (low/mid/high).
        max_tokens: Default max tokens for recall.
        tags: Default tags for retain operations.
        recall_tags: Default tags to filter recall/search.
        recall_tags_match: Tag matching mode.
        verbose: Enable verbose logging.

    Returns:
        The configured ContextBaseAG2Config.
    """
    global _global_config

    resolved_url = contextbase_api_url or DEFAULT_CONTEXTBASE_API_URL
    resolved_key = api_key or os.environ.get(CONTEXTBASE_API_KEY_ENV)

    _global_config = ContextBaseAG2Config(
        contextbase_api_url=resolved_url,
        api_key=resolved_key,
        budget=budget,
        max_tokens=max_tokens,
        tags=tags,
        recall_tags=recall_tags,
        recall_tags_match=recall_tags_match,
        verbose=verbose,
    )

    return _global_config


def get_config() -> Optional[ContextBaseAG2Config]:
    """Get the current global configuration."""
    return _global_config


def reset_config() -> None:
    """Reset global configuration to None."""
    global _global_config
    _global_config = None
