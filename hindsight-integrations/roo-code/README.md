# contextbase-roo-code

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Roo Code](https://github.com/RooVetGit/Roo-Code) via [ContextBase](https://github.com/RSIXDB/hindsight).

Run the installer once and every Roo Code session automatically recalls past context before tasks and retains learnings after.

## What It Does

- **Before each task** — Roo Code recalls relevant memories from ContextBase and includes them as context
- **During a task** — agents can store important decisions and discoveries immediately via `retain`
- **After each task** — agents summarize and retain what was accomplished for future sessions

## Prerequisites

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

**Self-hosting alternative** — run ContextBase locally:

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api  # starts on http://localhost:8888
```

## Installation

```bash
pip install contextbase-roo-code
```

Then, from your project directory:

```bash
contextbase-roo-code install
```

Or with a custom API URL:

```bash
contextbase-roo-code install --api-url https://my-hindsight.example.com
```

Install globally (applies to all projects):

```bash
contextbase-roo-code install --global
```

This writes two files:
- `.roo/mcp.json` — registers the ContextBase MCP server with Roo Code
- `.roo/rules/contextbase-memory.md` — rules injected into every system prompt

## How It Works

```
New task starts
  └─ Roo Code rules instruct agent to call recall
       └─ Relevant memories injected into context

Agent working…
  └─ retain stores decisions/discoveries immediately

Task ends
  └─ Roo Code rules instruct agent to call retain with summary
       └─ Summary stored for future sessions
```

ContextBase exposes `recall` and `retain` as MCP tools via its built-in `/mcp` endpoint. The rules file in `.roo/rules/` tells Roo Code when to call them.

## Configuration

The installer writes to `.roo/mcp.json`:

```json
{
  "mcpServers": {
    "contextbase": {
      "type": "streamable-http",
      "url": "http://localhost:8888/mcp",
      "timeout": 30,
      "alwaysAllow": ["recall", "retain"]
    }
  }
}
```

To change the API URL after installation, edit `.roo/mcp.json` directly or re-run the installer:

```bash
contextbase-roo-code install --api-url https://new-url.example.com
```

## Verifying Setup

1. Start Hindsight (`hindsight-api` or ContextBase remote service)
2. Open Roo Code in your project
3. Check **Settings → MCP Servers** — `contextbase` should show as connected
4. Start a task — you should see `recall` called automatically

## Development

```bash
uv sync
uv run pytest tests/ -v
```
