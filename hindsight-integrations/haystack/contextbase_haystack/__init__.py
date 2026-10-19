"""ContextBase memory integration for Haystack agents.

Provides Haystack-compatible ``Tool`` instances backed by ContextBase's
retain/recall/reflect APIs. Use ``create_contextbase_tools()`` to create
tools for any Haystack ``Agent``.

Usage::

    from contextbase_haystack import create_contextbase_tools
    from haystack.components.agents import Agent
    from haystack.components.generators.chat import OpenAIChatGenerator

    tools = create_contextbase_tools(bank_id="user-123", client=client)
    agent = Agent(chat_generator=OpenAIChatGenerator(), tools=tools)
"""

from .config import (
    ContextBaseHaystackConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import ContextBaseMemoryWrapper, create_contextbase_tools

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseHaystackConfig",
    "HindsightError",
    "create_contextbase_tools",
    "ContextBaseMemoryWrapper",
]
