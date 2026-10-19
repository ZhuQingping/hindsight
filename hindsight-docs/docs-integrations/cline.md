---
sidebar_position: 7
title: "Cline Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to the Cline VS Code coding agent with ContextBase using lifecycle hooks — no MCP. Hooks automatically recall context before each task and retain what happened after."
---

# Cline

:::warning Superseded by the Coding Agents plugin
**The Cline integration** is superseded by the [Coding Agents plugin](/sdks/integrations/coding-agents) — one
package covering Claude Code, Codex, opencode, Kilo, Cursor, Copilot, Grok, Antigravity, Devin and Cline and other CLI agents, with a per-repo memory bank they all share instead
of one bank per agent.

This page and the published package still work; they are no longer developed. To switch:

```bash
cd /path/to/your/repo
npx contextbase-coding-agents install cline-cli
```

Memory does not move automatically — the banks are scoped differently and this agent's history cannot be imported (it is kept in an internal database). See
[Migrating from the per-agent plugins](/sdks/integrations/coding-agents#migrating-from-the-per-agent-plugins).
:::


[View Changelog →](/changelog/integrations/cline)

Persistent memory for [Cline](https://github.com/cline/cline) using [ContextBase](https://github.com/RSIXDB/hindsight) — **without MCP**. Cline's [lifecycle hooks](https://docs.cline.bot/customization/hooks) run small scripts that automatically recall relevant context before each task and retain what happened when a task ends. Because it runs on hooks, memory is deterministic — it doesn't depend on the model deciding to call a tool.

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

Install the CLI, then run the installer from your project directory with your ContextBase URL and key:

```bash
pip install contextbase-cline

contextbase-cline install \
  --api-url http://localhost:8888 --api-token YOUR_KEY
```

Use `contextbase-cline install --global` to install for all projects, or `contextbase-cline uninstall` to remove it.

Then **enable hooks in Cline**: Settings → Features → Hooks.

:::note Platform
Cline hooks run on **macOS and Linux only** (no Windows) and require Python 3.
:::

## How It Works

| Cline hook         | What ContextBase does                                                   |
| ------------------ | --------------------------------------------------------------------- |
| `TaskStart`        | Recall context for the new task and inject it.                        |
| `UserPromptSubmit` | Recall memories for your message; record the prompt for later retain. |
| `TaskComplete`     | Retain the task's transcript and summary.                             |
| `TaskCancel`       | Retain the partial transcript of a cancelled task.                    |

Recalled memories are injected as a `<contextbase_memories>` context block. Cline doesn't hand hooks a transcript, so the integration accumulates each task's prompts locally and retains them at task end. Memories land in a single bank (`cline` by default).

## Configuration

Defaults live in the installed `settings.json`; put personal overrides in `~/.contextbase/cline.json` (stable across reinstalls), or use `CONTEXTBASE_*` environment variables. Common keys: `contextbaseApiUrl`, `contextbaseApiToken`, `bankId`, `autoRecall`, `autoRetain`, `recallBudget`, `dynamicBankId`, `debug`.

## Self-Hosting

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api  # http://localhost:8888
```

Point the installer at it: `--api-url http://localhost:8888`.

See the [integration source](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/cline) for full details.
