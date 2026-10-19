---
sidebar_position: 7
title: "Zed Persistent Memory with ContextBase | Integration"
description: "Add long-term memory to the Zed editor's AI assistant with ContextBase via MCP. One command wires up the ContextBase MCP server plus a recall/retain rule, so memory works automatically in the Agent Panel."
---

# Zed

Long-term memory for the [Zed](https://zed.dev) editor's AI assistant, powered by [ContextBase](https://github.com/RSIXDB/hindsight). One command connects Zed's Agent Panel to the ContextBase MCP server and adds a rule telling the agent to use it — so it recalls relevant memory at the start of a task and retains durable facts as it goes. Recall happens at query time against your actual message, and from your seat it's automatic.

[View Changelog →](/changelog/integrations/zed)

## How It Works

Zed has no pre-prompt hook, but it supports two things this integration uses:

- **MCP context servers:** Zed runs MCP servers configured under `context_servers` in `settings.json` and surfaces their tools in the Agent Panel. `contextbase-zed` registers the ContextBase MCP server there, giving the agent `recall` / `retain` / `reflect` tools.
- **A global instructions file** (`~/.config/zed/AGENTS.md`) that Zed includes in every conversation. The integration adds a small rule there telling the agent to recall first and retain what it learns.

Zed connects to the ContextBase MCP endpoint natively by URL (with your API key as a Bearer header), so no bridge process runs.

## Setup

`contextbase-zed` is a zero-dependency Node CLI — Node.js is only needed to run this setup tool. Run it straight from npm with `npx`:

```bash
npx contextbase-zed init --api-token YOUR_CONTEXTBASE_API_KEY --bank-id my-memory
```

Or install it globally for a persistent command:

```bash
npm install -g contextbase-zed
contextbase-zed init --api-token YOUR_CONTEXTBASE_API_KEY --bank-id my-memory
```

`init` adds the `contextbase` MCP server to `~/.config/zed/settings.json` and the recall/retain rule to `~/.config/zed/AGENTS.md`. Restart Zed, open the Agent Panel, and the `contextbase` server should show a green dot.

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or point at a self-hosted server with `--api-url http://localhost:8888` (no token needed for an open local server). If your `settings.json` has comments (JSONC), `init` prints the entry to paste rather than rewriting the file — or run `contextbase-zed init --print-only` anytime.

## Commands

| Command | Description |
| --- | --- |
| `contextbase-zed init` | Add the MCP server + recall/retain rule |
| `contextbase-zed status` | Show whether the server + rule are configured |
| `contextbase-zed uninstall` | Remove the server + rule |

## Note

Recall and retain run through MCP tools the agent calls, guided by the always-on rule. This makes recall query-time precise (no lag), with the tradeoff that it relies on the agent following the "recall first" instruction rather than the editor enforcing it.

See the [package README](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/zed) for full configuration options.
