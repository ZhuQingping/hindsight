# ContextBase Pipecat Integration

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Pipecat](https://github.com/pipecat-ai/pipecat) voice AI pipelines via [ContextBase](https://github.com/RSIXDB/hindsight). A single `FrameProcessor` slots between your user context aggregator and LLM service — recalling relevant memories before each turn and retaining conversation content after.

## Quick Start

```bash
pip install contextbase-pipecat
```

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```python
from pipecat.pipeline.pipeline import Pipeline
from contextbase_pipecat import ContextBaseMemoryService

memory = ContextBaseMemoryService(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",  # or set CONTEXTBASE_API_KEY env var
)

pipeline = Pipeline(
    [
        transport.input(),
        stt_service,
        user_aggregator,
        memory,  # ← add between user_aggregator and LLM
        llm_service,
        assistant_aggregator,
        tts_service,
        transport.output(),
    ]
)
```

### Self-hosting (local development)

If you're running ContextBase locally with `./scripts/dev/start-api.sh`, point at your local server instead:

```python
memory = ContextBaseMemoryService(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
)
```

See the [ContextBase installation guide](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs) for self-hosting setup.

## How It Works

```
New turn starts
  └─ LLMContextFrame arrives
       ├─ Retain previous complete turn (user+assistant) — fire-and-forget
       └─ Recall relevant memories for current user query
            └─ Inject as <contextbase_memories> system message
                 └─ Forward enriched context to LLM
```

On each `LLMContextFrame`:

1. **Retain** — any new complete user+assistant turn pairs are sent to ContextBase asynchronously (non-blocking)
2. **Recall** — the latest user message is used as the search query; results are injected as a system message before the LLM sees the context
3. **Forward** — the enriched context frame is pushed downstream

Memory accumulates across calls. By the third or fourth turn, recall starts surfacing useful context that the pipeline didn't have to re-establish.

## Prerequisites

A running ContextBase instance:

**Self-hosted:**
```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-api-key
hindsight-api  # starts on http://localhost:8888
```

Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

## Configuration

```python
ContextBaseMemoryService(
    bank_id="user-123",  # Required: memory bank to use
    contextbase_api_url="...",  # ContextBase API URL
    api_key="hsk_...",  # API key (ContextBase remote service)
    recall_budget="mid",  # "low", "mid", or "high"
    recall_max_tokens=4096,  # Max tokens for recall results
    enable_recall=True,  # Inject memories before LLM
    enable_retain=True,  # Store turns after each exchange
    memory_prefix="Relevant memories from past conversations:\n",
)
```

### Global configuration

```python
from contextbase_pipecat import configure

configure(
    contextbase_api_url="http://localhost:8888",  # example self-hosted endpoint
    api_key="hsk_...",
    recall_budget="mid",
)

# Now create services without repeating connection details
memory = ContextBaseMemoryService(bank_id="user-123")
```

## Running Tests

```bash
pip install pytest pytest-asyncio
pytest tests/ -v
```
