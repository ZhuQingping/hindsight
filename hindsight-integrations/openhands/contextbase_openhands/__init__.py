"""ContextBase memory integration for OpenHands (formerly OpenDevin).

Wires the ContextBase MCP server into OpenHands' ``config.toml`` and writes a
recall/retain rule into the project's ``AGENTS.md``, so the agent has
``recall``/``retain``/``reflect`` tools and uses them automatically.

CLI::

    contextbase-openhands init --api-token hsk_... --bank-id my-project
"""

__version__ = "0.1.0"
