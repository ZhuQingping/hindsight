# contextbase-agent-framework

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent long-term memory for [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) via [ContextBase](.).

Microsoft Agent Framework is the successor to Semantic Kernel. This integration plugs ContextBase in as a **context provider**, so every agent run automatically **recalls** relevant memories into the agent's context and **retains** the conversation afterward — no MCP, and no tools the model has to remember to call.

## Installation

```bash
pip install contextbase-agent-framework
```

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

## Usage

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
# ...later, even in a new process:
await agent.run("Suggest a recipe.", session=session)  # recalls the preference
```

Set your API key once via the `CONTEXTBASE_API_KEY` environment variable, or pass `api_key=`/`contextbase_api_url=` to `ContextBaseProvider`. For self-hosting:

```bash
pip install contextbase-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
contextbase-api  # http://localhost:8888
```

```python
ContextBaseProvider(bank_id="user-123", contextbase_api_url="http://localhost:8888")
```

## How It Works

| Hook | Behavior |
| --- | --- |
| `before_run` | Recall memories relevant to the user's message and inject them as a `## Memories` block in the agent's instructions. |
| `after_run` | Retain the user input + agent response so future runs build on them. |

Memories live in a ContextBase **bank** (one per user/agent/session — you choose). Recall and retain are best-effort: a memory hiccup never blocks the agent.

## Configuration

`ContextBaseProvider(bank_id, ...)` accepts: `client`, `contextbase_api_url`, `api_key`, `budget` (low/mid/high), `max_tokens`, `context`, `tags`, `recall_tags`, `recall_tags_match`, `mission` (creates the bank with a fact-extraction persona), `auto_recall`, `auto_retain`, `source_id`. You can also set process-wide defaults via `configure(...)`.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest tests -v          # unit tests
uv run pytest tests -v -m requires_real_llm   # e2e (needs a live ContextBase server)
```
