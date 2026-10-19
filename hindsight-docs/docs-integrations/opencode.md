---
sidebar_position: 20
title: "OpenCode Persistent Memory with ContextBase | Integration"
description: "Add long-term memory to OpenCode with ContextBase. Automatically captures conversations and recalls relevant context across coding sessions."
---

# OpenCode

:::warning Superseded by the Coding Agents plugin
**The opencode plugin** is superseded by the [Coding Agents plugin](/sdks/integrations/coding-agents) — one
package covering Claude Code, Codex, opencode, Kilo, Cursor, Copilot, Grok, Antigravity, Devin and Cline and other CLI agents, with a per-repo memory bank they all share instead
of one bank per agent.

This page and the published package still work; they are no longer developed. To switch:

```bash
cd /path/to/your/repo
npx contextbase-coding-agents install opencode
```

Memory does not move automatically — the banks are scoped differently and this agent's history cannot be imported (it is kept in an internal database). See
[Migrating from the per-agent plugins](/sdks/integrations/coding-agents#migrating-from-the-per-agent-plugins).
:::


Persistent long-term memory plugin for [OpenCode](https://opencode.ai) using [ContextBase](https://github.com/RSIXDB/hindsight). Automatically captures conversations, recalls relevant context on session start, and provides retain/recall/reflect tools the agent can call directly.

[View Changelog →](/changelog/integrations/opencode)

## Quick Start

Add to your `opencode.json` (project) or `~/.config/opencode/opencode.json` (global):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["@vectorize-io/opencode-contextbase"]
}
```

OpenCode auto-installs plugins in the `"plugin"` array on startup — no `npm install` required.

Point the plugin at your ContextBase server and start OpenCode:

```bash
export CONTEXTBASE_API_URL="http://localhost:8888"
opencode
```

### Using ContextBase remote service

Get an API key at [console.example.com/connect](http://localhost:9999):

```bash
export CONTEXTBASE_API_URL="http://localhost:8888"
export CONTEXTBASE_API_TOKEN="your-api-key"
opencode
```

Or configure inline via plugin options in `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": [
    ["@vectorize-io/opencode-contextbase", {
      "contextbaseApiUrl": "http://localhost:8888",
      "contextbaseApiToken": "your-api-key"
    }]
  ]
}
```

## Features

### Custom Tools

The plugin registers three tools the agent can call explicitly:

| Tool | Description |
|---|---|
| `contextbase_retain` | Store information in long-term memory |
| `contextbase_recall` | Search long-term memory for relevant information |
| `contextbase_reflect` | Generate a synthesized answer from long-term memory |

### Auto-Retain

When the session goes idle (`session.idle` event), the plugin automatically retains the conversation transcript to ContextBase. Configurable via `retainEveryNTurns` to control frequency.

### Session Recall

When a new session starts, the plugin recalls relevant project context and injects it into the system prompt, giving the agent access to memories from prior sessions.

### Compaction Hook

When OpenCode compacts the context window, the plugin:
1. Retains the current conversation before compaction
2. Recalls relevant memories and injects them into the compaction context

This ensures memories survive context window trimming.

## Configuration

### Plugin Options

```json
{
  "plugin": [
    ["@vectorize-io/opencode-contextbase", {
      "contextbaseApiUrl": "http://localhost:8888",
      "contextbaseApiToken": "your-api-key",
      "bankId": "my-project",
      "autoRecall": true,
      "autoRetain": true,
      "recallBudget": "mid",
      "recallTags": [],
      "recallTagsMatch": "any",
      "retainTags": [],
      "retainEveryNTurns": 3,
      "debug": false
    }]
  ]
}
```

### Config File

Create `~/.contextbase/opencode.json` for persistent configuration that applies across all projects:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "your-api-key",
  "recallBudget": "mid"
}
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `CONTEXTBASE_API_URL` | ContextBase API base URL | *(required)* |
| `CONTEXTBASE_API_TOKEN` | API key for authentication | |
| `CONTEXTBASE_BANK_ID` | Static memory bank ID | `opencode` |
| `CONTEXTBASE_AGENT_NAME` | Agent name for dynamic bank IDs | `opencode` |
| `CONTEXTBASE_AUTO_RECALL` | Auto-recall on session start | `true` |
| `CONTEXTBASE_AUTO_RETAIN` | Auto-retain on session idle | `true` |
| `CONTEXTBASE_RETAIN_MODE` | `full-session` or `last-turn` | `full-session` |
| `CONTEXTBASE_RECALL_BUDGET` | Recall budget: `low`, `mid`, `high` | `mid` |
| `CONTEXTBASE_RECALL_MAX_TOKENS` | Max tokens for recall results | `1024` |
| `CONTEXTBASE_RECALL_TAGS` | Comma-separated tags to filter recall results | |
| `CONTEXTBASE_RECALL_TAGS_MATCH` | Tag match mode: `any`, `all`, `any_strict`, `all_strict` | `any` |
| `CONTEXTBASE_DYNAMIC_BANK_ID` | Enable dynamic bank ID derivation | `false` |
| `CONTEXTBASE_BANK_MISSION` | Bank mission/context for reflect | |

Configuration priority (later wins): defaults < `~/.contextbase/opencode.json` < plugin options < env vars.

### Logging & debugging

The plugin logs through OpenCode's own log stream (`service=contextbase`), visible with `opencode --print-logs` or in the OpenCode log files. Errors (failed retain/recall, unreachable API, auth problems) and the resolved API URL + bank are logged **by default** — so if memories aren't saving, the reason is visible without any opt-in.

Verbose tracing is controlled by the `debug` option, which is **config-only** (set `"debug": true` in `opencode.json` plugin options or `~/.contextbase/opencode.json`). There is intentionally no `CONTEXTBASE_DEBUG` environment variable: env vars are unreliable to set for OpenCode's plugin runtime (notably on Windows, where a persistent OpenCode server may never see them).

```json
{
  "plugin": [["@vectorize-io/opencode-contextbase", { "debug": true }]]
}
```

## Dynamic Bank IDs

For multi-project isolation, enable dynamic bank ID derivation:

```bash
export CONTEXTBASE_DYNAMIC_BANK_ID=true
```

The bank ID is composed from granularity fields (default: `agent::project`). Supported fields: `agent`, `project`, `channel`, `user`.

For multi-user scenarios (e.g., shared agent serving multiple users):

```bash
export CONTEXTBASE_CHANNEL_ID="slack-general"
export CONTEXTBASE_USER_ID="user123"
```

## How It Works

1. **Plugin loads** when OpenCode starts — creates a `HindsightClient`, derives the bank ID, and registers tools + hooks
2. **Session starts** — `session.created` event triggers, plugin marks session for recall injection
3. **System transform** — on the first LLM call, recalled memories are injected into the system prompt
4. **Agent works** — can call `contextbase_recall` and `contextbase_retain` explicitly during the session
5. **Session idles** — `session.idle` event triggers auto-retain of the conversation
6. **Compaction** — if the context window fills up, memories are preserved through the compaction
