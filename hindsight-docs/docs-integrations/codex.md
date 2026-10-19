---
sidebar_position: 6
title: "Codex CLI Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to OpenAI Codex CLI with ContextBase. Three Python hook scripts automatically recall context before each prompt and retain conversations — no workflow changes required."
---

# Codex

:::warning Superseded by the Coding Agents plugin
**The Codex CLI integration** is superseded by the [Coding Agents plugin](/sdks/integrations/coding-agents) — one
package covering Claude Code, Codex, opencode, Kilo, Cursor, Copilot, Grok, Antigravity, Devin and Cline and other CLI agents, with a per-repo memory bank they all share instead
of one bank per agent.

This page and the published package still work; they are no longer developed. To switch:

```bash
cd /path/to/your/repo
npx contextbase-coding-agents install codex --import-conversations
```

Two things move, and nothing else does.

**Your server moves automatically.** `install` reads `~/.contextbase/codex.json` and keeps the same
`apiUrl` and token — an empty URL still means the local daemon — so you are not silently switched
to ContextBase remote service. Pass `--server` to change it.

**Your conversations are re-imported from local transcripts** by `--import-conversations`, as new
documents. They are not copied from the old bank: that bank's default was a single static bank
shared by every project, and its documents record only a session id, so working out which ones
belong to this repo means reading the local transcripts anyway.

