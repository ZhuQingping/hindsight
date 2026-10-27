# contextbase-llamaindex

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

LlamaIndex integration for [ContextBase](https://github.com/RSIXDB/hindsight) — persistent long-term memory for AI agents.

Provides two complementary patterns:

- **Tools** (`ContextBaseToolSpec`) — Agent-driven memory via LlamaIndex's `BaseToolSpec`. The agent decides when to retain/recall/reflect.
- **Memory** (`ContextBaseMemory`) — Automatic memory via LlamaIndex's `BaseMemory` interface. Messages are stored on every turn and recalled as context.

## Installation

```bash
pip install contextbase-llamaindex
```

## Quick Start: Agent Tools

```python
import asyncio
from contextbase_client import ContextBase
from contextbase_llamaindex import ContextBaseToolSpec
from llama_index.llms.openai import OpenAI
from llama_index.core.agent import ReActAgent


async def main():
    client = ContextBase(base_url="http://localhost:8888")

    spec = ContextBaseToolSpec(
        client=client,
        bank_id="user-123",
        mission="Track user preferences",
    )
    tools = spec.to_tool_list()

    agent = ReActAgent(tools=tools, llm=OpenAI(model="gpt-4o"))
    response = await agent.run("Remember that I prefer dark mode")
    print(response)


asyncio.run(main())
```

## Quick Start: Automatic Memory

```python
from contextbase_client import ContextBase
from contextbase_llamaindex import ContextBaseMemory

client = ContextBase(base_url="http://localhost:8888")
memory = ContextBaseMemory.from_client(
    client=client,
    bank_id="user-123",
    mission="Track user preferences",
)

agent = ReActAgent(tools=tools, llm=llm, memory=memory)
```

## Configuration

```python
from contextbase_llamaindex import configure

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="your-api-key",
    budget="mid",
    tags=["source:llamaindex"],
    context="my-app",
    mission="Track user preferences",
)
```

## Requirements

- Python 3.10+
- `llama-index-core >= 0.11.0`
- `contextbase-client >= 0.4.0`

## Documentation

- [Integration docs](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs)
- [ContextBase API docs](https://docs.hindsight.vectorize.io)
