---
sidebar_position: 36
title: "Continue.dev Persistent Memory with ContextBase | Integration"
description: "Add long-term memory to the Continue.dev coding assistant with ContextBase. Recall project memory into chat with @contextbase, plus optional automatic recall/retain via the ContextBase MCP server."
---

# Continue

Long-term memory for the [Continue.dev](https://continue.dev) coding assistant, powered by [ContextBase](https://github.com/RSIXDB/hindsight). Recall relevant project memory directly into chat, and optionally let the agent recall and retain automatically in agent mode.

[View Changelog →](/changelog/integrations/continue)

## How It Works

Continue has no hook that runs before a message is sent, but it supports two native extension points that `contextbase-continue` uses:

- **HTTP context provider (precise recall):** type `@contextbase <query>` (or a bare `@contextbase`) in Continue chat and relevant memory is recalled and injected into the model's context **at query time**. The package ships a small adapter server that implements Continue's HTTP context-provider contract (`{query, fullInput, options, workspacePath}` → context items) on top of ContextBase recall.
- **MCP server + rules (automatic):** point Continue's agent mode at the ContextBase MCP server for `retain`/`recall`/`reflect` tools, with a rules file that instructs the agent to recall at the start of every task and retain durable facts.

Memory is scoped per **bank** — use one bank per project so context from one codebase doesn't leak into another.

## Setup

```bash
pip install contextbase-continue
```

Run the adapter, pointing it at your ContextBase instance and bank:

```bash
export CONTEXTBASE_API_KEY=hsk_...
export CONTEXTBASE_CONTINUE_BANK_ID=my-project
contextbase-continue            # serves on 127.0.0.1:8123
```

Then register it in Continue's `config.yaml`:

```yaml
context:
  - provider: http
    params:
      url: "http://127.0.0.1:8123/"
      title: contextbase
      displayTitle: ContextBase
      description: Recall long-term memory from ContextBase
```

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or point at a self-hosted server with `CONTEXTBASE_API_URL=http://localhost:8888`.

## Automatic recall (optional)

For hands-off recall and retain in agent mode, wire the ContextBase MCP server into Continue and add a "recall first" rule. See the [`examples/.continue/`](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/continue/examples/.continue) assets in the integration directory.

## Limitation

Continue has no pre-prompt hook, so memory cannot be injected fully passively on every message. The `@contextbase` provider gives precise, query-time recall on demand; the MCP + rules setup gives automatic recall in agent mode, subject to the agent following the rule.
