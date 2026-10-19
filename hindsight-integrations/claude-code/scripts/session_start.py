#!/usr/bin/env python3
"""SessionStart hook: report missing remote connection configuration without starting an engine."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import debug_log, load_config
from lib.connection import get_api_url


def main():
    config = load_config()

    if not config.get("autoRecall") and not config.get("autoRetain"):
        debug_log(config, "Both autoRecall and autoRetain disabled, skipping session start")
        return

    # Consume stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    debug_log(config, f"SessionStart hook, source: {hook_input.get('source', 'unknown')}")

    # Resolve configuration without probing localhost or spawning an engine.
    try:
        api_url = get_api_url(config.get("apiUrl"))
        debug_log(config, f"contextbase API Endpoint configured: {api_url}")
    except (RuntimeError, ValueError) as e:
        print(json.dumps({"systemMessage": f"[contextbase] {e}"}))
        return


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[contextbase] SessionStart error: {e}", file=sys.stderr)
        sys.exit(0)
