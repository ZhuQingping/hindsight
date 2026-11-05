# contextbase-crewai

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent memory for AI agent crews via ContextBase. Give your CrewAI crews long-term memory with fact extraction, entity tracking, and temporal awareness.

## Features

- **Drop-in Storage Backend** - Implements CrewAI's `Storage` interface for `ExternalMemory`
- **Automatic Memory Flow** - CrewAI automatically stores task outputs and retrieves relevant memories
- **Per-Agent Banks** - Optionally give each agent its own isolated memory bank
- **Reflect Tool** - Agents can explicitly reason over memories with disposition-aware synthesis
- **Simple Configuration** - Configure once, use everywhere

## Installation

```bash
pip install contextbase-crewai
```

## Quick Start

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```python
from contextbase_crewai import configure, ContextBaseStorage
from crewai.memory.external.external_memory import ExternalMemory
from crewai import Agent, Crew, Task

# Step 1: Point CrewAI at ContextBase remote service
configure(
    contextbase_api_url="http://localhost:8888",
    api_key="hsk_...",  # or set CONTEXTBASE_API_KEY env var
)

# Step 2: Create crew with ContextBase-backed memory
crew = Crew(
    agents=[
        Agent(role="Researcher", goal="Find information", backstory="..."),
        Agent(role="Writer", goal="Write reports", backstory="..."),
    ],
    tasks=[
        Task(description="Research AI trends", expected_output="Report"),
    ],
    external_memory=ExternalMemory(storage=ContextBaseStorage(bank_id="my-crew")),
)

crew.kickoff()
```

That's it. CrewAI will automatically:
- **Query memories** at the start of each task
- **Store task outputs** to ContextBase after each task completes

Memories persist across crew runs, so your crew learns over time.

### Self-hosting (local development)

If you're running ContextBase locally with `./scripts/dev/start-api.sh`, point at your local server instead:

```python
configure(contextbase_api_url="http://localhost:8888")
```

See the [ContextBase installation guide](../../docs/contextbase/CUSTOMER-GUIDE.md) for self-hosting setup.

## Per-Agent Memory Banks

Give each agent its own isolated memory bank:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    per_agent_banks=True,  # Researcher -> "my-crew-researcher", Writer -> "my-crew-writer"
)
```

Or use a custom bank resolver for full control:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    bank_resolver=lambda base, agent: f"{base}-{agent.lower()}" if agent else base,
)
```

## Reflect Tool

CrewAI's storage interface only supports save/search/reset. To give agents access to ContextBase's `reflect` (disposition-aware memory synthesis), add it as a tool:

```python
from contextbase_crewai import ContextBaseReflectTool

reflect_tool = ContextBaseReflectTool(
    bank_id="my-crew",
    budget="mid",
    reflect_context="You are helping a software team track decisions.",
)

agent = Agent(
    role="Analyst",
    goal="Analyze project history",
    backstory="...",
    tools=[reflect_tool],
)
```

When the agent calls this tool, it gets a synthesized, contextual answer based on all relevant memories — not just raw facts.

## Bank Missions

Set a mission to guide how ContextBase processes and organizes memories:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    mission="Track software architecture decisions, technical debt, and team preferences.",
)
```

## Configuration

### Global Configuration

```python
from contextbase_crewai import configure

configure(
    contextbase_api_url="http://localhost:8888",  # example self-hosted endpoint
    api_key="your-api-key",  # Or set CONTEXTBASE_API_KEY env var
    budget="mid",  # Recall budget: low/mid/high
    max_tokens=4096,  # Max tokens for recall results
    tags=["env:prod"],  # Tags for stored memories
    recall_tags=["scope:global"],  # Tags to filter recall
    recall_tags_match="any",  # Tag match mode: any/all/any_strict/all_strict
    verbose=True,  # Enable logging
)
```

### Per-Storage Overrides

Constructor arguments override global configuration:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    budget="high",  # Override global budget
    max_tokens=8192,  # Override global max_tokens
    tags=["team:alpha"],  # Override global tags
)
```

## Examples

See the [CrewAI memory example](../../docs/contextbase/CUSTOMER-GUIDE.md) in the ContextBase Cookbook for a complete working demo with a Researcher + Writer crew.

## Configuration Reference

| Parameter | Default | Description |
|---|---|---|
| `contextbase_api_url` | an explicitly configured service URL | ContextBase API URL |
| `api_key` | `CONTEXTBASE_API_KEY` env | API key for authentication |
| `budget` | `"mid"` | Recall budget level (low/mid/high) |
| `max_tokens` | `4096` | Maximum tokens for recall results |
| `tags` | `None` | Tags applied when storing memories |
| `recall_tags` | `None` | Tags to filter when searching |
| `recall_tags_match` | `"any"` | Tag matching mode |
| `per_agent_banks` | `False` | Give each agent its own bank |
| `bank_resolver` | `None` | Custom (bank_id, agent) -> bank_id function |
| `mission` | `None` | Bank mission for memory organization |
| `verbose` | `False` | Enable verbose logging |
