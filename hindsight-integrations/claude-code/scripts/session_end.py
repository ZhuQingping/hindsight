#!/usr/bin/env python3
"""SessionEnd hook: flush the final transcript to the configured remote service."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.config import debug_log, load_config


def main():
    config = load_config()

    # Consume stdin
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    debug_log(config, f"SessionEnd hook, reason: {hook_input.get('reason', 'unknown')}")

    # Flush short sessions even when the periodic retain threshold was not met.
    if config.get("autoRetain") and hook_input.get("transcript_path"):
        try:
            from retain import run_retain

            run_retain(hook_input, force=True)
        except Exception as e:
            print(f"[contextbase] SessionEnd final retain error: {e}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"[contextbase] SessionEnd error: {e}", file=sys.stderr)
        sys.exit(0)
