"""ContextBase-Pydantic AI: Persistent memory tools for AI agents.

Provides ContextBase-backed tools and instructions for Pydantic AI agents,
giving them long-term memory across runs.

Basic usage::

    from hindsight_client import Hindsight
    from contextbase_pydantic_ai import create_contextbase_tools, memory_instructions
    from pydantic_ai import Agent

    client = Hindsight(base_url="", api_key="hsk_...")

    agent = Agent(
        "openai:gpt-4o",
        tools=create_contextbase_tools(client=client, bank_id="user-123"),
        instructions=[memory_instructions(client=client, bank_id="user-123")],
    )

    result = await agent.run("What do you remember about my preferences?")
"""

from .config import (
    ContextBasePydanticAIConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import create_contextbase_tools, memory_instructions

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBasePydanticAIConfig",
    "HindsightError",
    "create_contextbase_tools",
    "memory_instructions",
]
