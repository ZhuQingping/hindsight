---
title: "Claude Agent SDK Persistent Memory with ContextBase | Integration"
description: "Add persistent long-term memory to Anthropic's Claude Agent SDK with ContextBase. Drop-in MCP memory tools let agents retain, recall, and reflect, while hooks inject relevant memories automatically every turn."
---

# Claude Agent SDK

Persistent long-term memory for Anthropic's [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/) via [ContextBase](https://github.com/RSIXDB/hindsight). Expose retain/recall/reflect as MCP tools so the agent decides when to use memory, or wire up hooks to inject relevant memories automatically before every turn.

[View Changelog →](/changelog/integrations/claude-agent-sdk)

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
pip install contextbase-claude-agent-sdk
```

### Tools (explicit memory)

Give your Claude agent retain/recall/reflect tools so it can decide when to use memory:

```python
from claude_agent_sdk import query, ClaudeAgentOptions
from contextbase_claude_agent_sdk import create_contextbase_server

server = create_contextbase_server(
    bank_id="my-agent",
    contextbase_api_url="http://localhost:8888",
)

async for msg in query(
    prompt="Remember that I prefer dark mode. Then check what you know about me.",
    options=ClaudeAgentOptions(
        mcp_servers={"contextbase": server},
        allowed_tools=["mcp__contextbase__*"],
    ),
):
    print(msg)
```

## Features

- **Memory Tools** — retain, recall, and reflect exposed as MCP tools the agent can call on its own
- **Automatic Hooks** — inject relevant memories into context before each turn and retain conversation content after, with no explicit tool calls
- **Per-Agent Banks** — isolate memory per agent or user with a `bank_id`
- **Cloud or Self-Hosted** — point at ContextBase remote service or your own ContextBase deployment

## Learn More

- [Claude Agent SDK cookbook recipe](/cookbook/recipes/claude-agent-sdk)
- [Source on GitHub](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/claude-agent-sdk)
