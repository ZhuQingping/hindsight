# ContextBase for OpenAI Codex CLI

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

Long-term memory for [OpenAI Codex CLI](https://github.com/openai/codex) — remembers your projects, preferences, and past sessions across every conversation.

## How it works

Three Codex hooks keep memory in sync automatically:

| Hook | Action |
|------|--------|
| `SessionStart` | Warms up the ContextBase server in the background |
| `UserPromptSubmit` | Recalls relevant memories and injects them into context |
| `Stop` | Retains the conversation to long-term memory |

## Requirements

- **OpenAI Codex CLI** v0.116.0 or later (hooks support)
- **Python 3.9+** (for hook scripts)
- **ContextBase**: [ContextBase remote service](.) or local `contextbase-embed`

## Installation

> ✨ **Recommended: [ContextBase remote service](http://localhost:9999)** — free tier, no self-hosting required. Skip the local daemon entirely.

```bash
curl -fsSL ../../get-codex | bash
```

The installer:
1. Downloads scripts to `~/.contextbase/codex/scripts/`
2. Writes `~/.codex/hooks.json` with absolute paths to the scripts
3. Adds `codex_hooks = true` to `~/.codex/config.toml`

### Uninstall

```bash
curl -fsSL ../../get-codex | bash -s -- --uninstall
```

## Configuration

The default config is written to `~/.contextbase/codex/settings.json` on first install.

For personal overrides (stable across updates), create `~/.contextbase/codex.json`:

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "your-api-key",
  "bankId": "my-codex-memory"
}
```

### ContextBase remote service (recommended)

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```json
{
  "contextbaseApiUrl": "http://localhost:8888",
  "contextbaseApiToken": "your-api-key"
}
```

### Self-hosting: local daemon (`contextbase-embed`)

If you'd rather run ContextBase locally, leave `contextbaseApiUrl` empty and set an LLM API key — ContextBase will start the local server automatically:

```bash
export OPENAI_API_KEY=sk-your-key
# or
export ANTHROPIC_API_KEY=your-key
```

### Configuration options

| Key | Default | Description |
|-----|---------|-------------|
| `contextbaseApiUrl` | `""` | External API URL (empty = local daemon) |
| `contextbaseApiToken` | `null` | API token for ContextBase remote service |
| `bankId` | `"codex"` | Memory bank identifier |
| `bankMission` | (set) | Guides what facts ContextBase retains |
| `autoRecall` | `true` | Inject memories before each prompt |
| `autoRetain` | `true` | Store conversations after each turn |
| `retainMode` | `"full-session"` | `"full-session"` or `"chunked"` |
| `retainEveryNTurns` | `10` | Retain every N turns (1 = every turn) |
| `recallBudget` | `"mid"` | Recall depth: `"low"`, `"mid"`, `"high"` |
| `recallMaxTokens` | `1024` | Max tokens for injected memories |
| `recallMinScores` | `{}` | Optional score floors applied after recall, keyed by score field (for example `{"semantic": 0.65, "reranker": 0.2}`). Missing or `null` scores pass so BM25-only and passthrough-reranker hits are not accidentally suppressed. When a cross-encoder reranker is active, the `reranker` floor is the main precision gate; treat reranker scores as query-local and not calibrated across queries. |
| `recallTimeout` | `10` | Timeout in seconds for recall API calls |
| `dynamicBankId` | `false` | Separate bank per project/session |
| `dynamicBankGranularity` | `["agent", "project"]` | Fields for dynamic bank ID |
| `debug` | `false` | Log debug info to stderr |

### Environment variable overrides

All settings can also be set via environment variables:

```bash
export CONTEXTBASE_API_URL=http://localhost:8888
export CONTEXTBASE_API_TOKEN=your-api-key
export CONTEXTBASE_BANK_ID=my-project
export CONTEXTBASE_RECALL_TIMEOUT=30
export CONTEXTBASE_DEBUG=true
```

## How memory works

**Recall** — before each prompt, ContextBase searches your memory bank for facts relevant to what you're about to ask. Found memories are injected as context so Codex has continuity across sessions.

**Retain** — after each turn, Codex's conversation is stored to ContextBase. The memory engine extracts facts, relationships, and experiences — so you don't need to re-explain your stack, preferences, or past decisions.

## Dynamic bank IDs

To keep separate memory per project:

```json
{
  "dynamicBankId": true,
  "dynamicBankGranularity": ["agent", "project"]
}
```

This creates banks like `codex::my-project` automatically, using the working directory name.

## Troubleshooting

**Memory not appearing**: Enable debug mode (`"debug": true`) and check stderr output.

**Server not starting**: Set `contextbaseApiUrl` to use an external server, or ensure `uvx` is on PATH for local daemon mode.

**Hooks not firing**: Check that `~/.codex/config.toml` contains `codex_hooks = true` under `[features]`, and that your Codex CLI version supports hooks (v0.116.0+).

## Local engine distribution

For local engine mode, set `CONTEXTBASE_EMBED_PACKAGE` to the administrator-approved Python distribution specification, or set `embedPackagePath` to an engine checkout. The executable is `contextbase-embed`. Remote service connections use the configured API URL and token.
