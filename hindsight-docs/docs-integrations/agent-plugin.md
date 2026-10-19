---
sidebar_position: 2
title: "Agent Plugins Persistent Memory with ContextBase | Integration Guide"
description: "Give any Agent Plugins client — Codex, Cursor, GitHub Copilot, Kiro, VS Code — long-term memory with ContextBase. One portable, standards-based plugin bundles the ContextBase MCP server and a memory skill for recall, retain, and reflect."
---

# Agent Plugins

Portable long-term memory for any [Agent Plugins](https://agent-plugins.org) client, powered by [ContextBase](https://github.com/RSIXDB/hindsight).

[Agent Plugins](https://agent-plugins.org) is the vendor-neutral open standard (developed with Amazon, Cursor, Microsoft, OpenAI, and Vercel) for packaging **Agent Skills + MCP servers** into a single distributable plugin. Instead of a separate integration per tool, ContextBase ships **one** plugin that every compatible client can load — at launch: **ChatGPT / Codex, Cursor, GitHub Copilot, Kiro, and VS Code**.

:::warning Codex
Codex's Agent Plugins loader drops this plugin's `Authorization` header, so the plugin cannot authenticate from Codex. Use the [Coding Agents](/sdks/integrations/coding-agents) integration instead — see [Codex](#codex) below.
:::

## Quick Start

:::tip Recommended: ContextBase remote service
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

1. Get your `hsk_...` API key from [console.example.com/connect](http://localhost:9999).
2. Set the environment variables the plugin reads:

   ```bash
   export CONTEXTBASE_API_KEY="hsk_your_token"
   export CONTEXTBASE_BANK_ID="my-project"   # optional; see "Bank selection" below
   ```

3. Install the plugin in your client (through its plugin/MCP UI, or by pointing it at the plugin directory — installation is client-specific per the standard).

Once installed, ask the agent something that depends on past context, or tell it a durable preference — it calls `recall` and `retain` automatically, guided by the bundled skill.

## What's in the plugin

The plugin is a thin, transport-only wrapper — all memory logic stays server-side in ContextBase. It follows the Agent Plugins `1.0.0` layout:

```
agent-plugin/
├── plugin.json                       # manifest ($schema + name + metadata)
├── mcp.json                          # ContextBase MCP server (Streamable HTTP)
└── skills/
    └── contextbase-memory/
        └── SKILL.md                  # teaches the agent when to recall / retain / reflect
```

- **`mcp.json`** connects the client to ContextBase's built-in [MCP server](/developer/mcp-server) over Streamable HTTP.
- **`skills/contextbase-memory/SKILL.md`** is loaded into the agent's context so it knows *when* to reach for memory, not just that the tools exist.

## Memory tools

Via the MCP server, the agent gets ContextBase's full memory surface. The three it reaches for most:

| Tool | When | What it does |
|------|------|--------------|
| `recall` | Before answering, when past context could help | Semantic + keyword + graph + temporal retrieval over the bank |
| `retain` | After learning a durable, reusable fact | Stores the fact for future sessions |
| `reflect` | When a lookup is too shallow and you need synthesized reasoning | Disposition-aware reasoning over everything remembered |

Additional tools (knowledge pages, mental models, documents, tags) are exposed too — see the [MCP Server reference](/developer/mcp-server).

## Configuration

The plugin reads two environment variables, interpolated into `mcp.json`:

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| API key | `CONTEXTBASE_API_KEY` | — | Your `hsk_...` key. Sent as `Authorization: Bearer`. Required for ContextBase remote service. |
| Memory bank | `CONTEXTBASE_BANK_ID` | see below | Bank to read from and write to (sent as `X-Bank-Id`). Use one bank per user, project, or team for isolation. |

:::note Env-var syntax varies by client
Most clients substitute `${VAR}`; some (VS Code, Cursor) use `${env:VAR}`. If your client doesn't interpolate, paste the literal key and bank id into `mcp.json`. This does not work in Codex, which removes the `Authorization` header regardless of its value.
:::

**Bank selection when `CONTEXTBASE_BANK_ID` is unset.** A client that substitutes variables sends an empty `X-Bank-Id`, and the server uses the `default` bank. A client that does *not* substitute sends the literal text `${CONTEXTBASE_BANK_ID}`, which ContextBase treats as a bank name: reads fail with bank-not-found, and the first `retain` creates a bank with that name. Set the variable, or paste the bank id literally, to avoid this.

**Self-hosting:** replace the host in `mcp.json` (`http://localhost:8888`) with your deployment's URL. A local server with the MCP endpoint open needs no API key.

## Codex

Codex's Agent Plugins loader treats `Authorization` as a header only the client may set, so it removes the one in this plugin's `mcp.json`. It also copies the other headers verbatim, without expanding `${VAR}` placeholders. The portable plugin therefore cannot authenticate to ContextBase remote service from Codex, and pasting a literal key does not help because the header is removed whatever its value.

For Codex, use the [Coding Agents](/sdks/integrations/coding-agents) integration. It writes Codex's native MCP configuration and adds automatic recall/retain hooks:

```bash
npx contextbase-coding-agents install codex
```

## Explicit tools vs. automatic capture

Agent Plugins `1.0.0` standardizes **Skills + MCP**, not session lifecycle hooks. This plugin therefore delivers **explicit, tool-driven** memory that works identically across every supported client.

For the fully automatic experience — recall injected before every prompt and transcripts retained on session end — use the hook-based [Coding Agents](/sdks/integrations/coding-agents) integration, which covers Claude Code, Codex and many other coding agents. It shares the same ContextBase banks, so memory captured by the hook-based integration is recalled through the Agent Plugin, and vice versa.

## Troubleshooting

**No memories recalled**: `recall` returns results only after something has been retained. Retain a fact first, or seed the bank via the [API](/developer/api/quickstart).

**401 Unauthorized**: Check `CONTEXTBASE_API_KEY` is set and your client is interpolating it into the `Authorization` header (see the env-var syntax note above). In Codex this is expected: the header is removed, so use the [Codex](#codex) path instead.

**A bank named `${CONTEXTBASE_BANK_ID}` appears**: your client sent the placeholder without substituting it. Set the variable or paste the bank id into `mcp.json`, then delete the stray bank.

**Wrong or empty memory**: Confirm `CONTEXTBASE_BANK_ID` points at the bank you expect. Different tools writing to different banks won't share memory.

## Learn more

- [Agent Plugins standard](https://agent-plugins.org)
- [ContextBase MCP Server reference](/developer/mcp-server)
- Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
