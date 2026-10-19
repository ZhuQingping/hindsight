---
sidebar_position: 11
title: "Paperclip Persistent Memory with ContextBase | Integration Guide"
description: "Add long-term memory to all Paperclip agents with ContextBase. Install once as a plugin — every agent gets automatic recall before runs and retain after runs."
---

# Paperclip

Persistent memory for [Paperclip AI](https://github.com/paperclipai/paperclip) agents using [ContextBase](https://github.com/RSIXDB/hindsight).

Install the `contextbase-paperclip` plugin once. Every agent in your Paperclip instance automatically gets long-term memory that persists across runs, companies, and restarts — no code changes required.

[View Changelog →](/changelog/integrations/paperclip)

## Installation

```bash
pnpm paperclipai plugin install contextbase-paperclip
```

Then configure in **Settings → Plugins → ContextBase Memory**.

## Prerequisites

Requires Paperclip **2026.720.0 or newer**. Upgrading from an older plugin version? Open the plugin settings and pick the API key secret again: older versions saved the secret's name, and Paperclip now accepts only a reference chosen with the secret picker.

:::tip Configure your deployment
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

**Self-hosting alternative** — run ContextBase locally:

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api
```

## How It Works

```
agent.run.started
  └─ fetch issue via ctx.issues.get
       └─ recall(issueTitle + description) → cached in plugin state for this run

agent running…
  ├─ contextbase_recall(query) → cached context if query matches run start, otherwise live recall
  └─ contextbase_retain(content) → stores immediately

issue.comment.created
  └─ retain(full comment body via ctx.issues.listComments)
       └─ bank attribution: agent comment author when present; otherwise issue assignee

agent.run.finished
  └─ no-op (subscription kept for future use when payload carries output)
```

The bundled plugin manifest declares the `issues.read` and `issue.comments.read` capabilities needed by the new SDK calls, so Paperclip may prompt for these on first install or upgrade.

Memory is keyed to `companyId` + `agentId` — never to the run ID — so it accumulates across every run.

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `contextbaseApiUrl` | `http://localhost:8888` | ContextBase server URL (Cloud default; use `http://localhost:8888` for self-hosted) |
| `contextbaseApiKeyRef` | — | Paperclip secret holding your ContextBase remote service API key, chosen with the secret picker. Leave empty for self-hosted |
| `dynamicBankId` | `true` | When `true`, bank ID is derived from `bankGranularity`. Set `false` and provide `bankId` to share one static memory bank across agents |
| `bankId` | — | Static bank ID used when `dynamicBankId` is `false`. All agents sharing this value read/write the same memory bank |
| `bankGranularity` | `["company", "agent"]` | Memory isolation when `dynamicBankId` is `true`: per company+agent, per company, or per agent. Add `"user"` for per-user memory isolation (useful for GDPR compliance) |
| `recallBudget` | `mid` | `low` = fastest, `mid` = balanced, `high` = most thorough |
| `requestTimeoutMs` | `15000` | Timeout for each request to ContextBase. Raise it for self-hosted instances where recall on long issue descriptions is slower |
| `autoRetain` | `true` | Automatically retain run output after every run |

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

## Adapter Compatibility

Works with all Paperclip adapter types via the event system:

| Adapter | Supported |
|---------|-----------|
| Claude | ✓ |
| Codex | ✓ |
| Cursor | ✓ |
| HTTP | ✓ |
| Process | ✓ |
