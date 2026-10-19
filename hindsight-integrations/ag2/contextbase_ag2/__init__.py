"""ContextBase-AG2: Persistent memory tools for AG2 agents.

Provides ContextBase-backed tool functions that give AG2 agents long-term
memory across conversations via retain/recall/reflect operations.

Basic usage::

    from contextbase_ag2 import register_contextbase_tools

    register_contextbase_tools(
        assistant, user_proxy,
        bank_id="user-123",
        contextbase_api_url="http://localhost:8888",
    )

Manual registration::

    from contextbase_ag2 import create_contextbase_tools

    tools = create_contextbase_tools(
        bank_id="user-123",
        contextbase_api_url="http://localhost:8888",
    )
    for tool_fn in tools:
        assistant.register_for_llm(description=tool_fn.__doc__)(tool_fn)
        user_proxy.register_for_execution()(tool_fn)
"""

from .config import (
    ContextBaseAG2Config,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import create_contextbase_tools, register_contextbase_tools

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseAG2Config",
    "HindsightError",
    "create_contextbase_tools",
    "register_contextbase_tools",
]
