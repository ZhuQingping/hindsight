---
sidebar_position: 34
title: "Haystack Persistent Memory with ContextBase | Integration"
description: "Add persistent long-term memory to Haystack agents with ContextBase. Provides retain/recall/reflect Tools plus a ContextBaseMemoryWrapper with optional auto-recall and auto-retain."
---

# Haystack

Persistent long-term memory for [Haystack](https://haystack.deepset.ai/) agents via ContextBase. The `contextbase-haystack` package gives you two complementary patterns:

- **`create_contextbase_tools(...)`** — Returns a list of Haystack `Tool`s (`retain_memory`, `recall_memory`, `reflect_on_memory`) the model can call directly inside a turn.
- **`ContextBaseMemoryWrapper`** — A Haystack `Toolset` that bundles the same tools and adds optional **auto-recall** (inject relevant memories into the system prompt before each turn) and **auto-retain** (store user + assistant messages after each turn).

[View Changelog →](/changelog/integrations/haystack)

## Installation

```bash
pip install contextbase-haystack
```

## Quick Start

```python
from contextbase_client import ContextBase
from contextbase_haystack import create_contextbase_tools
from haystack.components.agents import Agent
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.dataclasses import ChatMessage

client = ContextBase(base_url="http://localhost:8888")

tools = create_contextbase_tools(
    client=client,
    bank_id="user-123",
    mission="Track user preferences",
)

agent = Agent(
    chat_generator=OpenAIChatGenerator(model="gpt-4o-mini"),
    tools=tools,
    system_prompt=(
        "You are a helpful assistant with long-term memory. "
        "Use retain_memory to store important facts. "
        "Use recall_memory to search memory before answering."
    ),
)

result = agent.run(messages=[ChatMessage.from_user("Remember that I prefer dark mode")])
print(result["messages"][-1].text)
```

## Automatic Memory with ContextBaseMemoryWrapper

For automatic recall and retain without relying on the agent to call tools:

```python
from contextbase_haystack import ContextBaseMemoryWrapper

toolset = ContextBaseMemoryWrapper(
    client=client,
    bank_id="user-123",
    mission="Track user preferences",
    auto_recall=True,   # Inject memories into the system prompt before each turn
    auto_retain=True,   # Store user + assistant messages after each turn
)

agent = Agent(
    chat_generator=OpenAIChatGenerator(model="gpt-4o-mini"),
    tools=toolset,
    system_prompt="You are a helpful assistant with long-term memory.",
)

# Use toolset.run() for automatic memory behavior
result = toolset.run(agent, messages=[ChatMessage.from_user("I prefer dark mode")])
```

## Selective Tools

```python
# Only retain + recall (no reflect)
tools = create_contextbase_tools(
    client=client,
    bank_id="user-123",
    include_reflect=False,
)
```

## Configuration

Call `configure()` once to set connection defaults so you can omit `client=`/`contextbase_api_url=` on every call:

```python
from contextbase_haystack import configure

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="your-api-key",
    budget="mid",
    tags=["source:haystack"],
    context="my-app",
    mission="Track user preferences",
)

tools = create_contextbase_tools(bank_id="user-123")
```

The API URL must be configured explicitly, and the API key falls back to the `CONTEXTBASE_API_KEY` environment variable.

## Requirements

- Python 3.10+
- `haystack-ai >= 2.12.0`
- `contextbase-client >= 0.4.0`

## Prerequisites

A running ContextBase instance:

Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

**Self-hosted:**

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-api-key
hindsight-api  # starts on http://localhost:8888
```
