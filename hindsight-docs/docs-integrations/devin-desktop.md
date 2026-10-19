---
sidebar_position: 7
title: "Devin Desktop Persistent Memory with ContextBase | Integration"
description: "Add long-term memory to Devin Desktop (formerly Windsurf) with ContextBase via MCP. One command wires the ContextBase MCP server into mcp_config.json plus an always-on recall/retain rule, so memory works automatically in Devin."
---

# Devin Desktop

Long-term memory for [Devin Desktop](https://devin.ai) — the editor formerly known as Windsurf (Codeium) — powered by [ContextBase](https://github.com/RSIXDB/hindsight). One command connects Devin to the ContextBase MCP server and adds a rule telling the agent to use it — so it recalls relevant memory at the start of a task and retains durable facts as it goes. Recall happens at query time against your actual message, and from your seat it's automatic.

:::note
Cognition rebranded Windsurf to Devin Desktop in June 2026. The MCP config still lives under `~/.codeium/windsurf/` — that's Devin Desktop's on-disk data directory and is unchanged by the rebrand. The workspace rule now lives under `.devin/rules/` (with `.windsurf/rules/` kept as a legacy fallback).
:::

[View Changelog →](/changelog/integrations/devin-desktop)

## How It Works

Devin Desktop supports two things this integration uses:

- **MCP servers:** Devin Desktop runs MCP servers configured under `mcpServers` in `~/.codeium/windsurf/mcp_config.json` and surfaces their tools to the agent. Remote servers connect via a `serverUrl` field with optional headers, so the ContextBase MCP endpoint connects directly — no bridge needed — giving the agent `recall` / `retain` / `reflect` tools.
- **Workspace rules** in `.devin/rules/`. A rule file with `trigger: always_on` frontmatter is included in every Devin request in the workspace. The integration writes a small rule there telling the agent to recall first and retain what it learns.

## Setup

```bash
pip install contextbase-devin-desktop
cd your-project
contextbase-devin-desktop init --api-token YOUR_CONTEXTBASE_API_KEY --bank-id my-memory
```

`init` adds the `contextbase` MCP server to `~/.codeium/windsurf/mcp_config.json` (Devin Desktop's single global MCP config) and writes the recall/retain rule to `./.devin/rules/contextbase.md`. Reload Devin Desktop (or refresh MCP servers), and the `contextbase` server's tools become available.

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or point at a self-hosted server with `--api-url http://localhost:8888` (no token needed for an open local server). If your `mcp_config.json` isn't plain JSON, `init` prints the entry to paste rather than rewriting the file — or run `contextbase-devin-desktop init --print-only` anytime.

## Commands

| Command | Description |
| --- | --- |
| `contextbase-devin-desktop init` | Add the MCP server + recall/retain rule |
| `contextbase-devin-desktop status` | Show whether the server + rule are configured |
| `contextbase-devin-desktop uninstall` | Remove the server + rule |

## Note

Recall and retain run through MCP tools the agent calls, guided by the always-on rule. This makes recall query-time precise (no lag), with the tradeoff that it relies on the agent following the "recall first" instruction rather than the editor enforcing it.

See the [package README](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/devin-desktop) for full configuration options.
