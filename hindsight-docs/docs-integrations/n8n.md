---
sidebar_position: 32
title: "n8n Persistent Memory with ContextBase | Integration"
description: "Add persistent long-term memory to any n8n workflow with ContextBase. A community node provides Retain, Recall, and Reflect operations — drop them into any workflow alongside Slack, Sheets, OpenAI, and 400+ other integrations."
---

# n8n

Persistent memory for [n8n](https://n8n.io) workflows via [ContextBase](https://github.com/RSIXDB/hindsight). The `n8n-nodes-contextbase` community node package adds three operations — **Retain**, **Recall**, **Reflect** — that work alongside any other n8n node.

[View Changelog →](/changelog/integrations/n8n)

## Why this matters

n8n is the connective tissue of automation: triggers from Gmail, Slack, Sheets, Stripe, Notion; actions across 400+ apps. Until now it has been **stateless** — every workflow run starts fresh. With ContextBase nodes you can:

- **Retain** every closed support ticket, sales-call summary, or form submission into a memory bank
- **Recall** relevant context before an OpenAI / Anthropic / Cohere step so the LLM sees prior history
- **Reflect** to ask synthesizing questions ("What do we know about this customer?") right inside a workflow

## Installation

In your n8n instance, go to **Settings → Community Nodes → Install** and enter:

```
n8n-nodes-contextbase
```

Or for self-hosted n8n:

```bash
cd ~/.n8n/custom
npm install n8n-nodes-contextbase
```

Restart n8n; the **ContextBase** node appears in the node panel.

## Setup

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

1. Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
2. **Get an API key** from the ContextBase dashboard
3. **In n8n**, create a new **ContextBase API** credential with your API URL (defaults to ContextBase remote service) and the `hsk_...` key

## Operations

### Retain

Store content in a bank. ContextBase extracts facts asynchronously after the call returns.

| Field | Description |
|---|---|
| Bank ID | Memory bank to store in (auto-created on first use) |
| Content | Free text to retain |
| Tags | Comma-separated tags |

### Recall

Search a bank for memories relevant to a query. Returns a `results` array.

| Field | Description |
|---|---|
| Bank ID | Memory bank to search |
| Query | Natural-language query |
| Budget | `low` / `mid` / `high` |
| Max Tokens | Cap on returned memory tokens |
| Tags Filter | Filter by tag |

### Reflect

Get an LLM-synthesized answer over the bank. Returns `text`.

| Field | Description |
|---|---|
| Bank ID | Memory bank |
| Query | Question to answer |
| Budget | `low` / `mid` / `high` |

## Example workflows

**Customer-support assistant** — every closed Zendesk ticket retains the resolution. Every new ticket starts with a recall against the bank to surface similar past issues, then passes that context to OpenAI to draft the first reply.

**Sales-call coach** — Gong webhook → ContextBase Retain (call summary). Before each next prep call, recall on the prospect's name to pull every prior touchpoint, then format into the daily prep doc.

**Personal Slack bot** — Slack DM trigger → ContextBase Recall on the user's question → OpenAI for the answer → Slack reply. The bot remembers every conversation across sessions.

## Source

- npm: [`n8n-nodes-contextbase`](https://www.npmjs.com/package/@vectorize-io/n8n-nodes-hindsight)
- GitHub: [`hindsight-integrations/n8n`](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/n8n)
