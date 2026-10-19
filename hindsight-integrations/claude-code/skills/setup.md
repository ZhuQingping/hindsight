---
name: contextbase:setup
description: Register ContextBase hooks (plugin ID contextbase-memory) into Claude Code settings. Run this once after installing the plugin.
---

First configure the API Endpoint and credential as described in the plugin README. Missing endpoint configuration does not start a local engine.

Register the contextbase-memory hooks into `~/.claude/settings.json` by running the setup script:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/setup_hooks.py"
```

If `CLAUDE_PLUGIN_ROOT` is not set, find the path manually:

```bash
ls ~/.claude/plugins/cache/contextbase/contextbase-memory/
```

Then run:

```bash
python3 ~/.claude/plugins/cache/contextbase/contextbase-memory/<version>/scripts/setup_hooks.py
```

After the script completes, restart Claude Code for the hooks to take effect. You should see `[contextbase]` log lines on the next session start.
