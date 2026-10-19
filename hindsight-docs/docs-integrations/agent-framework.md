---
sidebar_position: 8
title: "Microsoft Agent Framework Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to Microsoft Agent Framework agents with ContextBase via a context provider. Recalls relevant context before each run and retains the conversation after — no MCP, no tools to call."
---

# Microsoft Agent Framework

[View Changelog →](/changelog/integrations/agent-framework)

Persistent memory for [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) — the successor to Semantic Kernel — using [ContextBase](https://github.com/RSIXDB/hindsight). The integration plugs in as a **context provider**, so every agent run automatically recalls relevant memories into the agent's context and retains the conversation afterward. No MCP, and no tools the model has to remember to call.

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
pip install contextbase-agent-framework
export CONTEXTBASE_API_KEY=your-contextbase-key
```

```python
from agent_framework.openai import OpenAIChatClient
from contextbase_agent_framework import ContextBaseProvider

agent = OpenAIChatClient().as_agent(
    name="assistant",
    instructions="You are a helpful assistant.",
    context_providers=[ContextBaseProvider(bank_id="user-123")],
)

session = agent.create_session()
await agent.run("Remember that I prefer vegetarian food.", session=session)
await agent.run("Suggest a recipe.", session=session)  # recalls the preference
```

## How It Works

| Hook | Behavior |
| --- | --- |
| `before_run` | Recall memories relevant to the user's message and inject them as a `## Memories` block in the agent's instructions. |
| `after_run` | Retain the user input + agent response so future runs build on them. |

Memories live in a ContextBase **bank** — one per user, agent, or session (you choose via `bank_id`). Recall and retain are best-effort: a memory hiccup never blocks the agent.

## Configuration

`ContextBaseProvider(bank_id, ...)` accepts `contextbase_api_url`, `api_key`, `budget` (low/mid/high), `max_tokens`, `tags`, `recall_tags`, `mission`, `auto_recall`, `auto_retain`, and more. Process-wide defaults can be set with `configure(...)`.

## Self-Hosting

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api  # http://localhost:8888
```

```python
ContextBaseProvider(bank_id="user-123", contextbase_api_url="http://localhost:8888")
```

See the [integration source](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/agent-framework) for full details.
