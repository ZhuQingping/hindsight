---
name: agentstratum:setup
description: Register agentstratum-memory hooks into Claude Code settings. Run this once after installing the plugin.
---

First configure the API Endpoint and credential as described in the plugin README. Missing endpoint configuration does not start a local engine.

Register the agentstratum-memory hooks into `~/.claude/settings.json` by running the setup script:

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/setup_hooks.py"
```

If `CLAUDE_PLUGIN_ROOT` is not set, find the path manually:

```bash
ls ~/.claude/plugins/cache/agentstratum/agentstratum-memory/
```

Then run:

```bash
python3 ~/.claude/plugins/cache/agentstratum/agentstratum-memory/<version>/scripts/setup_hooks.py
```

After the script completes, restart Claude Code for the hooks to take effect. You should see `[agentstratum]` log lines on the next session start.

