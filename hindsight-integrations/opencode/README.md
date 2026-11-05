# @huaweicloud/opencode-contextbase

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

ContextBase memory plugin for [OpenCode](https://opencode.ai) — give your AI coding agent persistent long-term memory across sessions.

## Features

- **Custom tools**: `contextbase_retain`, `contextbase_recall`, `contextbase_reflect` — the agent calls these explicitly
- **Auto-retain**: Captures conversation on `session.idle` and stores to ContextBase
- **Memory injection**: Recalls relevant memories when a new session starts
- **Compaction hook**: Injects memories during context compaction so they survive window trimming

## Quick Start

Configure your ContextBase service URL and API key before starting OpenCode.

### 1. Enable the plugin

Add to your `opencode.json` (project) or `~/.config/opencode/opencode.json` (global):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@huaweicloud/opencode-contextbase"]
}
```

OpenCode auto-installs plugins listed here on startup — no `npm install` required.

### 2. Configure your ContextBase connection

Use the endpoint and API key supplied by your service administrator:

```bash
export CONTEXTBASE_API_TOKEN="your-api-key"
export CONTEXTBASE_API_URL="https://memory.example.com"

# Optional: override the memory bank ID (defaults to "opencode")
export CONTEXTBASE_BANK_ID="my-project"
```

The plugin now reads and writes against your configured bank.

### Using a self-hosted ContextBase instance

Point `CONTEXTBASE_API_URL` at your server. An API key is optional only if the server allows unauthenticated access:

```bash
export CONTEXTBASE_API_URL="http://localhost:8888"
```

Or configure inline in `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    [
      "@huaweicloud/opencode-contextbase",
      {
        "contextbaseApiUrl": "http://localhost:8888"
      }
    ]
  ]
}
```

## Configuration

### Plugin Options

Pass options directly in `opencode.json`:

```json
{
  "plugin": [
    [
      "@huaweicloud/opencode-contextbase",
      {
        "contextbaseApiUrl": "http://localhost:8888",
        "bankId": "my-project",
        "autoRecall": true,
        "autoRetain": true,
        "recallBudget": "mid"
      }
    ]
  ]
}
```

### Config File

Create `~/.contextbase/opencode.json` for persistent configuration:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "your-api-key",
  "recallBudget": "mid",
  "retainEveryNTurns": 3,
  "debug": false
}
```

### Environment Variables

| Variable                      | Description                                              | Default                               |
| ----------------------------- | -------------------------------------------------------- | ------------------------------------- |
| `CONTEXTBASE_API_URL`           | ContextBase API base URL                                   | `http://localhost:8888`  |
| `CONTEXTBASE_API_TOKEN`         | API key for authentication                               | (none — required for ContextBase remote service) |
| `CONTEXTBASE_BANK_ID`           | Static memory bank ID                                    | `opencode`                            |
| `CONTEXTBASE_AGENT_NAME`        | Agent name for dynamic bank IDs                          | `opencode`                            |
| `CONTEXTBASE_AUTO_RECALL`       | Auto-recall on session start                             | `true`                                |
| `CONTEXTBASE_AUTO_RETAIN`       | Auto-retain on session idle                              | `true`                                |
| `CONTEXTBASE_RETAIN_MODE`       | `full-session` or `last-turn`                            | `full-session`                        |
| `CONTEXTBASE_RECALL_BUDGET`     | Recall budget: `low`, `mid`, `high`                      | `mid`                                 |
| `CONTEXTBASE_RECALL_MAX_TOKENS` | Max tokens for recall results                            | `1024`                                |
| `CONTEXTBASE_RECALL_TAGS`       | Comma-separated, filter recalls                          | (none)                                |
| `CONTEXTBASE_RECALL_TAGS_MATCH` | Tag match mode: `any`, `all`, `any_strict`, `all_strict` | `any`                                 |
| `CONTEXTBASE_RETAIN_TAGS`       | Comma-separated, added to every retain                   | (none)                                |
| `CONTEXTBASE_DYNAMIC_BANK_ID`   | Enable dynamic bank ID derivation                        | `false`                               |
| `CONTEXTBASE_BANK_MISSION`      | Bank mission/context                                     | (none)                                |

> **Debug logging** is a config-only option (`"debug": true` in `opencode.json`
> plugin options or `~/.contextbase/opencode.json`) — there is intentionally no
> `CONTEXTBASE_DEBUG` env var, because environment variables are unreliable to set
> for OpenCode's plugin runtime (notably on Windows). Errors and the resolved
> API URL/bank are logged regardless of this setting; `debug` only adds verbose
> tracing. All plugin logs go to OpenCode's log stream (`service=contextbase`),
> visible with `--print-logs` or in the OpenCode log files.

### Configuration Priority

Settings are loaded in this order (later wins):

1. Built-in defaults
2. `~/.contextbase/opencode.json`
3. Plugin options from `opencode.json`
4. Environment variables

## Tools

### `contextbase_retain`

Store information in long-term memory. The agent uses this to save important facts, user preferences, project context, and decisions.

### `contextbase_recall`

Search long-term memory. The agent uses this proactively before answering questions where prior context would help.

### `contextbase_reflect`

Generate a synthesized answer from long-term memory. Unlike recall (raw memories), reflect produces a coherent summary.

## Dynamic Bank IDs

For multi-project setups, enable dynamic bank ID derivation:

```bash
export CONTEXTBASE_DYNAMIC_BANK_ID=true
```

The bank ID is composed from granularity fields (default: `agent::project`). Supported fields: `agent`, `project`, `gitProject`, `channel`, `user`.

- `project` uses the working directory basename. With this field, separate git worktrees of the same repository end up with different bank IDs because their paths differ.
- `gitProject` resolves to the main worktree's basename via `git rev-parse --git-common-dir`, so all linked worktrees of the same repository share a single bank. Falls back to the working directory basename when git is unavailable or the directory is not a repo. Use this in place of `project` if you want worktrees to share memory:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "gitProject"]
}
```

**Note:** The bank ID is derived once when the plugin loads, from environment variables set before OpenCode starts. These dimensions are process-scoped — they don't change per session within a running OpenCode process. For per-user isolation, set the env vars before launching each user's OpenCode instance:

```bash
export CONTEXTBASE_CHANNEL_ID="slack-general"
export CONTEXTBASE_USER_ID="user123"
```

## Development

```bash
npm install
npm test        # Run tests
npm run build   # Build to dist/
```

## License

MIT
