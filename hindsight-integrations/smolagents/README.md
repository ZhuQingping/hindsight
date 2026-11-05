# contextbase-smolagents

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent memory tools for [SmolAgents](https://github.com/huggingface/smolagents) agents via ContextBase. Give your agents long-term memory with retain, recall, and reflect — using SmolAgents' native Tool pattern.

## Features

- **Native Tool Subclasses** - Each tool extends SmolAgents' `Tool` base class
- **Memory Instructions** - Pre-recall memories for injection into agent system prompt
- **Three Memory Tools** - Retain (store), Recall (search), Reflect (synthesize) — include any combination
- **Factory Function** - Create all tools in one call with shared configuration
- **Simple Configuration** - Configure once globally, or pass a client directly

## Installation

```bash
pip install contextbase-smolagents
```

## Quick Start

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```python
from smolagents import CodeAgent, HfApiModel
from contextbase_smolagents import create_contextbase_tools

tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",  # or set CONTEXTBASE_API_KEY env var
)

agent = CodeAgent(
    tools=tools,
    model=HfApiModel(),
)

agent.run("Remember that I prefer dark mode")
agent.run("What are my preferences?")
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

See the [ContextBase installation guide](../../docs/contextbase/CUSTOMER-GUIDE.md) for self-hosting setup.

## With Memory Instructions

Pre-recall relevant memories and inject them into the system prompt:

```python
from contextbase_smolagents import create_contextbase_tools, memory_instructions

tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
)

memories = memory_instructions(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
)

agent = CodeAgent(
    tools=tools,
    model=HfApiModel(),
    system_prompt=f"You are a helpful assistant.\n\n{memories}",
)
```

## Individual Tools

You can also use the tool classes directly:

```python
from contextbase_smolagents import ContextBaseRetainTool, ContextBaseRecallTool

agent = CodeAgent(
    tools=[
        ContextBaseRetainTool(
            bank_id="user-123",
            contextbase_api_url="http://localhost:8888",
        ),
        ContextBaseRecallTool(
            bank_id="user-123",
            contextbase_api_url="http://localhost:8888",
        ),
    ],
    model=HfApiModel(),
)
```

## Selecting Tools

Include only the tools you need via the factory:

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

Instead of passing connection details to every tool, configure once:

```python
from contextbase_smolagents import configure, create_contextbase_tools

configure(
    contextbase_api_url="http://localhost:8888",  # example self-hosted endpoint
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
| `client` | `None` | Pre-configured ContextBase client |
| `contextbase_api_url` | `None` | API URL (used if no client provided) |
| `api_key` | `None` | API key (used if no client provided) |
| `budget` | `None` | Uses configured budget, or `"mid"` when unconfigured; an explicit value overrides configuration |
| `max_tokens` | `None` | Uses configured token limit, or `4096` when unconfigured; an explicit value overrides configuration |
| `tags` | `None` | Tags applied when storing memories |
| `recall_tags` | `None` | Tags to filter when searching |
| `recall_tags_match` | `None` | Uses configured matching mode, or `"any"` when unconfigured; an explicit value overrides configuration |
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
| `contextbase_api_url` | an explicitly configured service URL | ContextBase API URL |
| `api_key` | `CONTEXTBASE_API_KEY` env | API key for authentication |
| `budget` | `"mid"` | Default recall budget level |
| `max_tokens` | `4096` | Default max tokens for recall |
| `tags` | `None` | Default tags for retain operations |
| `recall_tags` | `None` | Default tags to filter recall |
| `recall_tags_match` | `"any"` | Default tag matching mode |
| `verbose` | `False` | Enable verbose logging |

## Requirements

- Python >= 3.10
- smolagents
- contextbase-client >= 0.4.0
- A running ContextBase API server

## License

MIT
