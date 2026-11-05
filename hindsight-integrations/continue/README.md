# contextbase-continue

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

[Continue.dev](https://continue.dev) integration for [ContextBase](.) — persistent long-term memory for your coding assistant.

Continue has no plugin hook that runs before a message is sent, but it does
support two native extension points that this integration uses:

1. **HTTP context provider** — type `@contextbase <query>` (or a bare `@contextbase`)
   in chat and relevant memory is recalled and injected into the model's context
   **at query time**. This package ships a tiny adapter server that implements
   Continue's HTTP context-provider contract on top of ContextBase recall.
2. **MCP server + rules** (optional) — wire the ContextBase MCP server into
   Continue's agent mode for `retain`/`recall`/`reflect` tools, with a rules file
   that tells the agent to recall automatically.

## Prerequisites

- A running ContextBase instance ([self-hosted via Docker](.) or [ContextBase remote service](http://localhost:9999))
- Continue (VS Code or JetBrains extension)
- Python 3.10+

## Installation

```bash
pip install contextbase-continue
```

## Quick start (HTTP context provider)

**1. Run the adapter**, pointing it at your ContextBase instance and bank:

```bash
export CONTEXTBASE_API_KEY=hsk_...            # omit only if your server permits no-auth access
export CONTEXTBASE_API_URL=http://localhost:8888   # required service endpoint; no bundled default
export CONTEXTBASE_CONTINUE_BANK_ID=my-project

contextbase-continue            # serves on 127.0.0.1:8123
```

**2. Register it** in Continue's `config.yaml` (`~/.continue/config.yaml` or a
workspace `.continue` block):

```yaml
context:
  - provider: http
    params:
      url: "http://127.0.0.1:8123/"
      title: contextbase
      displayTitle: ContextBase
      description: Recall long-term memory from ContextBase
```

**3. Use it.** In Continue chat, type `@contextbase` (optionally followed by what
you want to recall) and the matching memories are added to the model's context.

The adapter receives Continue's request (`{query, fullInput, options, workspacePath}`),
recalls from ContextBase, and returns context items shaped `{name, description, content}` —
exactly what Continue expects.

### Per-request bank override

The configured `CONTEXTBASE_CONTINUE_BANK_ID` is the default. A request may target
a different bank by sending `options.bankId`:

```yaml
context:
  - provider: http
    params:
      url: "http://127.0.0.1:8123/"
      options:
        bankId: another-bank
```

## Optional: automatic recall via MCP + rules

For hands-off recall/retain in **agent mode**, point Continue at the ContextBase
MCP server and add a rule telling the agent to call it. Example assets are in
[`examples/.continue/`](./examples/.continue):

- [`examples/.continue/mcpServers/contextbase.yaml`](./examples/.continue/mcpServers/contextbase.yaml) — the MCP server block
- [`examples/.continue/rules/contextbase.md`](./examples/.continue/rules/contextbase.md) — "always recall first" rule

## Configuration

| Env var | Description | Default |
| --- | --- | --- |
| `CONTEXTBASE_API_KEY` | ContextBase API key | _(none; required for Cloud)_ |
| `CONTEXTBASE_API_URL` | ContextBase API URL | `http://localhost:8888` |
| `CONTEXTBASE_CONTINUE_BANK_ID` | Default memory bank to recall against | _(none)_ |
| `CONTEXTBASE_CONTINUE_HOST` | Adapter bind host | `127.0.0.1` |
| `CONTEXTBASE_CONTINUE_PORT` | Adapter listen port | `8123` |

These can also be set programmatically via `configure(...)`. See `contextbase-continue --help`
for CLI flags.

## Development

```bash
uv sync
uv run pytest tests -v -m 'not requires_real_llm'   # deterministic suite
uv run pytest tests -v -m requires_real_llm          # gated live E2E (needs a ContextBase server)
```

## License

MIT
