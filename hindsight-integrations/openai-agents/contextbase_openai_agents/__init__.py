"""ContextBase-OpenAI-Agents: Persistent memory tools for OpenAI Agents SDK.

Provides ``FunctionTool`` instances that give OpenAI agents long-term memory
via ContextBase's retain/recall/reflect APIs.

Basic usage::

    from contextbase_client import ContextBase
    from contextbase_openai_agents import create_contextbase_tools

    client = ContextBase(base_url="http://localhost:8888")
    tools = create_contextbase_tools(client=client, bank_id="user-123")

    agent = Agent(name="assistant", tools=tools)
"""

from ._version import __version__
from .config import (
    ContextBaseOpenAIAgentsConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBaseError
from .tools import create_contextbase_tools, memory_instructions

__all__ = [
    "__version__",
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseOpenAIAgentsConfig",
    "ContextBaseError",
    "create_contextbase_tools",
    "memory_instructions",
]
