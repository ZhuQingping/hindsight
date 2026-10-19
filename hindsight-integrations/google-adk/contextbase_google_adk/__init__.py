"""ContextBase memory integration for Google ADK agents.

Provides two complementary patterns:

- **Automatic memory** (``ContextBaseMemoryService``):
  Implements ADK's ``BaseMemoryService``. Pass an instance to
  ``Runner(memory_service=...)`` and sessions are retained on completion,
  with ``search_memory`` queries served from ContextBase.

- **Explicit tools** (``create_contextbase_tools``):
  ADK ``FunctionTool`` wrappers for retain / recall / reflect, so agents can
  call ContextBase directly from inside a turn.

Usage::

    from contextbase_google_adk import ContextBaseMemoryService, create_contextbase_tools
"""

from .config import (
    ContextBaseAdkConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .memory import ContextBaseMemoryService
from .tools import create_contextbase_tools

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseAdkConfig",
    "HindsightError",
    "ContextBaseMemoryService",
    "create_contextbase_tools",
]
