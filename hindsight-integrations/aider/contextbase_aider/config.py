"""Configuration for the ContextBase Aider wrapper.

Settings layer (later wins): built-in defaults -> ``~/.contextbase/aider.json`` ->
environment variables. Resolved into a typed :class:`AiderConfig`.

``contextbase-aider`` wraps the ``aider`` CLI: it recalls relevant project memory
before the session (injected via a ``--read`` file) and retains the session
transcript afterwards (read from Aider's chat-history file).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

DEFAULT_CONTEXTBASE_API_URL = ""
CONTEXTBASE_API_KEY_ENV = "CONTEXTBASE_API_KEY"

USER_CONFIG_FILE = Path.home() / ".contextbase" / "aider.json"

Budget = Literal["low", "mid", "high"]

# Default file the recalled memory is written to (Aider reads it via --read).
DEFAULT_MEMORY_FILENAME = ".aider.contextbase-memory.md"
# Aider's default chat-history file (we read it to retain the session).
DEFAULT_CHAT_HISTORY_FILE = ".aider.chat.history.md"
DEFAULT_RECALL_QUERY = "relevant context, decisions, and conventions for this project"
DEFAULT_RECALL_PREAMBLE = "Long-term project memory recalled from Hindsight (use what's relevant, ignore the rest):"


@dataclass
class AiderConfig:
    """Resolved configuration for the Aider wrapper."""

    contextbase_api_url: str = DEFAULT_CONTEXTBASE_API_URL
    contextbase_api_token: Optional[str] = None

    # Bank scoping. By default the bank is the git repo name (one bank per repo),
    # so memory follows the project; ``bank_id`` pins an explicit bank.
    bank_id: Optional[str] = None

    auto_recall: bool = True
    auto_retain: bool = True

    recall_budget: Budget = "mid"
    recall_max_tokens: int = 2048
    recall_types: list[str] = field(default_factory=lambda: ["world", "experience"])
    recall_default_query: str = DEFAULT_RECALL_QUERY
    recall_preamble: str = DEFAULT_RECALL_PREAMBLE

    aider_command: str = "aider"
    memory_filename: str = DEFAULT_MEMORY_FILENAME
    chat_history_file: str = DEFAULT_CHAT_HISTORY_FILE


_FILE_KEYS = {
    "contextbaseApiUrl": ("contextbase_api_url", str),
    "contextbaseApiToken": ("contextbase_api_token", str),
    "bankId": ("bank_id", str),
    "autoRecall": ("auto_recall", bool),
    "autoRetain": ("auto_retain", bool),
    "recallBudget": ("recall_budget", str),
    "recallMaxTokens": ("recall_max_tokens", int),
    "recallTypes": ("recall_types", list),
    "recallDefaultQuery": ("recall_default_query", str),
    "recallPreamble": ("recall_preamble", str),
    "aiderCommand": ("aider_command", str),
    "memoryFilename": ("memory_filename", str),
    "chatHistoryFile": ("chat_history_file", str),
}

_ENV_KEYS = {
    "CONTEXTBASE_API_URL": ("contextbase_api_url", str),
    "CONTEXTBASE_API_TOKEN": ("contextbase_api_token", str),
    "CONTEXTBASE_AIDER_BANK_ID": ("bank_id", str),
    "CONTEXTBASE_AIDER_AUTO_RECALL": ("auto_recall", bool),
    "CONTEXTBASE_AIDER_AUTO_RETAIN": ("auto_retain", bool),
    "CONTEXTBASE_AIDER_RECALL_BUDGET": ("recall_budget", str),
    "CONTEXTBASE_AIDER_RECALL_PREAMBLE": ("recall_preamble", str),
    "CONTEXTBASE_AIDER_COMMAND": ("aider_command", str),
}


def _cast(value: object, typ: type) -> object | None:
    try:
        if typ is bool:
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "yes")
        if typ is int:
            return int(value)
        if typ is list:
            return list(value) if isinstance(value, (list, tuple)) else [value]
        return str(value)
    except (ValueError, TypeError):
        return None


def load_config(config_file: Optional[Path] = None, env: Optional[dict] = None) -> AiderConfig:
    """Load and resolve configuration from file then environment."""
    cfg = AiderConfig()
    env = os.environ if env is None else env

    path = config_file if config_file is not None else USER_CONFIG_FILE
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        for key, (attr, typ) in _FILE_KEYS.items():
            if key in data and data[key] is not None:
                cast = _cast(data[key], typ)
                if cast is not None:
                    setattr(cfg, attr, cast)

    for key, (attr, typ) in _ENV_KEYS.items():
        if env.get(key):
            cast = _cast(env[key], typ)
            if cast is not None:
                setattr(cfg, attr, cast)

    if not cfg.contextbase_api_url:
        cfg.contextbase_api_url = DEFAULT_CONTEXTBASE_API_URL

    return cfg
