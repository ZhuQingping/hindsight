# ContextBase for Cursor CLI

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Long-term memory for [Cursor CLI](https://cursor.com/docs/cli) — remembers your projects, preferences, and past sessions across every conversation.

## How it works

Four Cursor CLI hooks keep memory in sync automatically:

| Hook | Action |
|------|--------|
| `sessionStart` | Confirms ContextBase is reachable and pre-warms the local daemon if needed |
| `beforeSubmitPrompt` | Recalls relevant memories and injects them as `additional_context` |
| `stop` | Retains the conversation to long-term memory every configured N turns |
| `sessionEnd` | Forces a final retain so short sessions are still stored |

## Requirements

- **Cursor CLI** v0.45+ with hooks support
- **Python 3.9+** (for hook scripts; stdlib only — no pip install required)
- **ContextBase**: [ContextBase remote service](https://github.com/RSIXDB/hindsight) or local `hindsight-embed`

## Installation

Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```bash
pip install contextbase-cursor-cli
```

Then run the installer once:

```bash
# ContextBase remote service
contextbase-cursor-cli install --api-url http://localhost:8888 --api-token your-api-key

# Local daemon (hindsight-embed) — omit the flags
contextbase-cursor-cli install
```

The installer:

1. Copies the hook scripts to `~/.cursor/hooks/cursor-cli/`
2. Writes `~/.cursor/hooks.json` (merged with any existing entries) with absolute paths to the scripts
3. Seeds `~/.contextbase/cursor-cli.json` if it doesn't exist (drop your `contextbaseApiToken` here later)

Restart Cursor CLI to load the hooks. If memories are not recalled or retained, check that
`~/.cursor/hooks.json` exists and that `python3` is on `$PATH` from your shell.

### Uninstall

```bash
contextbase-cursor-cli uninstall
```

This removes the hook scripts and strips ContextBase's entries from `~/.cursor/hooks.json`. Your
personal config at `~/.contextbase/cursor-cli.json` is preserved.

## Configuration

Default config lives in `~/.cursor/hooks/cursor-cli/settings.json`. For personal overrides stable across updates, create `~/.contextbase/cursor-cli.json`:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "your-api-key",
  "bankId": "my-cursor-memory"
}
```

### Configuration options

| Key | Default | Description |
|-----|---------|-------------|
| `contextbaseApiUrl` | `""` | External API URL (empty = local daemon) |
| `contextbaseApiToken` | `null` | API token for ContextBase remote service |
| `bankId` | `"cursor-cli"` | Memory bank identifier |
| `bankMission` | (set) | Guides what facts ContextBase retains |
| `autoRecall` | `true` | Inject memories before each prompt |
| `autoRetain` | `true` | Store conversations after each turn |
| `retainMode` | `"full-session"` | `"full-session"` or `"chunked"` |
| `retainEveryNTurns` | `10` | Retain every N turns (1 = every turn) |
| `includeTools` | `false` | Surface tool calls as `[tool_use:name]`/`[tool_result]` markers in the plain-text transcript (recall queries; retain when tool calls aren't already stored as blocks) |
| `recallBudget` | `"mid"` | Recall depth: `"low"`, `"mid"`, `"high"` |
| `recallMaxTokens` | `1024` | Max tokens for injected memories |
| `recallTimeout` | `10` | Timeout in seconds for recall API calls |
| `dynamicBankId` | `false` | Separate bank per project |
| `dynamicBankGranularity` | `["agent", "project"]` | Fields for dynamic bank ID |
| `debug` | `false` | Log debug info to stderr |

### Environment variable overrides

All settings can also be set via environment variables:

```bash
export CONTEXTBASE_API_URL=http://localhost:8888
export CONTEXTBASE_API_TOKEN=your-api-key
export CONTEXTBASE_BANK_ID=my-project
export CONTEXTBASE_RECALL_TIMEOUT=30
export CONTEXTBASE_DEBUG=true
```

## How memory works

**Recall** — before each prompt, ContextBase searches your memory bank for facts relevant to what you're about to ask. Found memories are injected as `additional_context` so the agent has continuity across sessions.

**Retain** — after configured turns and again when the session ends, Cursor's conversation transcript is stored to ContextBase. The memory engine extracts facts, relationships, and experiences — so you don't need to re-explain your stack, preferences, or past decisions.

## Dynamic bank IDs

To keep separate memory per project:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

This creates banks like `cursor-cli::my-project` automatically, using either `CURSOR_PROJECT_DIR` (Cursor's env var) or the first entry of `workspace_roots` from the hook's common input fields.

To share memory across all worktrees of the same repo, use `gitProject` instead of `project`:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "gitProject"]
}
```

## Troubleshooting

**No "ContextBase is active" note on session start**: run with `"debug": true` (or `CONTEXTBASE_DEBUG=true`) and check stderr.

**Memory not appearing**: enable debug mode (`"debug": true`) and check that `CONTEXTBASE_API_URL` points to a reachable server.

**Hooks not firing**: check that `~/.cursor/hooks.json` is valid JSON and contains the four hook entries. Cursor CLI requires a session restart to pick up new hooks.

## Development

```bash
cd hindsight-integrations/cursor-cli
uv sync
uv run pytest tests/ -v
```

The tests mock the HTTP client, the stdin/stdout pipe, and the file-based state. No live ContextBase server is required.

## License

MIT
