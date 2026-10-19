"""ContextBase-Composio: Persistent memory custom tools for AI agents.

Exposes ContextBase's retain, recall, and reflect operations as Composio
in-process custom tools. The ContextBase bank for each call is the Composio
session's ``user_id``, so one registered tool set isolates memory per user.

Basic usage::

    from composio import Composio
    from contextbase_composio import register_contextbase_tools

    composio = Composio()
    tools = register_contextbase_tools(
        composio,
        contextbase_api_url="",
        api_key="hsk_...",
    )

    session = composio.create(
        user_id="user-123",  # becomes the ContextBase bank_id
        experimental={"custom_tools": tools},
    )
"""

from .config import (
    ContextBaseComposioConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import (
    RecallInput,
    ReflectInput,
    RetainInput,
    memory_instructions,
    register_contextbase_tools,
)

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseComposioConfig",
    "HindsightError",
    "register_contextbase_tools",
    "memory_instructions",
    "RetainInput",
    "RecallInput",
    "ReflectInput",
]
