---
sidebar_position: 40
title: "ZCode Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent long-term memory to ZCode (Z.ai's GLM desktop coding agent) with ContextBase. Python hooks automatically recall context before each prompt and retain conversations — no MCP, no workflow changes."
---

# ZCode

Persistent memory for [ZCode](https://zcode.z.ai) — Z.ai's GLM desktop coding agent — using [ContextBase](https://github.com/RSIXDB/hindsight). ZCode embeds the Claude Code agent runtime, so Python hook scripts automatically recall relevant context before each prompt and retain conversations after each turn. No MCP server, no changes to your ZCode workflow.

[View Changelog →](/changelog/integrations/zcode)

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
# Install the CLI
pip install contextbase-zcode

# Install the hooks (defaults to ContextBase remote service)
contextbase-zcode install --api-url http://localhost:8888 --api-token your-api-key

# Restart ZCode — memory is live
```

The installer copies the hook scripts to `~/.zcode/hooks/contextbase/`, registers them in `~/.zcode/cli/config.json` (merged with any existing hooks), and creates `~/.contextbase/zcode.json` for your personal config. It never touches your Claude Code config at `~/.claude/settings.json`.

**Self-hosting alternative** — connect to a local `hindsight-embed` daemon by omitting the flags:

```bash
contextbase-zcode install
```

To uninstall:

```bash
contextbase-zcode uninstall
```

### Alternative: install as a ZCode plugin

ZCode can install ContextBase directly from a plugin marketplace — no `pip` step. The same hook scripts ship as a hooks-only Claude Code plugin (`contextbase-zcode`) in the ContextBase marketplace:

```
# In ZCode: add the ContextBase marketplace, then install the plugin
zcode plugins add-marketplace RSIXDB/hindsight
zcode plugins install contextbase-zcode
```

When installed this way, ZCode registers the hooks automatically (no config-file edit). Provide your ContextBase credentials via environment variables (`CONTEXTBASE_API_URL`, `CONTEXTBASE_API_TOKEN`) or by creating `~/.contextbase/zcode.json`:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "hsk_your_token"
}
```

## Features

- **Auto-recall** — before each prompt, queries ContextBase for relevant memories and injects them as additional context (visible to the model, not the transcript)
- **Auto-retain** — after each response, stores the turn to ContextBase for future recall
- **No MCP required** — plain Python hook scripts calling ContextBase's REST API; nothing to run alongside ZCode
- **Cross-tool memory** — the same ContextBase bank is shared across Claude Code, Cursor, and other ContextBase integrations, so memory follows you between tools
- **Dynamic bank IDs** — supports per-project memory isolation based on the working directory
- **Zero runtime dependencies** — the hook scripts are pure Python stdlib; the `pip install` only ships the one-time installer

## Architecture

ZCode embeds the Claude Code agent runtime and reads the standard Claude Code hook schema from its own config namespace, `~/.zcode/cli/config.json` (with `hooks.enabled: true`). The plugin wires three hook events:

| Hook | Event | Purpose |
|------|-------|---------|
| `session_start.py` | `SessionStart` | Warm up — verify ContextBase is reachable |
| `recall.py` | `UserPromptSubmit` | **Auto-recall** — query memories, inject as `additionalContext` |
| `retain.py` | `Stop` | **Auto-retain** — assemble the turn, POST to ContextBase |

On `UserPromptSubmit`, the hook reads the prompt, queries ContextBase for the most relevant memories, and emits a context block that ZCode injects before sending the turn to the model:

```
<contextbase_memories>
Relevant memories from past conversations...
Current time - 2026-03-27 09:14

- Project uses FastAPI with asyncpg — not SQLAlchemy [world] (2026-03-26)
- Preferred testing framework: pytest with pytest-asyncio [experience] (2026-03-26)
</contextbase_memories>
```

On `Stop`, the hook pairs the user prompt (captured at `UserPromptSubmit`) with the agent's response and POSTs the turn to ContextBase. ZCode does not provide a `SessionEnd` hook event, so retention rides `Stop` — every turn is stored as it completes.

## Connection Modes

### 1. External API (recommended)

Connect to a running ContextBase server (cloud or self-hosted) via `~/.contextbase/zcode.json`:

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

Default config ships in `~/.zcode/hooks/contextbase/settings.json`. For personal overrides that survive updates, create `~/.contextbase/zcode.json`. Most settings can also be overridden via environment variable.

**Loading order** (later entries win):

1. Built-in defaults
2. Plugin `settings.json` (at `~/.zcode/hooks/contextbase/settings.json`)
3. User config (`~/.contextbase/zcode.json`)
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
| `bankId` | `CONTEXTBASE_BANK_ID` | `"zcode"` | The bank to read from and write to. All sessions share this bank unless `dynamicBankId` is enabled. |
| `bankMission` | `CONTEXTBASE_BANK_MISSION` | coding assistant prompt | Describes the agent's purpose. Sent when creating or updating the bank. |
| `dynamicBankId` | `CONTEXTBASE_DYNAMIC_BANK_ID` | `false` | When `true`, derives a unique bank ID from `dynamicBankGranularity` fields — useful for per-project isolation. |
| `agentName` | `CONTEXTBASE_AGENT_NAME` | `"zcode"` | Agent name used in dynamic bank ID derivation. |

---

### Auto-Recall

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRecall` | `CONTEXTBASE_AUTO_RECALL` | `true` | Master switch for auto-recall. |
| `recallBudget` | `CONTEXTBASE_RECALL_BUDGET` | `"mid"` | Search depth: `"low"` (fast), `"mid"` (balanced), `"high"` (thorough). |
| `recallMaxTokens` | `CONTEXTBASE_RECALL_MAX_TOKENS` | `1024` | Token budget for the injected memory block. |

---

### Auto-Retain

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRetain` | `CONTEXTBASE_AUTO_RETAIN` | `true` | Master switch for auto-retain. |
| `retainEveryNTurns` | `CONTEXTBASE_RETAIN_EVERY_N_TURNS` | `1` | Retain every N turns. Default `1` stores every turn on `Stop`. |

## Relationship to ZCode's built-in memory

ZCode ships its own local, per-project memory (`~/.zcode/cli/memories/`). ContextBase is complementary: it stores memory in a **cloud (or self-hosted) bank that is shared across tools** — the same bank powers Claude Code, Cursor, and other ContextBase integrations — so your context follows you between agents and machines rather than staying local to one ZCode project.
