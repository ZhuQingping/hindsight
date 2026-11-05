# n8n-nodes-contextbase

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

[ContextBase](.) memory nodes for [n8n](https://n8n.io) — give any n8n workflow persistent long-term memory with **retain**, **recall**, and **reflect** operations.

Drop a ContextBase node anywhere in a workflow to:

- **Retain** facts emerging from a workflow (form submissions, CRM updates, customer chat) into a memory bank
- **Recall** relevant context before an LLM step so the AI sees prior history
- **Reflect** to get an LLM-synthesized answer over the bank's accumulated knowledge

## Installation

In n8n, go to **Settings → Community Nodes → Install** and enter:

```
n8n-nodes-contextbase
```

Or install via npm in your self-hosted n8n:

```bash
cd ~/.n8n/custom
npm install n8n-nodes-contextbase
```

Restart n8n and the **ContextBase** node appears in the node panel.

## Setup

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

1. **Create a ContextBase account** at [ContextBase remote service](http://localhost:9999) (free tier available) — or self-host with the [ContextBase installer](../../docs/contextbase/CUSTOMER-GUIDE.md)
2. **Get an API key** from the ContextBase dashboard
3. **In n8n**, create a new **ContextBase API** credential:
   - **API URL**: `http://localhost:8888` (or your self-hosted URL)
   - **API Key**: your `hsk_...` key (leave blank for unauthenticated self-hosted)

## Operations

### Retain — store content in a bank

| Field   | Description                                                             |
| ------- | ----------------------------------------------------------------------- |
| Bank ID | The memory bank to store in (auto-created on first use)                 |
| Content | Free text to retain. ContextBase extracts structured facts asynchronously |
| Tags    | Comma-separated tags applied to the stored memory                       |

### Recall — search a bank

| Field       | Description                                       |
| ----------- | ------------------------------------------------- |
| Bank ID     | Memory bank to search                             |
| Query       | Natural-language query                            |
| Budget      | `low` / `mid` / `high` — controls retrieval depth |
| Max Tokens  | Cap on returned memory tokens                     |
| Tags Filter | Filter memories by tag                            |

Returns: `{ results: [{ text, score, ... }, ...] }`

### Reflect — LLM-synthesized answer

| Field   | Description               |
| ------- | ------------------------- |
| Bank ID | Memory bank to reflect on |
| Query   | Question to answer        |
| Budget  | `low` / `mid` / `high`    |

Returns: `{ text: "...", citations: [...] }`

## Example workflows

**Customer-support assistant** — every closed Zendesk ticket retains the resolution; every new ticket starts with a recall against the bank to surface similar past issues.

**Sales-call coach** — Gong webhook → ContextBase Retain (call summary). Before each next prep call, recall on the prospect's name to pull every prior touchpoint.

**Personal Slack bot** — Slack DM trigger → ContextBase Recall on the user's question, pass through to OpenAI node, reply.

## License

MIT
