"""Configuration management for the ContextBase Cursor CLI integration.

Mirrors `hindsight-integrations/codex/scripts/lib/config.py` with the agent
name and a couple of defaults rebranded for the Cursor CLI audience.

Loading order (later entries win):
  1. Built-in defaults
  2. Plugin install settings.json  (~/.cursor/hooks/cursor-cli/settings.json)
  3. User config                   (~/.contextbase/cursor-cli.json)
  4. Environment variable overrides

`~/.contextbase/cursor-cli.json` is the recommended place to configure the
integration — stable across updates.
"""

import json
import os
import sys

DEFAULTS = {
    # Recall
    "autoRecall": True,
    "recallBudget": "mid",
    "recallMaxTokens": 1024,
    "recallTimeout": 10,
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
    "retainContext": "cursor-cli",
    "retainTags": ["{conversation_id}"],
    "retainMetadata": {},
    # Surface tool calls as compact [tool_use:name]/[tool_result] markers in the
    # plain-text transcript view (recall queries; retain when retainToolCalls is
    # off). Off by default — only natural-language text is kept.
    "includeTools": False,
    # Connection
    "contextbaseApiUrl": None,
    "contextbaseApiToken": None,
    "apiPort": 9077,
    "daemonIdleTimeout": 0,
    "embedVersion": "latest",
    "embedPackagePath": None,
    # Bank
    "bankId": None,
    "bankIdPrefix": "",
    "dynamicBankId": False,
    "dynamicBankGranularity": ["agent", "project"],
    "bankMission": (
        "You are a Cursor CLI coding assistant. Focus on technical decisions, "
        "code changes, debugging sessions, and project context relevant to the "
        "user's work."
    ),
    "retainMission": (
        "Extract technical decisions, code patterns, debugging solutions, user "
        "preferences, project context, and architectural choices. Ignore routine "
        "greetings and transient operational details."
    ),
    "agentName": "cursor-cli",
    # LLM (for daemon mode)
    "llmProvider": None,
    "llmModel": None,
    "llmApiKeyEnv": None,
    # Misc
    "debug": False,
}

ENV_OVERRIDES = {
    "CONTEXTBASE_API_URL": ("contextbaseApiUrl", str),
    "CONTEXTBASE_API_TOKEN": ("contextbaseApiToken", str),
    "CONTEXTBASE_BANK_ID": ("bankId", str),
    "CONTEXTBASE_AGENT_NAME": ("agentName", str),
    "CONTEXTBASE_AUTO_RECALL": ("autoRecall", bool),
    "CONTEXTBASE_AUTO_RETAIN": ("autoRetain", bool),
    "CONTEXTBASE_RETAIN_MODE": ("retainMode", str),
    "CONTEXTBASE_INCLUDE_TOOLS": ("includeTools", bool),
    "CONTEXTBASE_RECALL_BUDGET": ("recallBudget", str),
    "CONTEXTBASE_RECALL_MAX_TOKENS": ("recallMaxTokens", int),
    "CONTEXTBASE_RECALL_TIMEOUT": ("recallTimeout", int),
    "CONTEXTBASE_RECALL_MAX_QUERY_CHARS": ("recallMaxQueryChars", int),
    "CONTEXTBASE_RECALL_CONTEXT_TURNS": ("recallContextTurns", int),
    "CONTEXTBASE_API_PORT": ("apiPort", int),
    "CONTEXTBASE_DAEMON_IDLE_TIMEOUT": ("daemonIdleTimeout", int),
    "CONTEXTBASE_EMBED_VERSION": ("embedVersion", str),
    "CONTEXTBASE_EMBED_PACKAGE_PATH": ("embedPackagePath", str),
    "CONTEXTBASE_DYNAMIC_BANK_ID": ("dynamicBankId", bool),
    "CONTEXTBASE_BANK_MISSION": ("bankMission", str),
    "CONTEXTBASE_LLM_PROVIDER": ("llmProvider", str),
    "CONTEXTBASE_LLM_MODEL": ("llmModel", str),
    "CONTEXTBASE_DEBUG": ("debug", bool),
}


def _cast_env(value, typ):
    """Cast environment variable string to target type. Returns None on failure."""
    try:
        if typ is bool:
            return value.lower() in ("true", "1", "yes")
        if typ is int:
            return int(value)
        return value
    except (ValueError, AttributeError):
        return None


def _load_settings_file(path, config):
    """Merge a settings.json file into config in-place. Silently skips if missing."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            file_config = json.load(f)
        config.update({k: v for k, v in file_config.items() if v is not None})
    except (json.JSONDecodeError, OSError) as e:
        debug_log(config, f"Failed to load {path}: {e}")


def load_config():
    """Load plugin configuration from settings.json + env overrides."""
    config = dict(DEFAULTS)

    # 1. Plugin install settings.json (shipped with the integration, in the
    #    install root — the parent of the `scripts` and `lib` directories).
    install_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _load_settings_file(os.path.join(install_root, "settings.json"), config)

    # 2. User config — stable, version-independent
    user_config_path = os.path.join(os.path.expanduser("~"), ".contextbase", "cursor-cli.json")
    _load_settings_file(user_config_path, config)

    # 3. Environment variable overrides (highest priority)
    for env_name, (key, typ) in ENV_OVERRIDES.items():
        val = os.environ.get(env_name)
        if val is not None:
            cast_val = _cast_env(val, typ)
            if cast_val is not None:
                config[key] = cast_val

    return config


def debug_log(config, *args):
    """Log to stderr if debug mode is enabled."""
    if config.get("debug"):
        print("[Hindsight]", *args, file=sys.stderr)
