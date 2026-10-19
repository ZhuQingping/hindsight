"""Configuration management for ContextBase Cursor plugin.

Loads settings from settings.json (plugin defaults) merged with environment
variable overrides. Follows the same layering as the Claude Code integration.
"""

import json
import os
import sys

# Default URL when no configuration is supplied — points at the hosted backend.
# Users who self-host override via ``contextbaseApiUrl`` or set
# ``useLocalDaemon: True`` to fall back to the auto-managed local daemon path.
DEFAULT_CONTEXTBASE_API_URL = ""

DEFAULTS = {
    # Recall
    "autoRecall": True,
    "recallBudget": "mid",
    "recallMaxTokens": 1024,
    "recallTypes": ["world", "experience"],
    "recallContextTurns": 1,
    "recallMaxQueryChars": 800,
    "recallPromptPreamble": (
        "Relevant memories from past coding sessions (prioritize recent when "
        "conflicting). Only use memories that are directly useful to continue "
        "this conversation; ignore the rest:"
    ),
    # Retain
    "autoRetain": True,
    "retainMode": "full-session",
    "retainEveryNTurns": 10,
    "retainOverlapTurns": 2,
    "retainToolCalls": False,
    "retainContext": "cursor",
    "retainTags": [],
    "retainMetadata": {},
    # Connection
    "contextbaseApiUrl": "",
    "contextbaseApiToken": None,
    "apiPort": 9077,
    "daemonIdleTimeout": 300,
    "embedVersion": "latest",
    "embedPackagePath": None,
    # If False (default), an empty ``contextbaseApiUrl`` falls back to the hosted
    # backend (``DEFAULT_CONTEXTBASE_API_URL``) — matches the cross-integration
    # cloud-default convention. Self-hosters who want the plugin to auto-start
    # a local daemon (the historical behaviour) opt in by setting True.
    "useLocalDaemon": False,
    # Workaround for Cursor's broken sessionStart additionalContext path.
    # See scripts/lib/rules_file.py for the upstream bug link.
    "useRulesFileFallback": True,
    "appendToGitignore": True,
    # Bank
    "bankId": "cursor",
    "bankIdPrefix": "",
    "dynamicBankId": False,
    "dynamicBankGranularity": ["agent", "project"],
    "bankMission": "",
    "retainMission": None,
    "agentName": "cursor",
    # LLM (for daemon mode)
    "llmProvider": None,
    "llmModel": None,
    "llmApiKeyEnv": None,
    # Misc
    "debug": False,
}

# Map env var names to config keys and their types
ENV_OVERRIDES = {
    "CONTEXTBASE_API_URL": ("contextbaseApiUrl", str),
    "CONTEXTBASE_API_TOKEN": ("contextbaseApiToken", str),
    "CONTEXTBASE_BANK_ID": ("bankId", str),
    "CONTEXTBASE_AGENT_NAME": ("agentName", str),
    "CONTEXTBASE_AUTO_RECALL": ("autoRecall", bool),
    "CONTEXTBASE_AUTO_RETAIN": ("autoRetain", bool),
    "CONTEXTBASE_RETAIN_MODE": ("retainMode", str),
    "CONTEXTBASE_RECALL_BUDGET": ("recallBudget", str),
    "CONTEXTBASE_RECALL_MAX_TOKENS": ("recallMaxTokens", int),
    "CONTEXTBASE_RECALL_MAX_QUERY_CHARS": ("recallMaxQueryChars", int),
    "CONTEXTBASE_RECALL_CONTEXT_TURNS": ("recallContextTurns", int),
    "CONTEXTBASE_API_PORT": ("apiPort", int),
    "CONTEXTBASE_DAEMON_IDLE_TIMEOUT": ("daemonIdleTimeout", int),
    "CONTEXTBASE_EMBED_VERSION": ("embedVersion", str),
    "CONTEXTBASE_EMBED_PACKAGE_PATH": ("embedPackagePath", str),
    "CONTEXTBASE_RETAIN_EVERY_N_TURNS": ("retainEveryNTurns", int),
    "CONTEXTBASE_RETAIN_CONTEXT": ("retainContext", str),
    "CONTEXTBASE_DYNAMIC_BANK_ID": ("dynamicBankId", bool),
    "CONTEXTBASE_BANK_MISSION": ("bankMission", str),
    "CONTEXTBASE_USE_LOCAL_DAEMON": ("useLocalDaemon", bool),
    "CONTEXTBASE_USE_RULES_FILE_FALLBACK": ("useRulesFileFallback", bool),
    "CONTEXTBASE_APPEND_TO_GITIGNORE": ("appendToGitignore", bool),
    "CONTEXTBASE_LLM_PROVIDER": ("llmProvider", str),
    "CONTEXTBASE_LLM_MODEL": ("llmModel", str),
    "CONTEXTBASE_DEBUG": ("debug", bool),
}


def _cast_env(value: str, typ):
    """Cast environment variable string to target type. Returns None on failure."""
    try:
        if typ is bool:
            return value.lower() in ("true", "1", "yes")
        if typ is int:
            return int(value)
        return value
    except (ValueError, AttributeError):
        return None


def _load_settings_file(path: str, config: dict) -> None:
    """Merge a settings.json file into config in-place. Silently skips if missing."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            file_config = json.load(f)
        config.update({k: v for k, v in file_config.items() if v is not None})
    except (json.JSONDecodeError, OSError) as e:
        debug_log(config, f"Failed to load {path}: {e}")


def load_config() -> dict:
    """Load plugin configuration from settings.json + env overrides.

    Loading order (later entries win):
      1. Built-in defaults
      2. Plugin default settings.json  (CURSOR_PLUGIN_ROOT/settings.json)
      3. User config                   (~/.contextbase/cursor.json)
      4. Environment variable overrides
    """
    config = dict(DEFAULTS)

    # 1. Plugin default settings.json
    plugin_root = os.environ.get("CURSOR_PLUGIN_ROOT", "")
    if not plugin_root:
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _load_settings_file(os.path.join(plugin_root, "settings.json"), config)

    # 2. User config
    user_config_path = os.path.join(os.path.expanduser("~"), ".contextbase", "cursor.json")
    _load_settings_file(user_config_path, config)

    # Apply environment variable overrides
    for env_name, (key, typ) in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if val is not None:
            cast_val = _cast_env(val, typ)
            if cast_val is not None:
                config[key] = cast_val

    return config


def debug_log(config: dict, *args):
    """Log to stderr if debug mode is enabled."""
    if config.get("debug"):
        print("[Hindsight]", *args, file=sys.stderr)


def read_hook_input() -> dict:
    """Parse the hook JSON from stdin.

    Cursor on Windows prefixes hook stdin with a UTF-8 BOM, which plain
    ``json.load`` rejects; ``utf-8-sig`` drops it when present.
    """
    return json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
