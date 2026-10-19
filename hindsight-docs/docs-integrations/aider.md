---
sidebar_position: 38
title: "Aider Persistent Memory with ContextBase | Integration"
description: "Give Aider persistent long-term memory with ContextBase. contextbase-aider wraps the aider CLI — recalls relevant project memory before each session and retains the transcript after."
---

# Aider

Persistent long-term memory for [Aider](https://aider.chat), powered by [ContextBase](https://github.com/RSIXDB/hindsight). `contextbase-aider` is a drop-in wrapper for the `aider` command: it **recalls relevant project memory before each session** (injected into Aider's context via a read-only file) and **retains the session transcript after** — so each Aider session starts with what you've learned and saves what it learns. Memory is scoped **per git repo**.

[View Changelog →](/changelog/integrations/aider)

## How It Works

Aider has no MCP client or per-prompt hook, but it loads **read-only context files** and writes a **chat-history file**. The wrapper uses both:

- **Recall (before):** queries ContextBase, writes the results to `.aider.contextbase-memory.md`, and launches `aider --read .aider.contextbase-memory.md …` so the memory is in context. `aider -m "fix the auth bug"` uses that message as the recall query; otherwise a general project-context query.
- **Retain (after):** when Aider exits, the wrapper reads the slice of the chat-history file written during the session and retains it to the repo's bank.

Recall is once per session (Aider can't be hooked mid-conversation), which fits its session-oriented workflow.

## Setup

```bash
pip install contextbase-aider aider-chat
export CONTEXTBASE_API_TOKEN=hsk_...
```

Use it exactly like `aider` — all arguments pass through:

```bash
contextbase-aider                       # interactive, project memory loaded
contextbase-aider -m "add retry logic"  # one-shot; recall uses the message
contextbase-aider src/app.py            # any aider args
```

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or a self-hosted server with `CONTEXTBASE_API_URL=http://localhost:8888`. The bank defaults to the git repo name, so a project's memory is shared with the other ContextBase editor integrations on the same repo.

See the [package README](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/aider) for full configuration options.
