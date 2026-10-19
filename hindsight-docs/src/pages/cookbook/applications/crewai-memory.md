---
sidebar_position: 6
---

# CrewAI + ContextBase Memory


:::info Complete Application
This is a complete, runnable application demonstrating ContextBase integration.
[**View source on GitHub →**](https://github.com/vectorize-io/hindsight-cookbook/tree/main/applications/crewai-memory)
:::


Give your CrewAI crews persistent long-term memory. Run a crew multiple times and watch it build on what it learned in previous runs.

## What This Demonstrates

- **Drop-in memory backend** for CrewAI via `contextbase-crewai`
- **Persistent memory across runs** - crews remember previous research
- **Reflect tool** - agents explicitly reason over past memories
- **Bank missions** - guide how ContextBase organizes memories

## Architecture

```
Run 1: "Research Rust benefits"
    │
    ├─ Researcher agent ──► ContextBase reflect (no prior memories)
    │                        ──► produces research findings
    ├─ Writer agent ────────► summarizes findings
    │
    └─ CrewAI auto-stores task outputs to ContextBase
                    │
Run 2: "Compare Rust with Go"
    │
    ├─ Researcher agent ──► ContextBase reflect (recalls Rust research!)
    │                        ──► builds on prior knowledge
    ├─ Writer agent ────────► writes comparative summary
    │
    └─ Memories accumulate across runs
```

## Prerequisites

1. **ContextBase running**

   ```bash
   export OPENAI_API_KEY=your-key

   docker build -f docker/standalone/Dockerfile -t contextbase:local .

docker run --rm -it -p 8888:8888 -p 9999:9999 \
     -e CONTEXTBASE_API_LLM_API_KEY=$OPENAI_API_KEY \
     -e CONTEXTBASE_API_LLM_MODEL=o3-mini \
     -v $HOME/.contextbase-docker:/home/hindsight/.pg0 \
     contextbase:local
   ```

2. **OpenAI API key** (for CrewAI's LLM)

   ```bash
   export OPENAI_API_KEY=your-key
   ```

3. **Install dependencies**

   ```bash
   cd applications/crewai-memory
   pip install -r requirements.txt
   ```

   > **Note:** `contextbase-crewai` is not on PyPI — it is installed directly from the
   > [ContextBase repo](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/crewai) via git.

## Quick Start

```bash
# First run - the crew has no memories yet
python research_crew.py "What are the benefits of Rust?"

# Second run - the crew remembers the Rust research
python research_crew.py "Compare Rust with Go"

# Third run - the crew has context from both prior runs
python research_crew.py "Which language should I pick for a CLI tool?"

# Reset memory and start fresh
python research_crew.py --reset
```

## How It Works

### 1. Configure ContextBase

```python
from contextbase_crewai import configure, ContextBaseStorage

configure(contextbase_api_url="http://localhost:8888", verbose=True)

storage = ContextBaseStorage(
    bank_id="research-crew",
    mission="Track technology research findings, comparisons, and recommendations.",
)
```

### 2. Add the Reflect Tool

The `ContextBaseReflectTool` lets agents explicitly query their memories with disposition-aware synthesis:

```python
from contextbase_crewai import ContextBaseReflectTool

reflect_tool = ContextBaseReflectTool(bank_id="research-crew", budget="mid")

researcher = Agent(
    role="Researcher",
    goal="Research topics thoroughly",
    backstory="Always use contextbase_reflect to check what you already know.",
    tools=[reflect_tool],
)
```

### 3. Wire Up the Crew

```python
from crewai.memory.external.external_memory import ExternalMemory

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, summary_task],
    external_memory=ExternalMemory(storage=storage),
)

crew.kickoff()
```

CrewAI automatically:
- **Queries memories** at the start of each task
- **Stores task outputs** after each task completes

## Core Files

| File | Description |
|------|-------------|
| `research_crew.py` | Complete working example with Researcher + Writer agents |
| `requirements.txt` | Python dependencies |

## Customization

### Per-Agent Memory Banks

Give each agent isolated memory:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    per_agent_banks=True,  # "my-crew-researcher", "my-crew-writer"
)
```

### Custom Bank Resolver

Full control over bank naming:

```python
storage = ContextBaseStorage(
    bank_id="my-crew",
    bank_resolver=lambda base, agent: f"{base}-{agent.lower()}" if agent else base,
)
```

### Configuration Options

| Parameter | Default | Description |
|-----------|---------|-------------|
| `bank_id` | (required) | Memory bank identifier |
| `mission` | `None` | Guide how ContextBase organizes memories |
| `budget` | `"mid"` | Recall budget: low/mid/high |
| `max_tokens` | `4096` | Max tokens for recall results |
| `per_agent_banks` | `False` | Isolate memory per agent |
| `tags` | `None` | Tags applied when storing |
| `verbose` | `False` | Enable logging |

See the [contextbase-crewai documentation](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/crewai) for the full API reference.

## Common Issues

**"Connection refused"**
- Make sure ContextBase is running on `localhost:8888`

**"OPENAI_API_KEY not set"**
```bash
export OPENAI_API_KEY=your-key
```

**"No module named 'contextbase_crewai'"**
```bash
pip install -r requirements.txt
```

---

**Built with:**
- [CrewAI](https://crewai.com) - Multi-agent orchestration
- [contextbase-crewai](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/crewai) - ContextBase storage backend for CrewAI
- [ContextBase](https://github.com/RSIXDB/hindsight) - Long-term memory for AI agents
