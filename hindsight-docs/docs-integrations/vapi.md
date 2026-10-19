---
sidebar_position: 21
title: "Vapi Persistent Memory with ContextBase | Integration"
description: "Add persistent long-term memory to Vapi voice AI calls via ContextBase webhooks. Auto-recalls caller context at call start and retains the transcript when the call ends."
---

# Vapi

Persistent long-term memory for [Vapi](https://vapi.ai) voice AI calls via [ContextBase](https://github.com/RSIXDB/hindsight). A single webhook handler recalls relevant memories at call start (injected as `assistantOverrides`) and retains the full transcript when the call ends.

[View Changelog →](/changelog/integrations/vapi)

## Quick Start

:::tip Configure your deployment
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
pip install contextbase-vapi
```

Wire it into any HTTP server. FastAPI example with ContextBase remote service:

```python
from fastapi import FastAPI, Request
from contextbase_vapi import ContextBaseVapiWebhook

app = FastAPI()
memory = ContextBaseVapiWebhook(
    bank_id="user-123",
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_your_token_here",
)

@app.post("/webhook")
async def vapi_webhook(request: Request):
    event = await request.json()
    response = await memory.handle(event)
    return response or {}
```

Point Vapi's **Server URL** at your webhook endpoint and memory is active.

**Self-hosting alternative:** [install ContextBase locally](/developer/installation) and use `contextbase_api_url="http://localhost:8888"` (omit `api_key`).

## How It Works

Unlike the Pipecat integration (per-turn `FrameProcessor`), Vapi doesn't expose a per-turn hook, so memory is injected **once per call** at call start:

```
Incoming call
  └─ Vapi fires "assistant-request" webhook
       └─ Recall memories (query = caller's phone number)
            └─ Return as assistantOverrides with <contextbase_memories> system message
                 └─ Vapi merges into assistant config before the call begins

Call ends
  └─ Vapi fires "end-of-call-report" webhook
       └─ Retain full transcript (fire-and-forget — webhook responds immediately)
```

Memory accumulates across calls. By the second or third call with the same caller, ContextBase surfaces relevant history automatically — previous decisions, account details, stated preferences.

## Vapi Server URL Setup

In the Vapi dashboard:

1. Go to **Settings → Server URL**
2. Point it at your webhook endpoint (e.g., `https://your-domain.com/webhook`)
3. Enable the `assistant-request` and `end-of-call-report` event types

See [Vapi's server events docs](https://docs.vapi.ai/server-url) for details.

## Outbound Calls

There is no `assistant-request` webhook for outbound calls. Use `build_assistant_overrides()` at call-creation time:

```python
overrides = await memory.build_assistant_overrides("Ben from Vectorize")
vapi.calls.create(
    assistant_id="...",
    assistant_overrides=overrides,
    customer={"number": "+15555550100"},
)
```

## Configuration

```python
ContextBaseVapiWebhook(
    bank_id="user-123",              # Required: memory bank to use
    contextbase_api_url="...",         # ContextBase API URL
    api_key="hsk_...",               # API key (ContextBase remote service)
    recall_budget="mid",             # "low", "mid", or "high"
    recall_max_tokens=4096,          # Max tokens for recall results
    enable_recall=True,              # Inject memories at call start
    enable_retain=True,              # Store transcript at call end
    memory_prefix="Relevant memories from past conversations:\n",
)
```

### Global Configuration

```python
from contextbase_vapi import configure

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",
    recall_budget="mid",
)

# Now create webhooks without repeating connection details
memory = ContextBaseVapiWebhook(bank_id="user-123")
```

## Bank Scoping

Typical patterns for the `bank_id`:

- **One bank per user** — scope by phone number (`user-+15551234567`) or your own account ID
- **Shared bank** — one bank for all callers (useful for small teams or shared memory)
- **Per-assistant** — if you have multiple Vapi assistants with different personalities or scopes

## Prerequisites

A running ContextBase instance:

**Self-hosted:**
```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-api-key
hindsight-api  # starts on http://localhost:8888
```

Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
