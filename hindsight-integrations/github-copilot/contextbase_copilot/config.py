"""Configuration for the ContextBase GitHub Copilot integration.

Settings layer (later wins): built-in defaults -> ``~/.contextbase/copilot.json``
-> environment variables. Resolved into a typed :class:`CopilotConfig`.

The integration is configuration-only: it wires the ContextBase MCP server into
VS Code's ``.vscode/mcp.json`` and writes a recall/retain rule into
``.github/copilot-instructions.md`` (which Copilot applies to every chat in the
workspace). Memory operations run through the MCP server at runtime.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_CONTEXTBASE_API_URL = ""
DEFAULT_BANK_ID = "copilot"

USER_CONFIG_FILE = Path.home() / ".contextbase" / "copilot.json"


@dataclass
class CopilotConfig:
    """Resolved configuration for the Copilot MCP setup."""

    contextbase_api_url: str = DEFAULT_CONTEXTBASE_API_URL
    contextbase_api_token: Optional[str] = None
    # The memory bank the MCP server is scoped to (the last path segment of the
    # MCP endpoint URL).
    bank_id: str = DEFAULT_BANK_ID


_FILE_KEYS = {
    "contextbaseApiUrl": "contextbase_api_url",
    "contextbaseApiToken": "contextbase_api_token",
    "bankId": "bank_id",
}

_ENV_KEYS = {
    "CONTEXTBASE_API_URL": "contextbase_api_url",
    "CONTEXTBASE_API_TOKEN": "contextbase_api_token",
    "CONTEXTBASE_COPILOT_BANK_ID": "bank_id",
}


def load_config(config_file: Optional[Path] = None, env: Optional[dict] = None) -> CopilotConfig:
    """Load and resolve configuration from file then environment."""
    cfg = CopilotConfig()
    env = os.environ if env is None else env

    path = config_file if config_file is not None else USER_CONFIG_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for key, attr in _FILE_KEYS.items():
            value = data.get(key)
            if value:
                setattr(cfg, attr, str(value))

    for key, attr in _ENV_KEYS.items():
        value = env.get(key)
        if value:
            setattr(cfg, attr, str(value))

    if not cfg.contextbase_api_url:
        cfg.contextbase_api_url = DEFAULT_CONTEXTBASE_API_URL
    if not cfg.bank_id:
        cfg.bank_id = DEFAULT_BANK_ID

    return cfg
