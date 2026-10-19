#!/usr/bin/env python3
"""SessionStart hook: health check.

Fires once when an OMO session begins. Verifies the ContextBase server
is reachable (cloud or self-hosted).
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.client import HindsightClient
from lib.config import debug_log, load_config


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

    api_url = config.get("contextbaseApiUrl")
    if not api_url:
        debug_log(config, "No contextbaseApiUrl configured")
        return

    api_token = config.get("contextbaseApiToken")
    if not api_token and "api.hindsight.vectorize.io" in api_url:
        print(
            "[Hindsight] Warning: Using ContextBase Cloud but no API key set. "
            "Set CONTEXTBASE_API_TOKEN or contextbaseApiToken in ~/.contextbase/omo.json",
            file=sys.stderr,
        )
        return

    try:
        client = HindsightClient(api_url, api_token)
        if client.health_check(timeout=3):
            debug_log(config, f"ContextBase server reachable at {api_url}")
        else:
            print(f"[Hindsight] Server not reachable at {api_url}", file=sys.stderr)
    except (RuntimeError, ValueError) as e:
        debug_log(config, f"Health check failed: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[Hindsight] SessionStart error: {e}", file=sys.stderr)
        sys.exit(0)
