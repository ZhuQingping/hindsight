"""ContextBase long-term memory integration for GitHub Copilot CLI.

Installs Copilot CLI hooks (``sessionStart``, ``subagentStart``,
``agentStop``, ``sessionEnd``) that recall relevant memories at session/
subagent start and retain conversation transcripts to ContextBase as the
session progresses.

CLI::

    contextbase-copilot-cli install
    contextbase-copilot-cli install --api-url  --api-token hsk_...
    contextbase-copilot-cli uninstall
"""

__version__ = "0.1.0"
