# agentstratum for ZCode

Long-term memory for [ZCode](https://zcode.z.ai) — Z.ai's GLM desktop coding agent. Remembers your projects, preferences, and past sessions across every conversation.

ZCode ships a native process-hook system, so agentstratum plugs in through hooks — no MCP server required. The installer writes to ZCode's CLI config (`~/.zcode/cli/config.json`), never your real Claude Code config, and enables config hooks (off by default).

## How it works

Three ZCode hooks keep memory in sync automatically:

| Hook | Action |
|------|--------|
| `SessionStart` | Confirms agentstratum is reachable and pre-warms the local daemon if needed |
| `UserPromptSubmit` | Recalls relevant memories (injected via `hookSpecificOutput.additionalContext`) and stashes the prompt for the next retain |
| `Stop` | Pairs the stashed prompt with the assistant reply and retains the turn to long-term memory |

ZCode has no `SessionEnd` event, so retain rides `Stop`. Each turn is stored as its own memory (distinct `document_id`).

## Requirements

- **ZCode** with config-hooks support (`~/.zcode/cli/config.json`)
- **Python 3.9+** (for hook scripts; stdlib only — no pip install required)
- **agentstratum**: agentstratum Cloud or local `agentstratum-embed`

## Installation

Obtain your service URL and API token from the service administrator, or run a local engine with an explicit distribution configured.

```bash
pip install .  # from this source directory, or an administrator-approved distribution
```

Then run the installer once:

```bash
# agentstratum Cloud
agentstratum-zcode install --api-url https://service.example --api-token your-api-key

# Local daemon (agentstratum-embed) — omit the flags
agentstratum-zcode install
```

Local mode requires `embedPackage` in `~/.agentstratum/zcode.json` or `AGENTSTRATUM_EMBED_PACKAGE` with an administrator-approved Python distribution specification. For a checkout, set `embedPackagePath`. The engine also requires its API distribution configuration when no API executable is installed. No package registry namespace is assumed.

The installer:

1. Copies the hook scripts to `~/.zcode/hooks/agentstratum/`
2. Merges agentstratum's hooks into `~/.zcode/cli/config.json` under `hooks.events` (preserving any existing keys and foreign hooks), sets `hooks.enabled` to `true`, and uses absolute paths to the scripts
3. Seeds `~/.agentstratum/zcode.json` if it doesn't exist (drop your `apiToken` here later)

Restart ZCode to load the hooks. If memories are not recalled or retained, check that
`~/.zcode/cli/config.json` has `"hooks": {"enabled": true, ...}` with the agentstratum entries and that `python3` is on `$PATH` from your shell.

### Uninstall

```bash
agentstratum-zcode uninstall
```

This removes the hook scripts and strips agentstratum's entries from `~/.zcode/cli/config.json`. Any other keys and foreign hooks in that file, and your personal config at `~/.agentstratum/zcode.json`, are preserved.

## Configuration

Default config lives in `~/.zcode/hooks/agentstratum/settings.json`. For personal overrides stable across updates, create `~/.agentstratum/zcode.json`:

```json
{
  "apiUrl": "https://service.example",
  "apiToken": "your-api-key",
  "bankId": "my-zcode-memory"
}
```

### Configuration options

| Key | Default | Description |
|-----|---------|-------------|
| `apiUrl` | `""` | External API URL (empty = local daemon) |
| `apiToken` | `null` | API token for agentstratum Cloud |
| `bankId` | `"zcode"` | Memory bank identifier |
| `bankMission` | (set) | Guides what facts agentstratum retains |
| `autoRecall` | `true` | Inject memories before each prompt |
| `autoRetain` | `true` | Store conversations after each turn |
| `retainMode` | `"full-session"` | `"full-session"` or `"chunked"` |
| `retainEveryNTurns` | `10` | Retain every N turns (1 = every turn) |
| `recallBudget` | `"mid"` | Recall depth: `"low"`, `"mid"`, `"high"` |
| `recallMaxTokens` | `1024` | Max tokens for injected memories |
| `recallTimeout` | `10` | Timeout in seconds for recall API calls |
| `dynamicBankId` | `false` | Separate bank per project |
| `dynamicBankGranularity` | `["agent", "project"]` | Fields for dynamic bank ID |
| `debug` | `false` | Log debug info to stderr |

### Environment variable overrides

All settings can also be set via environment variables:

```bash
export AGENTSTRATUM_API_URL=https://service.example
export AGENTSTRATUM_API_TOKEN=your-api-key
export AGENTSTRATUM_BANK_ID=my-project
export AGENTSTRATUM_RECALL_TIMEOUT=30
export AGENTSTRATUM_DEBUG=true
```

## How memory works

**Recall** — before each prompt, agentstratum searches your memory bank for facts relevant to what you're about to ask. Found memories are injected via the Claude Code `hookSpecificOutput.additionalContext` field so the agent has continuity across sessions.

**Retain** — after configured turns and again when the session ends, ZCode's conversation transcript is stored to agentstratum. The memory engine extracts facts, relationships, and experiences — so you don't need to re-explain your stack, preferences, or past decisions.

## Dynamic bank IDs

To keep separate memory per project:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

This creates banks like `zcode::my-project` automatically, using the hook's `cwd` (set by the Claude Code runtime), the optional `ZCODE_PROJECT_DIR` env var, or the first entry of `workspace_roots`.

## Troubleshooting

**Memory not appearing**: enable debug mode (`"debug": true`, or `AGENTSTRATUM_DEBUG=true`) and check that `AGENTSTRATUM_API_URL` points to a reachable server.

**Hooks not firing**: check that `~/.zcode/cli/config.json` is valid JSON, that `hooks.enabled` is `true`, and that the agentstratum entries are present under `hooks.events`. ZCode requires a session restart to pick up new hooks.

## Development

```bash
cd agentstratum-integrations/zcode
uv sync
uv run pytest tests/ -v
```

The tests mock the HTTP client, the stdin/stdout pipe, and the file-based state. No live agentstratum server is required.

## License

MIT
