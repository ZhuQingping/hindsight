"""ContextBase-Claude-Agent-SDK: Persistent memory for Claude agents.

Provides an in-process MCP server with ContextBase memory tools and
automatic memory hooks for the Claude Agent SDK.

Basic usage with tools::

    from claude_agent_sdk import query, ClaudeAgentOptions
    from contextbase_claude_agent_sdk import create_contextbase_server

    server = create_contextbase_server(
        bank_id="my-agent",
        contextbase_api_url="http://localhost:8888",
    )

    async for msg in query(
        prompt="What do you remember about my preferences?",
        options=ClaudeAgentOptions(
            mcp_servers={"contextbase": server},
            allowed_tools=["mcp__contextbase__*"],
        ),
    ):
        print(msg)

With automatic memory hooks::

    from contextbase_claude_agent_sdk import create_contextbase_server, create_memory_hooks

    server = create_contextbase_server(bank_id="my-agent", contextbase_api_url="http://localhost:8888")
    hooks = create_memory_hooks(bank_id="my-agent", contextbase_api_url="http://localhost:8888")

    async for msg in query(
        prompt="Help me refactor the auth module.",
        options=ClaudeAgentOptions(
            mcp_servers={"contextbase": server},
            allowed_tools=["mcp__contextbase__*"],
            hooks=hooks,
        ),
    ):
        print(msg)
"""

from ._version import __version__
from .config import (
    ContextBaseClaudeAgentSDKConfig,
    configure,
    get_config,
    reset_config,
)
from .errors import HindsightError
from .hooks import MemoryHookConfig, create_memory_hooks
from .tools import create_contextbase_server, create_contextbase_tools

__all__ = [
    "__version__",
    "configure",
    "get_config",
    "reset_config",
    "ContextBaseClaudeAgentSDKConfig",
    "HindsightError",
    "create_contextbase_server",
    "create_contextbase_tools",
    "create_memory_hooks",
    "MemoryHookConfig",
]
