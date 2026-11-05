# ContextBase × OMO (oh-my-openagent)

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Long-term memory for [OMO](https://github.com/code-yeongyu/oh-my-openagent) agents via [ContextBase](.). Automatically recalls relevant context before each prompt and retains session learnings for future use.

## Setup

### 1. Get an API key

Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

### 2. Install the integration

From the `hindsight-integrations/omo/` directory:

```bash
# Hooks (global)
mkdir -p ~/.omo/hooks
cp hooks/hooks.json ~/.omo/hooks/contextbase-hooks.json

# Scripts + settings (global)
mkdir -p ~/.omo/plugins/contextbase/scripts
cp -r scripts/ ~/.omo/plugins/contextbase/scripts/
cp settings.json ~/.omo/plugins/contextbase/settings.json

# Rules (per-project — run from your project root)
mkdir -p /path/to/your/project/.omo/rules
cp rules/contextbase-memory.md /path/to/your/project/.omo/rules/contextbase-memory.md
```

### 3. Set your API key

```bash
export CONTEXTBASE_API_TOKEN=hsk_your_key_here
```

Or persistently in `~/.contextbase/omo.json`:

```json
{
  "contextbaseApiToken": "hsk_your_key_here"
}
```

### 4. Allow env vars in OMO config

In `~/.config/opencode/oh-my-openagent.jsonc`:

```jsonc
{
  "mcp_env_allowlist": [
    "CONTEXTBASE_API_URL",
    "CONTEXTBASE_API_TOKEN",
    "CONTEXTBASE_BANK_ID"
  ]
}
```

That's it. Start OMO and memory works automatically.

## Self-Hosted (optional)

To use a self-hosted ContextBase instance instead of cloud, override the API URL:

```bash
export CONTEXTBASE_API_URL=http://localhost:8888
```

Or in `~/.contextbase/omo.json`:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": null
}
```

No API token is required for local instances.

## How It Works

| Hook Event | When | Action |
|---|---|---|
| `SessionStart` | Session begins | Health check; warn if API key missing |
| `UserPromptSubmit` | Before each prompt | Query ContextBase for relevant memories; inject as context |
| `Stop` | Agent finishes | Extract transcript; send to ContextBase for fact extraction |
| `SubagentStop` | Sub-agent finishes | Same as Stop — captures sub-agent learnings |
| `SessionEnd` | Session terminates | Force final retain for short sessions |

All hooks degrade gracefully: if ContextBase is unreachable, OMO continues working normally without memory.

## Configuration

Settings are loaded in order (later wins):

1. `settings.json` (plugin defaults — cloud URL pre-set)
2. `~/.contextbase/omo.json` (user overrides)
3. `CONTEXTBASE_*` environment variables

### Key Settings

| Setting | Env Var | Default | Description |
|---|---|---|---|
| `contextbaseApiUrl` | `CONTEXTBASE_API_URL` | `http://localhost:8888` | API endpoint |
| `contextbaseApiToken` | `CONTEXTBASE_API_TOKEN` | — | API key (`hsk_...`), required for cloud |
| `bankId` | `CONTEXTBASE_BANK_ID` | `omo` | Memory bank name |
| `autoRecall` | `CONTEXTBASE_AUTO_RECALL` | `true` | Auto-recall before prompts |
| `autoRetain` | `CONTEXTBASE_AUTO_RETAIN` | `true` | Auto-retain after responses |
| `retainEveryNTurns` | — | `10` | Retain frequency (turns) |
| `recallBudget` | `CONTEXTBASE_RECALL_BUDGET` | `mid` | Recall depth (`low`/`mid`/`high`) |
| `dynamicBankId` | `CONTEXTBASE_DYNAMIC_BANK_ID` | `false` | Per-project bank isolation |
| `debug` | `CONTEXTBASE_DEBUG` | `false` | Enable debug logging to stderr |

### Dynamic Bank IDs

Enable per-project memory isolation:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

This creates banks like `omo::myproject`, `omo::other-repo`, etc.

### Multi-Bank Recall

Query additional banks alongside the primary one:

```json
{
  "recallAdditionalBanks": ["shared-team-knowledge"]
}
```

## Architecture

```
OMO (orchestrator)
 ├── SessionStart hook → health check
 ├── UserPromptSubmit hook → recall memories → inject as additionalContext
 ├── Stop hook → retain session transcript (async)
 ├── SubagentStop hook → retain sub-agent findings (async)
 └── SessionEnd hook → force final retain
```

## Testing

```bash
# Run unit tests
cd hindsight-integrations/omo
pip install pytest
python -m pytest tests/ -v

# Run interactive demo against a local ContextBase server
CONTEXTBASE_API_URL=http://localhost:8888 python demo.py
```
