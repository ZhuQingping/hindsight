#!/usr/bin/env python3
"""Register agentstratum-memory hooks into ~/.claude/settings.json.

Claude Code's plugin installer does not currently merge hooks.json into
settings.json automatically. Run this script once after installing the plugin:

    python3 setup_hooks.py

Or via the /agentstratum:setup skill inside a Claude Code session.
"""

import argparse
import json
import os
import sys

SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
USER_CONFIG_PATH = os.path.expanduser("~/.agentstratum/claude-code.json")

# Default hook timeout for UserPromptSubmit (auto-recall).
# Raised from 12s to 45s — the hooks.json shipped with the plugin also
# uses this floor, but setup_hooks.py can tighten it further when the
# user has set a lower requestTimeoutSeconds (see build_hooks).
HOOK_RECALL_TIMEOUT_DEFAULT = 45
HOOK_RECALL_TIMEOUT_MIN = 30


def _read_request_timeout() -> int | None:
    """Return user-configured requestTimeoutSeconds, or None if unavailable."""
    if not os.path.isfile(USER_CONFIG_PATH):
        return None
    try:
        with open(USER_CONFIG_PATH) as f:
            cfg = json.load(f)
        value = cfg.get("requestTimeoutSeconds")
        if isinstance(value, (int, float)) and value > 0:
            return int(value)
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _recall_timeout() -> int:
    """Compute the recall hook timeout.

    When the user has set requestTimeoutSeconds, the hook timeout is that
    value plus a 15s margin so the hook process is never killed before the
    MCP request it wraps has a chance to complete (see #2854).

    Otherwise a safe default is used.
    """
    req_timeout = _read_request_timeout()
    if req_timeout is not None:
        return max(req_timeout + 15, HOOK_RECALL_TIMEOUT_MIN)
    return HOOK_RECALL_TIMEOUT_DEFAULT


def build_hooks(plugin_root: str) -> dict:
    recall_timeout = _recall_timeout()
    return {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'python3 "{plugin_root}/scripts/recall.py"',
                        "timeout": recall_timeout,
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'python3 "{plugin_root}/scripts/retain.py"',
                        "timeout": 15,
                        "async": True,
                    }
                ]
            }
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'python3 "{plugin_root}/scripts/session_start.py"',
                        "timeout": 5,
                    }
                ]
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f'python3 "{plugin_root}/scripts/session_end.py"',
                        "timeout": 10,
                    }
                ]
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Register or remove this plugin's Claude Code hooks")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--plugin-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    args = parser.parse_args()
    plugin_root = os.path.abspath(args.plugin_root)

    if not os.path.isfile(SETTINGS_PATH):
        print(f"Error: {SETTINGS_PATH} not found. Is Claude Code installed?", file=sys.stderr)
        sys.exit(1)

    with open(SETTINGS_PATH) as f:
        settings = json.load(f)

    new_hooks = build_hooks(plugin_root)
    existing_hooks = settings.setdefault("hooks", {})
    for event, groups in new_hooks.items():
        owned_commands = {hook["command"] for group in groups for hook in group["hooks"]}
        kept = []
        for group in existing_hooks.get(event, []):
            remaining = [hook for hook in group.get("hooks", []) if hook.get("command") not in owned_commands]
            if remaining:
                kept.append({**group, "hooks": remaining})
        if not args.uninstall:
            kept.extend(groups)
        if kept:
            existing_hooks[event] = kept
        else:
            existing_hooks.pop(event, None)

    with open(SETTINGS_PATH, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    action = "removed" if args.uninstall else "registered"
    print(f"agentstratum-memory hooks {action} successfully.")
    print(f"Plugin root: {plugin_root}")
    print("Restart Claude Code for changes to take effect.")


if __name__ == "__main__":
    main()
