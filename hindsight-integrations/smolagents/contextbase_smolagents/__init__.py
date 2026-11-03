"""ContextBase-SmolAgents: Persistent memory tools for AI agents.

Provides ContextBase-backed Tool subclasses for SmolAgents agents,
giving them long-term memory via retain, recall, and reflect tools.

Basic usage::

    from smolagents import CodeAgent, HfApiModel
    from contextbase_smolagents import create_contextbase_tools

    tools = create_contextbase_tools(
        bank_id="user-123",
        contextbase_api_url="",
        api_key="hsk_...",
    )

    agent = CodeAgent(
        tools=tools,
        model=HfApiModel(),
    )

    agent.run("Remember that I prefer dark mode")
"""

from .config import (
    ContextBaseSmolAgentsConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import ContextBaseError
from .tools import (
    ContextBaseRecallTool,
    ContextBaseReflectTool,
    ContextBaseRetainTool,
    create_contextbase_tools,
    memory_instructions,
)

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseSmolAgentsConfig",
    "ContextBaseError",
    "ContextBaseRetainTool",
    "ContextBaseRecallTool",
    "ContextBaseReflectTool",
    "create_contextbase_tools",
    "memory_instructions",
]
