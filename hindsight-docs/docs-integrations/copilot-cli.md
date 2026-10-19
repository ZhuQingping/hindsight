---
sidebar_position: 7
title: "GitHub Copilot CLI Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to GitHub Copilot CLI with ContextBase. Python hook scripts automatically recall context at session start and retain conversations — no workflow changes required."
---

# GitHub Copilot CLI

:::warning Superseded by the Coding Agents plugin
**The GitHub Copilot CLI integration** is superseded by the [Coding Agents plugin](/sdks/integrations/coding-agents) — one
package covering Claude Code, Codex, opencode, Kilo, Cursor, Copilot, Grok, Antigravity, Devin and Cline and other CLI agents, with a per-repo memory bank they all share instead
of one bank per agent.

This page and the published package still work; they are no longer developed. To switch:

```bash
cd /path/to/your/repo
npx contextbase-coding-agents install copilot-cli
```

Memory does not move automatically — the banks are scoped differently and this agent's history cannot be imported (it is kept in an internal database). See
[Migrating from the per-agent plugins](/sdks/integrations/coding-agents#migrating-from-the-per-agent-plugins).
:::


Persistent memory for [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/use-hooks) using [ContextBase](https://github.com/RSIXDB/hindsight). Python hook scripts automatically recall relevant context at session start (and for every subagent Copilot CLI spawns) and retain conversations as they happen — no changes to your Copilot CLI workflow required.

[View Changelog →](/changelog/integrations/copilot-cli)

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
# Install the CLI
pip install contextbase-copilot-cli

# Install the hooks (defaults to ContextBase remote service)
contextbase-copilot-cli install --api-url http://localhost:8888 --api-token your-api-key

# Restart Copilot CLI — memory is live
```

The installer copies the hook scripts to `~/.copilot/contextbase-copilot-cli/`, writes a standalone `~/.copilot/hooks/contextbase-copilot-cli.json` (Copilot CLI loads every `*.json` file in its hooks directory, so this never needs to merge with other tools' hook files), and creates `~/.contextbase/copilot-cli.json` for your personal config.

**Self-hosting alternative** — connect to a local `hindsight-embed` daemon by omitting the flags:

```bash
contextbase-copilot-cli install
```

To uninstall:

```bash
contextbase-copilot-cli uninstall
```

### Repo-level install

For a team-shared configuration checked into version control, register the hooks at the repository level instead:

```bash
contextbase-copilot-cli install --scope repo
```

This writes `.github/hooks/contextbase-copilot-cli.json` in the current repo. Hook scripts are still installed to `~/.copilot/contextbase-copilot-cli/` (per-machine), so the token must come from the `CONTEXTBASE_API_TOKEN` environment variable rather than a committed file.

## Features

- **Auto-recall at session start** — when a Copilot CLI session starts, queries ContextBase for relevant memories and injects them as additional context. Uses the queued `initialPrompt` when one exists, or falls back to a generic project-context query derived from the working directory.
- **Auto-recall for subagents** — Copilot CLI's built-in subagents (`explore`, `task`, `research`, `code-review`, `rubber-duck`, `security-review`, and custom agents) run in their own isolated context and otherwise get none of the memory injected at session start. The `subagentStart` hook gives them baseline project memory too.
- **Auto-retain** — after each turn (subject to `retainEveryNTurns`), and again on session end, stores the conversation to ContextBase for future recall.
- **Dynamic bank IDs** — supports per-project memory isolation based on the working directory.
- **Session-level upsert** — uses the session ID as the document ID so re-running the same session updates rather than duplicates stored content.
- **Zero runtime dependencies** — the hook scripts are pure Python stdlib; the `pip install` only ships the one-time installer.

## Architecture

The plugin uses four Copilot CLI hook events:

| Hook | Event | Purpose |
|------|-------|---------|
| `session_start.py` | `sessionStart` | **Auto-recall** — query memories using the initial prompt (or a project-context fallback), inject as additional context |
| `subagent_start.py` | `subagentStart` | **Auto-recall for subagents** — query memories using a project-context fallback query (subagent payloads carry no task text), inject as additional context |
| `agent_stop.py` | `agentStop` | **Auto-retain** — read the transcript, apply the `retainEveryNTurns` cadence, POST to Hindsight (async); caches the transcript path for `sessionEnd` |
| `session_end.py` | `sessionEnd` | **Final flush** — force a retain using the transcript path cached by the last `agentStop`, since `sessionEnd`'s payload has no transcript path of its own |

On `sessionStart`, the hook queries ContextBase for the most relevant memories and injects a context block that Copilot CLI adds to the session:

```
<contextbase_memories>
Relevant memories from past conversations...
Current time - 2026-03-27 09:14

- Project uses FastAPI with asyncpg — not SQLAlchemy [world] (2026-03-26)
- Preferred testing framework: pytest with pytest-asyncio [experience] (2026-03-26)
</contextbase_memories>
```

`subagentStart` fires for every subagent Copilot CLI spawns except the built-in `general-purpose` agent (which never emits the event) and injects the same style of context block, prepended to that subagent's prompt.

On `agentStop` (and again on `sessionEnd`), the hook reads the session transcript, strips previously injected memory tags (to prevent feedback loops), and POSTs the conversation to ContextBase asynchronously.

:::note Recall is not refreshed per turn
Unlike some other integrations, Copilot CLI's `userPromptSubmitted` and `preToolUse` hooks don't support injecting additional context, so recall only runs once per session (at `sessionStart`) and once per subagent (at `subagentStart`) rather than being refreshed on every turn. This keeps the integration simple and reliable, at the cost of not picking up new memories mid-session.
:::

## Connection Modes

### 1. External API (recommended)

Connect to a running ContextBase server (cloud or self-hosted) via `~/.contextbase/copilot-cli.json`:

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

Default config ships in `~/.copilot/contextbase-copilot-cli/settings.json`. For personal overrides that survive updates, create `~/.contextbase/copilot-cli.json`. Most settings can also be overridden via environment variable.

**Loading order** (later entries win):

1. Built-in defaults
2. Plugin `settings.json` (at `~/.copilot/contextbase-copilot-cli/settings.json`)
3. User config (`~/.contextbase/copilot-cli.json`)
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
| `bankId` | `CONTEXTBASE_BANK_ID` | `"copilot-cli"` | The bank to read from and write to. All sessions share this bank unless `dynamicBankId` is enabled. |
| `bankMission` | `CONTEXTBASE_BANK_MISSION` | coding assistant prompt | Describes the agent's purpose. Sent when creating or updating the bank. |
| `retainMission` | — | extraction prompt | Instructions for ContextBase's fact extraction — what to extract from coding conversations. |
| `dynamicBankId` | `CONTEXTBASE_DYNAMIC_BANK_ID` | `false` | When `true`, derives a unique bank ID from `dynamicBankGranularity` fields — useful for per-project isolation. |
| `dynamicBankGranularity` | — | `["agent", "project"]` | Which fields to combine for dynamic bank IDs. `"project"` = working directory, `"agent"` = agent name. |
| `agentName` | `CONTEXTBASE_AGENT_NAME` | `"copilot-cli"` | Agent name used in dynamic bank ID derivation. |

---

### Auto-Recall

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRecall` | `CONTEXTBASE_AUTO_RECALL` | `true` | Master switch for auto-recall (covers both `sessionStart` and `subagentStart`). |
| `recallBudget` | `CONTEXTBASE_RECALL_BUDGET` | `"mid"` | Search depth: `"low"` (fast), `"mid"` (balanced), `"high"` (thorough). |
| `recallMaxTokens` | `CONTEXTBASE_RECALL_MAX_TOKENS` | `1024` | Max tokens in the recalled memory block. |
| `recallTypes` | — | `["world", "experience"]` | Memory types to retrieve. |
| `recallFallbackQueryTemplate` | — | project-context prompt | Query used when there's no specific prompt/task text available (interactive `sessionStart` with no queued prompt, or any `subagentStart`). |

---

### Auto-Retain

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| `autoRetain` | `CONTEXTBASE_AUTO_RETAIN` | `true` | Master switch for auto-retain. |
| `retainMode` | `CONTEXTBASE_RETAIN_MODE` | `"full-session"` | `"full-session"` sends the full transcript per session (upserted by session ID). `"chunked"` sends sliding windows every N turns. |
| `retainEveryNTurns` | — | `10` | Retain fires every N turns. `1` = every turn. Higher values reduce API calls. |
| `retainContext` | — | `"copilot-cli"` | Label identifying the source integration. Useful when multiple integrations write to the same bank. |

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

With this config, running Copilot CLI in `~/projects/api` and `~/projects/frontend` stores and recalls memories separately. Bank IDs are derived from the working directory path.

## Troubleshooting

**Hooks not firing**: check that `~/.copilot/hooks/contextbase-copilot-cli.json` (or `.github/hooks/contextbase-copilot-cli.json` for repo scope) is valid JSON. Copilot CLI loads hook configuration when it starts, so restart the CLI after installing or updating hooks.

**No memories recalled**: Recall returns results only after something has been retained. Complete one Copilot CLI session first, then start a new one.

**Memory not being stored**: `retainEveryNTurns` defaults to `10` — the `agentStop` hook only fires a retain every 10 turns. While testing, add `"retainEveryNTurns": 1` to `~/.contextbase/copilot-cli.json`. The `sessionEnd` hook also forces a final retain when the session terminates.

**Debug mode**: Add `"debug": true` to `~/.contextbase/copilot-cli.json` to see what ContextBase is doing on each turn.
