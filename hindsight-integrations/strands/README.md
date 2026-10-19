# contextbase-strands

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent memory tools for [Strands Agents SDK](https://github.com/strands-agents/sdk-python) agents via ContextBase. Give your agents long-term memory with retain, recall, and reflect — using Strands' native `@tool` pattern.

## Features

- **Native `@tool` Functions** - Tools are plain Python functions, compatible with `Agent(tools=[...])`
- **Memory Instructions** - Pre-recall memories for injection into agent system prompt
- **Three Memory Tools** - Retain (store), Recall (search), Reflect (synthesize) — include any combination
- **Simple Configuration** - Configure once globally, or pass a client directly

## Installation

```bash
pip install contextbase-strands
```

## Quick Start

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```python
from strands import Agent
from contextbase_strands import create_contextbase_tools

tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",  # or set CONTEXTBASE_API_KEY env var
)

agent = Agent(tools=tools)
agent("Remember that I prefer dark mode")
agent("What are my preferences?")
tools.close()  # Close only if contextbase-strands created the client internally
```

The agent now has three tools it can call:

- **`contextbase_retain`** — Store information to long-term memory
- **`contextbase_recall`** — Search long-term memory for relevant facts
- **`contextbase_reflect`** — Synthesize a reasoned answer from memories

### Self-hosting (local development)

If you're running ContextBase locally with `./scripts/dev/start-api.sh`, point at your local server instead:

```python
tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
)
```

See the [ContextBase installation guide](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs) for self-hosting setup.

## With Memory Instructions

Pre-recall relevant memories and inject them into the system prompt:

```python
from contextbase_strands import create_contextbase_tools, memory_instructions

tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
)

memories = memory_instructions(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
)

agent = Agent(
    tools=tools,
    system_prompt=f"You are a helpful assistant.\n\n{memories}",
)
```

## FastAPI Lifecycle (Recommended)

Prefer creating one shared ContextBase client in app lifespan and passing `client=...`.
This gives explicit ownership and clean shutdown via `await client.aclose()`.

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from hindsight_client import Hindsight
from contextbase_strands import create_contextbase_tools, memory_instructions


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Hindsight(base_url="http://localhost:8888", api_key="test-key")
    app.state.hindsight_client = client
    try:
        yield
    finally:
        await client.aclose()


app = FastAPI(lifespan=lifespan)


@app.post("/chat")
async def chat():
    client = app.state.hindsight_client
    tools = create_contextbase_tools(bank_id="user-123", client=client)
    memories = memory_instructions(bank_id="user-123", client=client)
    ...
```

If you pass `contextbase_api_url`/`api_key` directly to `create_contextbase_tools()`,
`contextbase-strands` creates the client internally. In that case call
`await tools.aclose()` (or `tools.close()`) during shutdown.

## Selecting Tools

Include only the tools you need:

```python
tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    enable_retain=True,
    enable_recall=True,
    enable_reflect=False,  # Omit reflect
)
```

## Global Configuration

Instead of passing connection details to every call, configure once:

```python
from contextbase_strands import configure, create_contextbase_tools

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="your-api-key",  # Or set CONTEXTBASE_API_KEY env var
    budget="mid",  # Recall budget: low/mid/high
    max_tokens=4096,  # Max tokens for recall results
    tags=["env:prod"],  # Tags for stored memories
    recall_tags=["scope:global"],  # Tags to filter recall
    recall_tags_match="any",  # Tag match mode: any/all/any_strict/all_strict
)

# Now create tools without passing connection details
tools = create_contextbase_tools(bank_id="user-123")
```

## Configuration Reference

### `create_contextbase_tools()`

| Parameter | Default | Description |
|---|---|---|
| `bank_id` | *required* | ContextBase memory bank ID |
| `client` | `None` | Pre-configured ContextBase client (caller owns lifecycle) |
| `contextbase_api_url` | `None` | API URL (if used, integration creates/owns client) |
| `api_key` | `None` | API key (used if no client provided) |
| `budget` | `"mid"` | Recall/reflect budget level (low/mid/high) |
| `max_tokens` | `4096` | Maximum tokens for recall results |
| `tags` | `None` | Tags applied when storing memories |
| `recall_tags` | `None` | Tags to filter when searching |
| `recall_tags_match` | `"any"` | Tag matching mode |
| `enable_retain` | `True` | Include the retain (store) tool |
| `enable_recall` | `True` | Include the recall (search) tool |
| `enable_reflect` | `True` | Include the reflect (synthesize) tool |

### `memory_instructions()`

| Parameter | Default | Description |
|---|---|---|
| `bank_id` | *required* | ContextBase memory bank ID |
| `client` | `None` | Pre-configured ContextBase client |
| `contextbase_api_url` | `None` | API URL (used if no client provided) |
| `api_key` | `None` | API key (used if no client provided) |
| `query` | `"relevant context about the user"` | Recall query for memory injection |
| `budget` | `"low"` | Recall budget level |
| `max_results` | `5` | Maximum memories to inject |
| `max_tokens` | `4096` | Maximum tokens for recall results |
| `prefix` | `"Relevant memories:\n"` | Text prepended before memory list |
| `tags` | `None` | Tags to filter recall results |
| `tags_match` | `"any"` | Tag matching mode |

### `configure()`

| Parameter | Default | Description |
|---|---|---|
| `contextbase_api_url` | Required | ContextBase API URL |
| `api_key` | `CONTEXTBASE_API_KEY` env | API key for authentication |
| `budget` | `"mid"` | Default recall budget level |
| `max_tokens` | `4096` | Default max tokens for recall |
| `tags` | `None` | Default tags for retain operations |
| `recall_tags` | `None` | Default tags to filter recall |
| `recall_tags_match` | `"any"` | Default tag matching mode |
| `verbose` | `False` | Enable verbose logging |

## Requirements

- Python >= 3.10
- strands-agents
- hindsight-client >= 0.4.0
- A running ContextBase API server

## License

MIT
