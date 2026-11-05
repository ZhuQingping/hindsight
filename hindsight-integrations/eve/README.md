# ContextBase for Eve

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Long-term memory for [Vercel Eve](https://eve.dev) agents, powered by
[ContextBase](.). A memory provider for Eve's
[memory slots](https://eve.dev/docs/memory): relevant memory is recalled on the live user
message before every turn, each exchange is captured after, and every scope (user, tenant,
channel) gets its own isolated ContextBase bank — **without the model ever choosing to call a
tool.**

## How it works

Eve resolves and locks a scope for every turn, then calls the provider at fixed points:

| Phase            | What ContextBase does                                                                                |
| ---------------- | -------------------------------------------------------------------------------------------------- |
| `turn.started`   | Recalls memories relevant to the user's message and places them in context, attributed to the slot |
| `turn.completed` | Retains the user message and the assistant's final reply (idempotent per eve operation id)         |
| tools            | Exposes `<slot>__reflect`, so the model can ask long-term memory a question when it needs to       |

Every read and write is partitioned by the locked scope key: one ContextBase bank per scope,
auto-created on first use. Two tenants can never see each other's memory.

## Install

```bash
npm install contextbase-eve
```

`eve` (>= 0.45.1) is a peer dependency — you already have it in an Eve project.

## Quick start

Create one file:

```ts
// agent/memory/contextbase.ts
import { contextbaseMemory } from "contextbase-eve";
import { defineMemory } from "eve/memory";
import { byPrincipal } from "eve/memory/scope";

export default defineMemory({
  description: "Long-term memory about the current user.",
  provider: contextbaseMemory(),
  scope: byPrincipal,
});
```

That's it. The provider reads its connection from the environment:

| Env var             | Purpose                                                                  |
| ------------------- | ------------------------------------------------------------------------ |
| `CONTEXTBASE_API_KEY` | Bearer token sent as `Authorization: Bearer <key>`                       |
| `CONTEXTBASE_API_URL` | Required ContextBase REST base, unless passed as `apiUrl`               |
| `CONTEXTBASE_CLOUD_API_URL` | Optional deployment Cloud origin; matching endpoints require an API key |
| `CONTEXTBASE_BANK_ID` | _Optional._ Pin every scope to one shared bank (single-user agents only) |

### ContextBase remote service

Set `CONTEXTBASE_API_URL` to your service endpoint and `CONTEXTBASE_API_KEY` to a
key issued by its administrator. There is no bundled service URL. Deployments
can also set `CONTEXTBASE_CLOUD_API_URL` to enable a missing-key check for that origin.

### Self-hosted

```bash
export CONTEXTBASE_API_URL="http://localhost:8000"
export CONTEXTBASE_API_KEY="…"   # or pass apiKey: null below for a no-auth server
```

```ts
provider: contextbaseMemory({ apiUrl: "http://localhost:8000", apiKey: null }),
```

## Scope → bank

`scope` is Eve's — `byPrincipal` gives each authenticated caller their own memory; a custom
resolver can scope by tenant, channel, or anything else in trusted session metadata (see
[Eve's memory docs](https://eve.dev/docs/memory)). ContextBase maps each locked scope to a bank:

- **Default:** the bank is the scope key (`memscope1_…`), an opaque digest Eve derives from the
  namespace and scope. Isolation is automatic.
- **Custom:** pass a resolver to name banks yourself, e.g. ``bankId: (scope) => `eve-${scope.value}` ``
  for human-readable bank names in the ContextBase dashboard.
- **Shared:** a string `bankId` (or `CONTEXTBASE_BANK_ID`) pins every scope to a single bank. Only
  do this for single-user agents — it disables per-scope isolation.

## Options

```ts
contextbaseMemory({
  apiUrl, // string — REST base; defaults to CONTEXTBASE_API_URL, then Cloud
  apiKey, // string | null — bearer token; null = no auth (local dev)
  bankId, // string | (scope) => string — see "Scope → bank"
  budget, // "low" | "mid" | "high" — recall result budget (default "mid")
  maxTokens, // number — recall token budget (default 1024)
  recallQuery, // string — query when the turn has no user text (default: a broad profile query)
  context, // string — `context` tag written on retained items (default "eve")
  includeAssistantReply, // boolean — also retain the assistant's reply (default true)
  capture, // boolean — retain each turn (default true; false = recall-only)
  tools, // boolean — expose the `reflect` tool (default true)
  timeoutMs, // number — HTTP timeout (default 15000)
  onError, // (err, phase) => void — failures degrade via this (default console.warn)
});
```

## Notes

- Recall never fails a turn: a ContextBase error is reported through `onError` and the turn runs
  without memory. Captures run asynchronously and never block a reply.
- Each turn's recall is one message with a stable id, so it **supersedes** the previous turn's
  block instead of piling up in session history — including after compaction.
- Captures are keyed by Eve's `operationId`; a replayed capture replaces the earlier document
  rather than storing it twice.
- By default **both** the user's message and the assistant's reply are retained — the reply is
  usually where the answer lives. Set `includeAssistantReply: false` to store only the user's
  message.

## Known issue: capture on eve 0.51.0 – 0.68.x

eve 0.51.0 stopped passing the turn's history to `turn.completed` (a regression from
[vercel/eve#2690](https://github.com/vercel/eve/pull/2690)), so **no provider's
`capture["turn.completed"]` runs** on those versions — memory is recalled but nothing new is
stored. Tracked in [vercel/eve#3223](https://github.com/vercel/eve/issues/3223) and fixed by
[vercel/eve#3985](https://github.com/vercel/eve/pull/3985), which ships in eve 0.69.0 — upgrade
to it. Recall, the `reflect` tool, and compaction capture are unaffected. On an older eve, either
pin `eve@0.50.0`, or keep the
deprecated `contextbaseRetainHook()` in `agent/hooks/contextbase.ts` next to the provider — eve's hook
events still fire — giving both the same string `bankId` so they share a bank.

## Verify

Run your agent. Tell it a durable preference in one session ("whenever you write me code, use
Python with full type hints and no comments"). Start a **fresh** session as the same user and
ask for something — the agent applies the remembered preference, because the memory was recalled
before the model ran, with no tool call.

## Migrating from 0.2

0.2 wired memory through two authored files (`agent/instructions/contextbase.ts` with
`contextbaseMemory()` and `agent/hooks/contextbase.ts` with `contextbaseRetainHook()`), before Eve had a
memory provider contract. Replace both with the single `agent/memory/contextbase.ts` above. The old
entrypoints still ship as `contextbaseAutoRecall()` and `contextbaseRetainHook()` (deprecated, removed
in the next release); `contextbaseMemory()` now returns the provider.

What changes: recall uses the live user message instead of a fixed broad query, memory is
isolated per scope instead of one bank for everyone, and recalled context arrives as a
slot-attributed message rather than system instructions.

## Links

- [ContextBase docs](.)
- [Eve memory](https://eve.dev/docs/memory) ·
  [Build a memory provider](https://github.com/vercel/eve/blob/main/docs/memory/custom-provider.md)
