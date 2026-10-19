# contextbase-google-adk

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Google ADK](https://adk.dev/) agents via [ContextBase](https://github.com/RSIXDB/hindsight).

The package gives you two complementary patterns:

- **`ContextBaseMemoryService`** — Implements ADK's `BaseMemoryService`. Pass it to `Runner(memory_service=...)` and sessions are automatically retained on completion; agents calling `search_memory` get results back from ContextBase.
- **`create_contextbase_tools(...)`** — Returns a list of ADK `FunctionTool` instances (`contextbase_retain`, `contextbase_recall`, `contextbase_reflect`) the model can call inside a turn.

## Installation

```bash
pip install contextbase-google-adk
```

## Quick Start: Automatic Memory

```python
import asyncio
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from contextbase_google_adk import ContextBaseMemoryService

memory = ContextBaseMemoryService.from_url(
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
)

agent = LlmAgent(name="assistant", model="gemini-2.0-flash")

runner = Runner(
    app_name="my-app",
    agent=agent,
    session_service=InMemorySessionService(),
    memory_service=memory,
)
```

When a session ends, `Runner` calls `add_session_to_memory`, which retains the session's events to a ContextBase bank keyed by `(app_name, user_id)`. When the agent (or another call) invokes `search_memory(app_name, user_id, query)`, the integration runs a ContextBase recall and returns the results as ADK `MemoryEntry` objects.

## Quick Start: Explicit Tools

```python
from google.adk.agents import LlmAgent
from contextbase_google_adk import create_contextbase_tools

tools = create_contextbase_tools(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
)

agent = LlmAgent(name="assistant", model="gemini-2.0-flash", tools=tools)
```

The agent now has three tools (toggle with `include_retain` / `include_recall` / `include_reflect`):

- `contextbase_retain(content)` — store information to long-term memory
- `contextbase_recall(query)` — search memory and return matches
- `contextbase_reflect(query)` — synthesize a coherent answer from memory

## Global Configuration

For shared defaults, call `configure(...)` once at startup:

```python
from contextbase_google_adk import configure

configure(
    contextbase_api_url="http://localhost:8888",
    api_key=None,  # falls back to CONTEXTBASE_API_KEY env var
    bank_id_template="{app_name}::{user_id}",
    budget="mid",
    max_tokens=4096,
)
```

Subsequent `ContextBaseMemoryService.from_url()` and `create_contextbase_tools()` calls use the global config as a fallback.

## Bank ID Derivation

By default, each `(app_name, user_id)` pair gets its own bank: `"{app_name}::{user_id}"`. Override with `bank_id_template`:

```python
# Per-user bank shared across apps
ContextBaseMemoryService.from_url(..., bank_id_template="user::{user_id}")

# Static bank shared across all users
ContextBaseMemoryService.from_url(..., bank_id_template="my-shared-bank")
```

## Configuration Reference

| Argument | Default | Description |
|---|---|---|
| `contextbase_api_url` | `http://localhost:8888` | ContextBase API URL (Cloud by default). |
| `api_key` | `CONTEXTBASE_API_KEY` env | Bearer token for ContextBase remote service. |
| `bank_id_template` | `"{app_name}::{user_id}"` | Format string for deriving the bank id. |
| `budget` | `"mid"` | Recall budget: `low`/`mid`/`high`. |
| `max_tokens` | `4096` | Max tokens for recall results. |
| `tags` | `None` | Extra tags added to retains. `app:` and `user:` are always added. |
| `recall_tags` | `None` | Extra tags appended to recall queries. `user:` is always added. |
| `recall_tags_match` | `"any"` | Tag match mode: `any` / `all` / `any_strict` / `all_strict`. |
| `mission` | `None` | If set, the bank is created (idempotent) on first use with this fact-extraction mission. |
| `context` | `"google-adk"` | Provenance label attached to retained content. |

## Memory Scoping with Tags

Each retained session/event carries `app:<app_name>` and `user:<user_id>` tags. Recall queries automatically include `user:<user_id>` so users never see each other's memories. Pass `tags=[...]` to extend the retain set or `recall_tags=[...]` to filter recall further.

## Connection Modes

### ContextBase remote service (recommended)

```python
ContextBaseMemoryService.from_url(
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
)
```

### Self-hosted

```python
ContextBaseMemoryService.from_url(contextbase_api_url="http://localhost:8888")
```

## Error Handling

All `add_*` and `search_memory` methods are resilient: ContextBase failures are logged but never propagate to the `Runner`. The explicit tools raise `HindsightError` on failure so the agent can react.

## Requirements

- Python 3.10+
- `google-adk>=2.0`
- `hindsight-client>=0.4.0`

## License

MIT
