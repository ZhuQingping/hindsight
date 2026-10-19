# ContextBase for Dify

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Dify](https://dify.ai) workflows via [ContextBase](https://github.com/RSIXDB/hindsight).

Three tools — **Retain**, **Recall**, **Reflect** — drop into any Dify workflow alongside your other nodes.

- **Author**: Vectorize, Inc.
- **Repository**: <https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/dify>
- **Contact**: support@vectorize.io · [GitHub Issues](https://github.com/vectorize-io/hindsight/issues)

## Setup

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

1. Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
2. **Get an API key** from the ContextBase dashboard.
3. **In Dify**, install this plugin (Marketplace or upload `.difypkg`), then add credentials:
   - **API URL**: `http://localhost:8888` (Cloud) or your self-hosted URL
   - **API Key**: your `hsk_...` key (optional for self-hosted unauthenticated instances)

## Tools

### Retain

Store content in a bank. ContextBase extracts facts asynchronously after the call returns.

| Field | Description |
|---|---|
| Bank ID | Memory bank to store in (auto-created on first use) |
| Content | Free-text content to retain |
| Tags | Optional comma-separated tags |

### Recall

Search a bank for memories relevant to a query. Returns a `results` array.

| Field | Description |
|---|---|
| Bank ID | Memory bank to search |
| Query | Natural-language query |
| Budget | `low` / `mid` / `high` |
| Max Tokens | Cap on tokens returned |
| Tags | Optional comma-separated tag filter |

### Reflect

Get an LLM-synthesized answer over the bank. Returns a `text` field.

| Field | Description |
|---|---|
| Bank ID | Memory bank |
| Query | Question to answer |
| Budget | `low` / `mid` / `high` |

## Example workflow

**Customer-support assistant** — every closed Zendesk ticket triggers a Retain. Every new ticket starts with a Recall against the bank, then passes the context to your LLM node to draft a first reply.

## Source

- GitHub: [`RSIXDB/hindsight`](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/dify)
- Docs: [hindsight.vectorize.io/sdks/integrations/dify](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs)
