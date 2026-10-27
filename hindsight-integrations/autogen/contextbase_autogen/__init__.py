"""ContextBase-AutoGen: Persistent memory tools for AutoGen agents.

Provides ``FunctionTool`` instances that give AutoGen agents long-term memory
via ContextBase's retain/recall/reflect APIs.

Basic usage::

    from contextbase_client import ContextBase
    from contextbase_autogen import create_contextbase_tools

    client = ContextBase(base_url="http://localhost:8888")
    tools = create_contextbase_tools(client=client, bank_id="user-123")

    # Use with an AutoGen AssistantAgent
    agent = AssistantAgent(name="assistant", model_client=model, tools=tools)
"""

from .config import (
    ContextBaseAutoGenConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBaseError
from .tools import create_contextbase_tools

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseAutoGenConfig",
    "ContextBaseError",
    "create_contextbase_tools",
]
