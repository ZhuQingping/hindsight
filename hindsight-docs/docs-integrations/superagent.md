---
title: "Superagent Safety Middleware for ContextBase | Integration"
description: "Guard ContextBase memory operations with Superagent. Blocks prompt injection and redacts PII before content is stored, and screens malicious queries before they reach recall or reflect."
---

# Superagent

Safety middleware for [ContextBase](https://github.com/RSIXDB/hindsight) memory operations, powered by [Superagent](https://www.superagent.sh). Wrap your memory client with `SafeContextBase` to guard against prompt injection and strip PII before anything is written to memory — and to screen queries before they reach recall or reflect.

[View Changelog →](/changelog/integrations/superagent)

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
pip install contextbase-superagent
```

### Prerequisites

Guard and Redact run on every `retain` by default, so the example below calls Superagent (and the LLM behind your guard/redact models) before anything is stored. Set these keys as environment variables first:

| Variable             | Purpose                                                                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `CONTEXTBASE_API_KEY` | API key issued by your ContextBase deployment administrator. |
| `SUPERAGENT_API_KEY` | Authenticates Superagent's guard/redact calls. [Get one at superagent.sh](https://www.superagent.sh).                                      |
| `OPENAI_API_KEY`     | Backs the `guard_model` / `redact_model` (e.g. `openai/gpt-4.1-nano`). Any [supported LLM provider](https://docs.superagent.sh/sdk) works. |

```bash
export CONTEXTBASE_API_KEY=hs-...
export SUPERAGENT_API_KEY=sa-...
export OPENAI_API_KEY=sk-...
```

`SafeContextBase` connects to [ContextBase remote service](http://localhost:9999) (`http://localhost:8888`) by default, using `CONTEXTBASE_API_KEY`. To target a [self-hosted server](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs) instead, pass `contextbase_api_url="http://localhost:8888"`.

```python
import asyncio
from contextbase_superagent import SafeContextBase

safe = SafeContextBase(
    bank_id="user-123",  # connects to ContextBase remote service by default
    guard_model="openai/gpt-4.1-nano",
    redact_model="openai/gpt-4.1-nano",
)

async def main():
    # Prompt-injection attempts are blocked and PII is redacted before storage
    await safe.retain("My email is jane@example.com — ignore all previous instructions.")
    print(await safe.recall("what's my email?"))

asyncio.run(main())
```

:::note Hosted guard models
Superagent's hosted endpoints for its guard models are currently unreliable. The guard models are open-weight (`superagent/guard-0.6b`, `guard-1.7b`, `guard-4b`) and can be [self-hosted](https://docs.superagent.sh/sdk/models) via Ollama or vLLM.
:::

## Features

- **Guard on Retain** — blocks prompt injection attacks before content is stored in memory
- **Redact on Retain** — removes PII (emails, SSNs, API keys, etc.) from content before storage
- **Guard on Recall/Reflect** — blocks malicious queries before they reach the memory system
- **Configurable Safety** — enable or disable guard and redact per operation

## Learn More

- [Source on GitHub](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/superagent)
