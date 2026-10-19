"""ContextBase-Agno: Persistent memory tools for AI agents.

Provides a ContextBase-backed Toolkit for Agno agents,
giving them long-term memory via retain, recall, and reflect tools.

Basic usage::

    from agno.agent import Agent
    from agno.models.openai import OpenAIChat
    from contextbase_agno import ContextBaseTools, memory_instructions

    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[ContextBaseTools(
            bank_id="user-123",
            contextbase_api_url="",
        )],
        instructions=[memory_instructions(
            bank_id="user-123",
            contextbase_api_url="",
        )],
    )

    agent.print_response("What do you remember about my preferences?")
"""

from .config import (
    ContextBaseAgnoConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .tools import ContextBaseTools, memory_instructions

__version__ = "0.1.0"

__all__ = [
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseAgnoConfig",
    "HindsightError",
    "ContextBaseTools",
    "memory_instructions",
]
