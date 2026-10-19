---
sidebar_position: 7
title: "Cursor CLI Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to Cursor CLI with ContextBase. Python hook scripts automatically recall context before each prompt and retain conversations — no workflow changes required."
---

# Cursor CLI

:::warning Superseded by the Coding Agents plugin
**The Cursor CLI integration** is superseded by the [Coding Agents plugin](/sdks/integrations/coding-agents) — one
package covering Claude Code, Codex, opencode, Kilo, Cursor, Copilot, Grok, Antigravity, Devin and Cline and other CLI agents, with a per-repo memory bank they all share instead
of one bank per agent.

This page and the published package still work; they are no longer developed. To switch:

```bash
cd /path/to/your/repo
npx contextbase-coding-agents install cursor-cli
```

Memory does not move automatically — the banks are scoped differently and this agent's history cannot be imported (it is kept in an internal database). See
[Migrating from the per-agent plugins](/sdks/integrations/coding-agents#migrating-from-the-per-agent-plugins).
:::


[View Changelog →](/changelog/integrations/cursor-cli)

Persistent memory for [Cursor CLI](https://docs.cursor.com/en/cli/overview) using [ContextBase](https://github.com/RSIXDB/hindsight). Python hook scripts automatically recall relevant context before each prompt and retain conversations after each turn — no changes to your Cursor workflow required.

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
# Install the CLI
pip install contextbase-cursor-cli

# Install the hooks (defaults to ContextBase remote service)
contextbase-cursor-cli install --api-url http://localhost:8888 --api-token your-api-key

# Restart Cursor CLI — memory is live
```

The installer copies the hook scripts to `~/.cursor/hooks/cursor-cli/`, writes `~/.cursor/hooks.json` (merged with any existing entries), and creates `~/.contextbase/cursor-cli.json` for your personal config.

**Self-hosting alternative** — connect to a local `hindsight-embed` daemon by omitting the flags:

```bash
contextbase-cursor-cli install
```

To uninstall:

```bash
contextbase-cursor-cli uninstall
```

## Features

- **Auto-recall** — before each prompt, queries ContextBase for relevant memories and injects them as additional context (visible to the model, not the transcript)
- **Auto-retain** — after each response, and again on session end, stores the conversation to ContextBase for future recall
- **Dynamic bank IDs** — supports per-project memory isolation based on the working directory
- **Session-level upsert** — uses the session ID as the document ID so re-running the same session updates rather than duplicates stored content
- **Zero runtime dependencies** — the hook scripts are pure Python stdlib; the `pip install` only ships the one-time installer

## Architecture

The plugin uses four Cursor CLI hook events:

| Hook | Event | Purpose |
|------|-------|---------|
| `session_start.py` | `sessionStart` | Warm up — verify ContextBase is reachable |
| `recall.py` | `beforeSubmitPrompt` | **Auto-recall** — query memories, inject as additional context |
| `retain.py` | `stop` | **Auto-retain** — extract transcript, POST to Hindsight (async) |
| `session_end.py` | `sessionEnd` | **Final flush** — force a retain so the last turns aren't lost |

On `beforeSubmitPrompt`, the hook reads the prompt, queries ContextBase for the most relevant memories, and injects a context block. Cursor prepends this to the conversation before sending it to the model:

```
<contextbase_memories>
Relevant memories from past conversations...
Current time - 2026-03-27 09:14

- Project uses FastAPI with asyncpg — not SQLAlchemy [world] (2026-03-26)
- Preferred testing framework: pytest with pytest-asyncio [experience] (2026-03-26)
</contextbase_memories>
```

On `stop` (and again on `sessionEnd`), the hook reads the session transcript, strips previously injected memory tags (to prevent feedback loops), and POSTs the conversation to ContextBase asynchronously.

## Connection Modes

### 1. External API (recommended)

Connect to a running ContextBase server (cloud or self-hosted) via `~/.contextbase/cursor-cli.json`:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "hsk_your_token"
}
```

### 2. Local Daemon

Run `hindsight-embed` locally. The `session_start.py` hook detects it on `apiPort` (default `9077`). The daemon is not auto-started by the plugin — start it separately:

```bash
uvx hindsight-embed
```

Then leave `contextbaseApiUrl` empty in your config and the plugin connects to `http://localhost:9077`.

## Configuration

Default config ships in `~/.cursor/hooks/cursor-cli/settings.json`. For personal overrides that survive updates, create `~/.contextbase/cursor-cli.json`. Most settings can also be overridden via environment variable.

**Loading order** (later entries win):

1. Built-in defaults
2. Plugin `settings.json` (at `~/.cursor/hooks/cursor-cli/settings.json`)
3. User config (`~/.contextbase/cursor-cli.json`)
4. Environment variables

---

### Connection

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `contextbaseApiUrl` | `CONTEXTBASE_API_URL` | `""` | URL of the ContextBase API server. Empty = local daemon. |
| `contextbaseApiToken` | `CONTEXTBASE_API_TOKEN` | `null` | API token for authentication. Required for ContextBase remote service. |
| `apiPort` | `CONTEXTBASE_API_PORT` | `9077` | Port for the local `hindsight-embed` daemon. |

---

### Memory Bank

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `bankId` | `CONTEXTBASE_BANK_ID` | `"cursor-cli"` | The bank to read from and write to. All sessions share this bank unless `dynamicBankId` is enabled. |
| `bankMission` | `CONTEXTBASE_BANK_MISSION` | coding assistant prompt | Describes the agent's purpose. Sent when creating or updating the bank. |
| `retainMission` | — | extraction prompt | Instructions for ContextBase's fact extraction — what to extract from coding conversations. |
| `dynamicBankId` | `CONTEXTBASE_DYNAMIC_BANK_ID` | `false` | When `true`, derives a unique bank ID from `dynamicBankGranularity` fields — useful for per-project isolation. |
| `dynamicBankGranularity` | — | `["agent", "project"]` | Which fields to combine for dynamic bank IDs. `"project"` = working directory, `"agent"` = agent name. |
| `agentName` | `CONTEXTBASE_AGENT_NAME` | `"cursor-cli"` | Agent name used in dynamic bank ID derivation. |

---

### Auto-Recall

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRecall` | `CONTEXTBASE_AUTO_RECALL` | `true` | Master switch for auto-recall. |
| `recallBudget` | `CONTEXTBASE_RECALL_BUDGET` | `"mid"` | Search depth: `"low"` (fast), `"mid"` (balanced), `"high"` (thorough). |
| `recallMaxTokens` | `CONTEXTBASE_RECALL_MAX_TOKENS` | `1024` | Max tokens in the recalled memory block. |
| `recallTypes` | — | `["world", "experience"]` | Memory types to retrieve. |
| `recallContextTurns` | `CONTEXTBASE_RECALL_CONTEXT_TURNS` | `1` | Prior turns to include when building the recall query. `1` = latest prompt only. |

---

### Auto-Retain

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRetain` | `CONTEXTBASE_AUTO_RETAIN` | `true` | Master switch for auto-retain. |
| `retainMode` | `CONTEXTBASE_RETAIN_MODE` | `"full-session"` | `"full-session"` sends the full transcript per session (upserted by session ID). `"chunked"` sends sliding windows every N turns. |
| `retainEveryNTurns` | — | `10` | Retain fires every N turns. `1` = every turn. Higher values reduce API calls. |
| `retainContext` | — | `"cursor-cli"` | Label identifying the source integration. Useful when multiple integrations write to the same bank. |

---

### Debug

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `debug` | `CONTEXTBASE_DEBUG` | `false` | Enable verbose logging to stderr. All log lines are prefixed with `[ContextBase]`. |

## Per-Project Memory

To give each project its own isolated memory bank, enable dynamic bank IDs:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

With this config, running Cursor in `~/projects/api` and `~/projects/frontend` stores and recalls memories separately. Bank IDs are derived from the working directory path.

## Troubleshooting

**Hooks not firing**: Confirm `~/.cursor/hooks.json` exists and that `python3` is on your shell's `$PATH`. Re-run `contextbase-cursor-cli install` to rewrite the hook entries.

**No memories recalled**: Recall returns results only after something has been retained. Complete one Cursor session first, then start a new one.

**Memory not being stored**: `retainEveryNTurns` defaults to `10` — the `stop` hook only fires a retain every 10 turns. While testing, add `"retainEveryNTurns": 1` to `~/.contextbase/cursor-cli.json`. The `sessionEnd` hook also forces a final retain when you close the session.

**Debug mode**: Add `"debug": true` to `~/.contextbase/cursor-cli.json` to see what ContextBase is doing on each turn.
