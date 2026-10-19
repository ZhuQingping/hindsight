# ContextBase for Flowise

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Flowise](https://flowiseai.com) chatflows and agents via [ContextBase](https://github.com/RSIXDB/hindsight).

Three Tool nodes — **ContextBase Retain**, **ContextBase Recall**, **ContextBase Reflect** — drop into any Flowise chatflow or agent flow alongside your other Tools.

- **Author**: Vectorize, Inc.
- **Repository**: <https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/flowise>
- **Contact**: support@vectorize.io · [GitHub Issues](https://github.com/vectorize-io/hindsight/issues)

## Status

This package is the source-of-truth copy of the ContextBase Flowise nodes. Flowise distributes nodes only inside its main monorepo, so the user-facing distribution is an upstream PR to [`FlowiseAI/Flowise`](https://github.com/FlowiseAI/Flowise) under `packages/components/`.

## Installation (local Flowise dev fork)

While the upstream PR is in flight, you can use the nodes by copying them into a Flowise checkout:

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
cd packages/components && pnpm add @vectorize-io/hindsight-client
cd ../.. && pnpm install && pnpm build
pnpm start  # opens http://localhost:3000
```

## Setup

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

1. Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
2. **Get an API key** from the ContextBase dashboard.
3. **In Flowise**, create a new credential of type **ContextBase API**:
   - **API URL**: `http://localhost:8888` (Cloud) or your self-hosted URL
   - **API Key**: your `hsk_...` key (optional for self-hosted unauthenticated instances)

## Tools

### ContextBase Retain

Stores free-text content in a memory bank. ContextBase extracts facts asynchronously after the call returns.

| Field           | Description                                                |
| --------------- | ---------------------------------------------------------- |
| Default Bank ID | Memory bank to retain into when the agent doesn't pass one |

Tool input schema (the agent passes these): `bankId`, `content`, optional `tags`.

### ContextBase Recall

Searches a bank for memories relevant to a query. Returns ranked results.

| Field           | Description                                           |
| --------------- | ----------------------------------------------------- |
| Default Bank ID | Memory bank to search when the agent doesn't pass one |
| Default Budget  | `low` / `mid` / `high`                                |

Tool input schema: `bankId`, `query`, optional `budget`, `maxTokens`, `tags`.

### ContextBase Reflect

Returns an LLM-synthesized answer over a bank.

| Field           | Description                                               |
| --------------- | --------------------------------------------------------- |
| Default Bank ID | Memory bank to reflect on when the agent doesn't pass one |
| Default Budget  | `low` / `mid` / `high`                                    |

Tool input schema: `bankId`, `query`, optional `budget`.

## Example chatflow

A typical conversational agent recipe:

1. **ChatOpenAI** (or any chat LLM)
2. **Conversational Agent** with three tools attached: ContextBase Retain + ContextBase Recall + ContextBase Reflect
3. Set a default Bank ID like `user-${sessionId}` on each tool
4. The agent learns to call Recall before answering and Retain after meaningful exchanges

## Source

- GitHub: [`RSIXDB/hindsight`](https://github.com/RSIXDB/hindsight/tree/main/hindsight-integrations/flowise)
- Docs: [hindsight.vectorize.io/sdks/integrations/flowise](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs)
