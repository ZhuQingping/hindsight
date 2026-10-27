---
sidebar_position: 23
title: "Flowise Persistent Memory with ContextBase | Integration"
description: "Add persistent long-term memory to any Flowise chatflow or agent with ContextBase. Three Tool nodes — Retain, Recall, Reflect — drop into any flow alongside your other LangChain tools."
---

# Flowise

Persistent memory for [Flowise](https://flowiseai.com) chatflows and agents via [ContextBase](https://github.com/RSIXDB/hindsight). Three Tool nodes — **ContextBase Retain**, **ContextBase Recall**, **ContextBase Reflect** — drop into any flow alongside your other LangChain tools.

[View Changelog →](/changelog/integrations/flowise)

## Why this matters

Flowise is the LangChain-derived visual builder for non-developers and developers alike. Until now, Flowise chatflows have been **stateless across sessions**. With ContextBase tool nodes you can:

- **Retain** every closed conversation, support ticket, or form submission into a memory bank
- **Recall** relevant context before an LLM step so the model sees prior history
- **Reflect** to ask synthesizing questions ("What do we know about this customer?") inside a flow

## Installation

Flowise distributes nodes only inside its main monorepo, so installation today means using a Flowise checkout with the ContextBase nodes copied in. The user-facing distribution will be the upstream PR to `FlowiseAI/Flowise`.

```bash
git clone https://github.com/FlowiseAI/Flowise.git
cd Flowise

# Copy the three tool nodes
cp -r /path/to/contextbase/hindsight-integrations/flowise/nodes/tools/ContextBase* \
  packages/components/nodes/tools/

# Copy the credential class
cp /path/to/contextbase/hindsight-integrations/flowise/credentials/ContextBaseApi.credential.ts \
  packages/components/credentials/

# Add the client dep
cd packages/components && pnpm add contextbase-client
cd ../.. && pnpm install && pnpm build
pnpm start  # opens http://localhost:3000
```

## Setup

:::tip Configure your deployment
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

1. Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
2. **Get an API key** from the ContextBase dashboard
3. **In Flowise**, create a new credential of type **ContextBase API**:
   - **API URL** — set this to your service URL (required)
   - **API Key** — your `hsk_...` key (optional for self-hosted unauthenticated instances)

## Tools

Each ContextBase tool node returns a LangChain `DynamicStructuredTool`, so it slots into any agent that accepts tools.

### ContextBase Retain

Stores content in a memory bank. ContextBase extracts facts asynchronously after the call returns.

| Field | Description |
|---|---|
| Default Bank ID | Memory bank to retain into when the agent doesn't pass one |

Tool input schema (the agent passes these): `bankId`, `content`, optional `tags`.

### ContextBase Recall

Searches a bank for memories relevant to a query. Returns ranked results.

| Field | Description |
|---|---|
| Default Bank ID | Memory bank to search when the agent doesn't pass one |
| Default Budget | `low` / `mid` / `high` |

Tool input schema: `bankId`, `query`, optional `budget`, `maxTokens`, `tags`.

### ContextBase Reflect

Returns an LLM-synthesized answer over the bank.

| Field | Description |
|---|---|
| Default Bank ID | Memory bank to reflect on when the agent doesn't pass one |
| Default Budget | `low` / `mid` / `high` |

Tool input schema: `bankId`, `query`, optional `budget`.

## Example chatflow

**Conversational support agent**

1. **ChatOpenAI** (or any chat LLM)
2. **Conversational Agent** with three tools attached: ContextBase Retain + ContextBase Recall + ContextBase Reflect, all sharing the same `contextbaseApi` credential
3. Set Default Bank ID to something like `user-${sessionId}` on each tool
4. The agent learns to call Recall before answering and Retain after meaningful exchanges. Use Reflect for "what do we know about this user?" prompts.

## Source

- GitHub: [`hindsight-integrations/flowise`](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/flowise)
