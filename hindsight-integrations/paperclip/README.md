# contextbase-paperclip

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Persistent long-term memory for Paperclip agents via [ContextBase](.).

Install once. Every agent in your Paperclip instance gets memory that persists across runs and restarts.

Whether that memory also persists across companies is a configuration choice, not a given: `bankGranularity` decides it, and the default keeps each company separate. See [Bank ID Format](#bank-id-format).

## What It Does

- **Before each run** — fetches the run's issue and recalls relevant memories on its title + description, caches them for the agent
- **After each comment** — retains the full comment body to ContextBase (durable record of both user and agent output)
- **Agent tools** — `contextbase_recall` and `contextbase_retain` tools for agents to query and store memory mid-run

## Installation

```bash
pnpm paperclipai plugin install contextbase-paperclip
```

Then configure in **Settings → Plugins → ContextBase Memory**.

## Prerequisites

Requires Paperclip **2026.720.0 or newer**. Upgrading from an older plugin version? Open the plugin settings and pick the API key secret again: older versions saved the secret's name, and Paperclip now accepts only a reference chosen with the secret picker.

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

**Self-hosting alternative** — run ContextBase locally:

```bash
pip install contextbase-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
contextbase-api
```

## Configuration

| Field                | Default                              | Description                                                                                                                                                            |
| -------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `contextbaseApiUrl`    | `http://localhost:8888` | ContextBase server URL (Cloud default; use `http://localhost:8888` for self-hosted)                                                                                      |
| `contextbaseApiKeyRef` | —                                    | Paperclip secret holding your ContextBase remote service API key, chosen with the secret picker. Leave empty for self-hosted                                                      |
| `dynamicBankId`      | `true`                               | When `true`, bank ID is derived from `bankGranularity`. Set `false` and provide `bankId` to share one static memory bank across agents                                 |
| `bankId`             | —                                    | Static bank ID used when `dynamicBankId` is `false`. All agents sharing this value read/write the same memory bank                                                     |
| `bankGranularity`    | `["company", "agent"]`               | Memory isolation when `dynamicBankId` is `true`: per company+agent, per company, or per agent. Add `"user"` for per-user memory isolation (useful for GDPR compliance) |
| `recallBudget`       | `mid`                                | `low` = fastest, `mid` = balanced, `high` = most thorough                                                                                                              |
| `requestTimeoutMs`   | `15000`                              | Timeout for each request to ContextBase. Raise it for self-hosted instances where recall on long issue descriptions is slower                                            |
| `autoRetain`         | `true`                               | Automatically retain the full body of every issue comment. Set `false` to turn comment retention off                                                                   |
| `enabledAgentIds`    | —                                    | Restrict recall/retain to these agent IDs only. Leave empty to enable for all agents (default)                                                                         |

## Bank ID Format

```
paperclip::{companyId}::{agentId}                  ← default (company + agent granularity)
paperclip::{companyId}                             ← company granularity (shared across agents)
paperclip::{agentId}                               ← agent granularity (agent memory across companies)
paperclip::{companyId}::{agentId}::user::{userId}  ← user granularity (per-user isolation, GDPR-friendly)
{bankId}                                           ← static shared bank (dynamicBankId = false)
```

## Agent Tools

Agents can call these tools directly during a run:

**`contextbase_recall(query)`** — search memory for relevant context. Called automatically at run start; agents can also call it mid-run for targeted queries. The run-start result is reused only when the agent asks the same query; any other query triggers a live recall.

**`contextbase_retain(content)`** — store a fact or decision immediately, without waiting for run end.

## How It Works

```
agent.run.started
  └─ fetch issue via ctx.issues.get
       └─ recall(issueTitle + description) → cached in plugin state for the run

agent running…
  ├─ contextbase_recall(query) → cached context if query matches run start, otherwise live recall
  └─ contextbase_retain(content) → stores immediately

issue.comment.created
  └─ retain(full comment body via ctx.issues.listComments)
       └─ bank attribution: agent comment author when present; otherwise issue assignee

agent.run.finished
  └─ no-op (subscription kept for future use when payload carries output)
```

`autoRetain` gates the `issue.comment.created` handler above. It does not make
`agent.run.finished` retain run output: Paperclip's run-finished payload does not
carry the agent's output, so that handler has nothing to store. Setting
`autoRetain` to `false` therefore turns off comment retention, and agents can
still store memories explicitly with `contextbase_retain`.

The bundled plugin manifest declares the `issues.read` and `issue.comments.read` capabilities needed by the new SDK calls, so Paperclip may prompt for these on first install or upgrade.

By default, memory is keyed to `companyId` + `agentId`, and never to the Paperclip session or run ID, so it survives across any number of runs. `bankGranularity` controls which of those parts the key is built from; the run ID is only ever used for run-scoped plugin state such as the cached recall.

## Development

```bash
npm install
npm run build
npm test
```

Local install into a running Paperclip instance:

```bash
curl -X POST http://127.0.0.1:3100/api/plugins/install \
  -H "Content-Type: application/json" \
  -d '{"packageName":"/absolute/path/to/hindsight-integrations/paperclip","isLocalPath":true}'
```
