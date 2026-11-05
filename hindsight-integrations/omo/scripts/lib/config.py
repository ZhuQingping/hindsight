"""Configuration management for ContextBase OMO plugin.

Loads settings from settings.json (plugin defaults) merged with environment
variable overrides.

Cloud-first: defaults to .
Set CONTEXTBASE_API_URL to use a self-hosted instance instead.
"""

import json
import os
import sys

DEFAULTS = {
    # Recall
    "autoRecall": True,
    "recallBudget": "mid",
    "recallMaxTokens": 1024,
    "recallTypes": ["world", "experience"],
    "recallContextTurns": 1,
    "recallMaxQueryChars": 800,
    "recallRoles": ["user", "assistant"],
    "recallPromptPreamble": (
        "Relevant memories from past conversations (prioritize recent when "
        "conflicting). Only use memories that are directly useful to continue "
        "this conversation; ignore the rest:"
    ),
    # Retain
    "autoRetain": True,
    "retainMode": "full-session",
    "retainRoles": ["user", "assistant"],
    "retainEveryNTurns": 10,
    "retainOverlapTurns": 2,
    "retainToolCalls": False,
    "retainContext": "omo",
    "retainTags": [],
    "retainMetadata": {},
    "recallAdditionalBanks": [],
    # Connection — cloud by default
    "contextbaseApiUrl": "",
    "contextbaseApiToken": None,
    "requestTimeoutSeconds": None,
    # Bank
    "bankId": None,
    "bankIdPrefix": "",
    "dynamicBankId": False,
    "dynamicBankGranularity": ["agent", "project"],
    "bankMission": "",
    "retainMission": None,
    "agentName": "omo",
    "resolveWorktrees": True,
    "directoryBankMap": {},
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
    "CONTEXTBASE_REQUEST_TIMEOUT_SECONDS": ("requestTimeoutSeconds", int),
    "CONTEXTBASE_DYNAMIC_BANK_ID": ("dynamicBankId", bool),
    "CONTEXTBASE_BANK_MISSION": ("bankMission", str),
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
      1. Built-in defaults (cloud URL pre-set)
      2. Plugin default settings.json  (PLUGIN_ROOT/settings.json)
      3. User config                   (~/.contextbase/omo.json)
      4. Environment variable overrides
    """
    config = dict(DEFAULTS)

    # 1. Plugin default settings.json
    plugin_root = os.environ.get("PLUGIN_ROOT", "")
    if not plugin_root:
        plugin_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _load_settings_file(os.path.join(plugin_root, "settings.json"), config)

    # 2. User config — stable, version-independent
    user_config_path = os.path.join(os.path.expanduser("~"), ".contextbase", "omo.json")
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
        print("[ContextBase]", *args, file=sys.stderr)
