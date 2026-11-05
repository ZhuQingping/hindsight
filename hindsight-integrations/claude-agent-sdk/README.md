# contextbase-claude-agent-sdk

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent memory tools and hooks for the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/), powered by [ContextBase](.).

## Installation

```bash
pip install contextbase-claude-agent-sdk
```

## Quick Start

### Tools (explicit memory)

Give your Claude agent retain/recall/reflect tools so it can decide when to use memory:

```python
from claude_agent_sdk import query, ClaudeAgentOptions
from contextbase_claude_agent_sdk import create_contextbase_server

server = create_contextbase_server(
    bank_id="my-agent",
    contextbase_api_url="http://localhost:8888",
)

async for msg in query(
    prompt="Remember that I prefer dark mode. Then check what you know about me.",
    options=ClaudeAgentOptions(
        mcp_servers={"contextbase": server},
        allowed_tools=["mcp__contextbase__*"],
    ),
):
    print(msg)
```

### Hooks (automatic memory)

Auto-recall relevant memories before each prompt and auto-retain results after each session:

```python
from claude_agent_sdk import query, ClaudeAgentOptions
from contextbase_claude_agent_sdk import create_contextbase_server, create_memory_hooks

server = create_contextbase_server(bank_id="my-agent", contextbase_api_url="http://localhost:8888")
hooks = create_memory_hooks(bank_id="my-agent", contextbase_api_url="http://localhost:8888")

async for msg in query(
    prompt="Help me refactor the auth module.",
    options=ClaudeAgentOptions(
        mcp_servers={"contextbase": server},
        allowed_tools=["mcp__contextbase__*"],
        hooks=hooks,
    ),
):
    print(msg)
```

### Global configuration

```python
from contextbase_claude_agent_sdk import configure

configure(
    contextbase_api_url="http://localhost:8888",
    api_key="your-api-key",
    budget="mid",
)
```

## Hook Configuration

Fine-tune automatic memory behavior:

```python
from contextbase_claude_agent_sdk import MemoryHookConfig, create_memory_hooks

hooks = create_memory_hooks(
    bank_id="my-agent",
    hook_config=MemoryHookConfig(
        auto_recall=True,  # inject memories before each prompt
        auto_retain=True,  # save results after each session
        retain_on_tools=["Bash"],  # also retain notable Bash outputs
        recall_max_results=5,  # max memories to inject
        retain_tags=["source:my-app"],
    ),
)
```
