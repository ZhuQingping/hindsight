"""Configuration for the ContextBase OpenHands integration.

Settings layer (later wins): built-in defaults -> ``~/.contextbase/openhands.json``
-> environment variables. Resolved into a typed :class:`OpenHandsConfig`.

The integration is configuration-only: it wires the ContextBase MCP server into
OpenHands' ``config.toml`` (the ``[mcp]`` section) and writes a recall/retain
rule into the project's ``AGENTS.md``. Memory operations run through the MCP
server at runtime, so there is no daemon or direct API client here.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Cross-integration cloud-default convention.
DEFAULT_CONTEXTBASE_API_URL = ""
DEFAULT_BANK_ID = "openhands"

USER_CONFIG_FILE = Path.home() / ".contextbase" / "openhands.json"


@dataclass
class OpenHandsConfig:
    """Resolved configuration for the OpenHands MCP setup."""

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
    "CONTEXTBASE_OPENHANDS_BANK_ID": "bank_id",
}


def load_config(config_file: Optional[Path] = None, env: Optional[dict] = None) -> OpenHandsConfig:
    """Load and resolve configuration from file then environment."""
    cfg = OpenHandsConfig()
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
