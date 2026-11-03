"""ContextBase memory integration for LlamaIndex agents.

Provides two complementary patterns:

- **Tools** (``ContextBaseToolSpec``, ``create_contextbase_tools``):
  Agent-driven memory via LlamaIndex's ``BaseToolSpec``.
  The agent decides when to retain/recall/reflect.

- **Memory** (``ContextBaseMemory``):
  Automatic memory via LlamaIndex's ``BaseMemory`` interface.
  Messages are stored on ``put()`` and recalled on ``get()``.

Usage::

    from contextbase_llamaindex import ContextBaseToolSpec, create_contextbase_tools
    from contextbase_llamaindex import ContextBaseMemory
"""

from .config import (
    ContextBaseLlamaIndexConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBaseError
from .memory import ContextBaseMemory
from .tools import ContextBaseToolSpec, create_contextbase_tools

__version__ = "0.1.2"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseLlamaIndexConfig",
    "ContextBaseError",
    "ContextBaseToolSpec",
    "create_contextbase_tools",
    "ContextBaseMemory",
]
