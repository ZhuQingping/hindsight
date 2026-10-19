---
sidebar_position: 39
title: "GitHub Copilot Persistent Memory with ContextBase | Integration"
description: "Add long-term memory to GitHub Copilot in VS Code with ContextBase via MCP. One command wires up the ContextBase MCP server plus a recall/retain rule."
---

# GitHub Copilot

Long-term memory for [GitHub Copilot](https://github.com/features/copilot) in VS Code, powered by [ContextBase](https://github.com/RSIXDB/hindsight). One command connects Copilot's agent mode to the ContextBase MCP server and adds a recall/retain rule — so Copilot recalls relevant memory at the start of a task and retains durable facts as it works.

[View Changelog →](/changelog/integrations/github-copilot)

## How It Works

VS Code Copilot supports two things this integration uses:

- **MCP servers** via `.vscode/mcp.json` (agent mode), including **HTTP servers** with headers — so the ContextBase MCP endpoint connects directly:

  ```json
  {
    "servers": {
      "contextbase": {
        "type": "http",
        "url": "http://localhost:8888/mcp/my-project/",
        "headers": { "Authorization": "Bearer hsk_..." }
      }
    }
  }
  ```

- **`.github/copilot-instructions.md`**, which Copilot applies to every chat in the workspace — that's where the recall/retain rule lives.

## Setup

```bash
pip install contextbase-copilot
cd your-project
contextbase-copilot init --api-token YOUR_CONTEXTBASE_API_KEY --bank-id my-project
```

`init` merges the `servers` entry into `./.vscode/mcp.json` and writes the rule into `./.github/copilot-instructions.md`. Reload VS Code, open Copilot Chat in **agent mode**, and start the `contextbase` MCP server from the chat's tools menu.

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or a self-hosted server with `--api-url http://localhost:8888` (no token needed for an open local server). If `mcp.json` has comments, `init` prints the snippet to paste instead — or run `contextbase-copilot init --print-only` anytime.

## Commands

| Command | Description |
| --- | --- |
| `contextbase-copilot init` | Add the MCP server + recall/retain rule |
| `contextbase-copilot status` | Show whether the server + rule are configured |
| `contextbase-copilot uninstall` | Remove the server + rule |

See the [package README](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/github-copilot) for full configuration options.
