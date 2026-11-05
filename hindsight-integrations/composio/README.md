# contextbase-composio

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent memory for [Composio](https://composio.dev) agents via ContextBase. Exposes ContextBase's
**retain**, **recall**, and **reflect** operations as Composio in-process custom tools your agent
can call directly.

The ContextBase memory bank for each call is the Composio session's `user_id`, so a single
registered tool set isolates memory per user automatically.

## Features

- **Composio Custom Tools** — registered via `composio.experimental.tool()` and bound to a session
- **Per-user memory** — the session `user_id` maps to the ContextBase `bank_id` (with a configurable fallback bank)
- **Three Memory Tools** — Retain (store), Recall (search), Reflect (synthesize) — include any combination
- **Simple Configuration** — pass a client/URL directly, or `configure()` once globally

## Installation

```bash
pip install contextbase-composio
```

## Quick Start

> **Recommended: [ContextBase remote service](http://localhost:9999)** — free tier, no self-hosting required.

```python
from composio import Composio
from contextbase_composio import register_contextbase_tools

composio = Composio()  # uses COMPOSIO_API_KEY

tools = register_contextbase_tools(
    composio,
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",  # or set CONTEXTBASE_API_KEY env var
)

session = composio.create(
    user_id="user-123",  # becomes the ContextBase bank_id
    experimental={"custom_tools": tools},
)

# Pass session.tools() to your agent/LLM as usual.
```

The session now has three tools the agent can call:

- **`CONTEXTBASE_RETAIN`** — Store information to long-term memory
- **`CONTEXTBASE_RECALL`** — Search long-term memory for relevant facts
- **`CONTEXTBASE_REFLECT`** — Synthesize a reasoned answer from memories

## Bank selection

The bank is resolved per call:

1. The session's `user_id` (recommended — one tool set, isolated per user).
2. `default_bank` (passed to `register_contextbase_tools` or `configure`) when a call has no `user_id`.

If neither is available, the tool raises an error.

```python
tools = register_contextbase_tools(
    composio,
    contextbase_api_url="http://localhost:8888",
    default_bank="shared",  # used only when a session has no user_id
)
```

## Selecting tools

```python
tools = register_contextbase_tools(
    composio,
    contextbase_api_url="http://localhost:8888",
    enable_retain=True,
    enable_recall=True,
    enable_reflect=False,  # omit reflect
)
```

## Global configuration

Instead of passing connection details every time, configure once:

```python
from contextbase_composio import configure, register_contextbase_tools

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="your-api-key",  # or set CONTEXTBASE_API_KEY env var
    default_bank="shared",  # fallback bank when no user_id
    budget="mid",  # recall/reflect budget: low/mid/high
    max_tokens=4096,  # max tokens for recall results
    tags=["env:prod"],  # tags for stored memories
    recall_tags=["scope:global"],  # tags to filter recall
    recall_tags_match="any",  # any/all/any_strict/all_strict
)

tools = register_contextbase_tools(composio)
```

## Self-hosting (local development)

If you're running ContextBase locally with `./scripts/dev/start-api.sh`, swap the URL:

```python
tools = register_contextbase_tools(
    composio,
    contextbase_api_url="http://localhost:8888",
)
```

See the [installation guide](../../docs/contextbase/CUSTOMER-GUIDE.md) for self-hosting setup.

## Configuration reference

### `register_contextbase_tools()`

| Parameter | Default | Description |
|---|---|---|
| `composio` | *required* | The `Composio` instance (provides the decorator) |
| `client` | `None` | Pre-configured ContextBase client |
| `contextbase_api_url` | `None` | API URL (used if no client provided) |
| `api_key` | `None` | API key (used if no client provided) |
| `default_bank` | `None` | Bank used when a call has no Composio `user_id` |
| `budget` | `"mid"` | Recall/reflect budget level (low/mid/high) |
| `max_tokens` | `4096` | Maximum tokens for recall results |
| `tags` | `None` | Tags applied when storing memories |
| `recall_tags` | `None` | Tags to filter when searching |
| `recall_tags_match` | `"any"` | Tag matching mode |
| `enable_retain` | `True` | Include the retain (store) tool |
| `enable_recall` | `True` | Include the recall (search) tool |
| `enable_reflect` | `True` | Include the reflect (synthesize) tool |

## Requirements

- Python >= 3.10
- composio >= 0.13.1, < 1
- contextbase-client >= 0.4.0
- A running ContextBase API server (or ContextBase remote service)

> **Note:** Composio's custom-tools API is currently experimental. This integration targets the
> Composio 0.13.x SDK (`from composio import Composio`). It intentionally excludes the in-progress
> `1.0.0` rewrite, whose API differs.
