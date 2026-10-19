"""ContextBase-Superagent: Safety middleware for AI agent memory.

Wraps ContextBase memory operations with Superagent Guard (prompt injection
detection) and Redact (PII removal) for secure memory storage and retrieval.

Basic usage::

    from contextbase_superagent import SafeContextBase

    safe = SafeContextBase(
        bank_id="user-123",
        contextbase_api_url="http://localhost:8888",
        guard_model="openai/gpt-4.1-nano",
        redact_model="openai/gpt-4.1-nano",
    )

    # Content is guarded and redacted before storage
    await safe.retain("John's email is john@acme.com")

    # Queries are guarded before recall
    results = await safe.recall("What do I know about John?")
"""

from .config import (
    ContextBaseSuperagentConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import GuardBlockedError, HindsightError
from .middleware import SafeContextBase

try:
    from importlib.metadata import version as _get_version

    __version__ = _get_version("contextbase-superagent")
except Exception:
    __version__ = "0.0.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseSuperagentConfig",
    "HindsightError",
    "GuardBlockedError",
    "SafeContextBase",
]