**Nothing else carries over.** The old `recall*` and `retain*` settings, missions and bank-naming
options describe a pipeline this package replaced. Bank naming changes too — one bank per repo,
shared by every agent. See
[Migrating from the per-agent plugins](/sdks/integrations/coding-agents#migrating-from-the-per-agent-plugins).
:::


[View Changelog →](/changelog/integrations/codex)

Persistent memory for [Codex CLI](https://github.com/openai/codex) using [ContextBase](https://github.com/RSIXDB/hindsight). Three Python hook scripts automatically recall relevant context before each prompt and retain conversations after each turn — no changes to your Codex workflow required.

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
curl -fsSL https://github.com/RSIXDB/hindsight/get-codex | bash
```

The installer will guide you through choosing Cloud or local-daemon mode and configuring your connection. Once installed, start a new Codex session — memory is live.

To uninstall:

```bash
curl -fsSL https://github.com/RSIXDB/hindsight/get-codex | bash -s -- --uninstall
```

## Features

- **Auto-recall** — on every user prompt, queries ContextBase for relevant memories and injects them as `additionalContext` (invisible to the transcript, visible to Codex)
- **Auto-retain** — after each Codex response, stores the conversation transcript to ContextBase for future recall
- **Dynamic bank IDs** — supports per-project memory isolation based on the working directory
- **Session-level upsert** — uses the session ID as the document ID so re-running the same session updates rather than duplicates stored content
- **Zero dependencies** — pure Python stdlib, no pip install required

## Architecture

The plugin uses three Codex hook events:

| Hook | Event | Purpose |
|------|-------|---------|
| `session_start.py` | `SessionStart` | Warm up — verify ContextBase is reachable |
| `recall.py` | `UserPromptSubmit` | **Auto-recall** — query memories, inject as `additionalContext` |
| `retain.py` | `Stop` | **Auto-retain** — extract transcript, POST to Hindsight (async) |

On `UserPromptSubmit`, the hook reads the prompt, queries ContextBase for the most relevant memories, and outputs a `hookSpecificOutput.additionalContext` block. Codex prepends this to the conversation before sending it to the model:

```
<contextbase_memories>
Relevant memories from past conversations...
Current time - 2026-03-27 09:14

- Project uses FastAPI with asyncpg — not SQLAlchemy [world] (2026-03-26)
- Preferred testing framework: pytest with pytest-asyncio [experience] (2026-03-26)
</contextbase_memories>
```

On `Stop`, the hook reads the session transcript, strips previously injected memory tags (to prevent feedback loops), and POSTs the conversation to ContextBase asynchronously.

## Connection Modes

### 1. External API (recommended)

Connect to a running ContextBase server (cloud or self-hosted):

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "hsk_your_token"
}
```

### 2. Local Daemon

Run `hindsight-embed` locally. The `session_start.py` hook will detect it on `apiPort` (default `9077`). The daemon is not auto-started by the Codex plugin — start it separately:

```bash
uvx hindsight-embed
```

Then leave `contextbaseApiUrl` empty in your config and the plugin will connect to `http://localhost:9077`.

## Configuration

Settings are loaded from `~/.contextbase/codex.json`. Every setting can also be overridden via environment variable.

**Loading order** (later entries win):

1. Built-in defaults
2. Plugin `settings.json` (at `~/.contextbase/codex/settings.json`)
3. User config (`~/.contextbase/codex.json`)
4. Environment variables

---

### Connection

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `contextbaseApiUrl` | `CONTEXTBASE_API_URL` | `""` | URL of the ContextBase API server. Required. |
| `contextbaseApiToken` | `CONTEXTBASE_API_TOKEN` | `null` | API token for authentication. Required for ContextBase remote service. |
| `apiPort` | `CONTEXTBASE_API_PORT` | `9077` | Port for the local `hindsight-embed` daemon. |

---

### Memory Bank

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `bankId` | `CONTEXTBASE_BANK_ID` | `"codex"` | The bank to read from and write to. All sessions share this bank unless `dynamicBankId` is enabled. |
| `bankMission` | `CONTEXTBASE_BANK_MISSION` | coding assistant prompt | Describes the agent's purpose. Sent when creating or updating the bank. |
| `retainMission` | — | extraction prompt | Instructions for ContextBase's fact extraction — what to extract from coding conversations. |
| `dynamicBankId` | `CONTEXTBASE_DYNAMIC_BANK_ID` | `false` | When `true`, derives a unique bank ID from `dynamicBankGranularity` fields — useful for per-project isolation. |
| `dynamicBankGranularity` | — | `["agent", "project"]` | Which fields to combine for dynamic bank IDs. `"project"` = working directory, `"agent"` = agent name. |
| `bankIdPrefix` | — | `""` | Prefix prepended to all bank IDs. |
| `agentName` | `CONTEXTBASE_AGENT_NAME` | `"codex"` | Agent name used in dynamic bank ID derivation. |

---

### Auto-Recall

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRecall` | `CONTEXTBASE_AUTO_RECALL` | `true` | Master switch for auto-recall. |
| `recallBudget` | `CONTEXTBASE_RECALL_BUDGET` | `"mid"` | Search depth: `"low"` (fast), `"mid"` (balanced), `"high"` (thorough). |
| `recallMaxTokens` | `CONTEXTBASE_RECALL_MAX_TOKENS` | `1024` | Max tokens in the recalled memory block. |
| `recallTypes` | — | `["world", "experience"]` | Memory types to retrieve. |
| `recallContextTurns` | `CONTEXTBASE_RECALL_CONTEXT_TURNS` | `1` | Prior turns to include when building the recall query. `1` = latest prompt only. |
| `recallMaxQueryChars` | `CONTEXTBASE_RECALL_MAX_QUERY_CHARS` | `800` | Max characters in the query sent to ContextBase. |
| `recallRoles` | — | `["user", "assistant"]` | Which roles to include when building a multi-turn query. |
| `recallPromptPreamble` | — | built-in | Text placed above the recalled memories in the injected context block. |

---

### Auto-Retain

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRetain` | `CONTEXTBASE_AUTO_RETAIN` | `true` | Master switch for auto-retain. |
| `retainMode` | `CONTEXTBASE_RETAIN_MODE` | `"full-session"` | `"full-session"` sends the full transcript per session (upserted by session ID). `"chunked"` sends sliding windows every N turns. |
| `retainEveryNTurns` | — | `10` | Retain fires every N turns. `1` = every turn. Higher values reduce API calls. |
| `retainOverlapTurns` | — | `2` | Extra turns included from the previous chunk (chunked mode only). |
| `retainRoles` | — | `["user", "assistant"]` | Which roles to include in the retained transcript. |
| `retainTags` | — | `["{session_id}"]` | Tags attached to the stored document. `{session_id}` is replaced at runtime. |
| `retainMetadata` | — | `{}` | Arbitrary key-value metadata attached to the stored document. |
| `retainContext` | — | `"codex"` | Label identifying the source integration. Useful when multiple integrations write to the same bank. |

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

With this config, running Codex in `~/projects/api` and `~/projects/frontend` stores and recalls memories separately. Bank IDs are derived from the working directory path.

## Troubleshooting

**Hooks not firing**: Check that `~/.codex/config.toml` contains `codex_hooks = true` under `[features]`. Re-run the installer to fix this automatically.

**No memories recalled**: Recall returns results only after something has been retained. Either complete one Codex session first, or seed your bank manually using the [cookbook example](https://github.com/vectorize-io/hindsight-cookbook/tree/main/applications/codex-memory).

**Memory not being stored**: `retainEveryNTurns` defaults to `10` — retain only fires every 10 turns. While testing, add `"retainEveryNTurns": 1` to `~/.contextbase/codex.json`.

**Debug mode**: Add `"debug": true` to `~/.contextbase/codex.json` to see what ContextBase is doing on each turn:

```
[ContextBase] Recalling from bank 'codex', query length: 42
[ContextBase] Injecting 3 memories
[ContextBase] Retaining to bank 'codex', doc 'sess-abc123', 2 messages, 847 chars
```

**High latency on recall**: Use `"recallBudget": "low"` or reduce `recallMaxTokens` to speed up recall queries.
