# contextbase-cline

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Persistent long-term memory for [Cline](https://github.com/cline/cline) via [ContextBase](https://github.com/RSIXDB/hindsight) — **no MCP required**.

Cline's [lifecycle hooks](https://docs.cline.bot/customization/hooks) run small scripts at key moments. This integration installs hooks that automatically **recall** relevant memories before Cline works and **retain** what happened when a task ends. Memory persists across sessions, so Cline builds on past context instead of starting cold.

## What It Does

- **Before a task / each message** — the `TaskStart` and `UserPromptSubmit` hooks recall relevant memories from ContextBase and inject them as context.
- **When a task ends** — the `TaskComplete` (and `TaskCancel`) hook retains the task's prompts and summary for future sessions.
- **Deterministic** — because it runs on hooks, memory happens automatically; it doesn't depend on the model deciding to call a tool (no MCP).

## Prerequisites

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

**Self-hosting alternative:**

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api  # starts on http://localhost:8888
```

> **Platform:** Cline hooks run on **macOS and Linux only** (no Windows). Hooks need Python 3.

## Installation

```bash
pip install contextbase-cline
```

Then, from your project directory:

```bash
contextbase-cline install --api-url http://localhost:8888 --api-token YOUR_KEY
```

Install globally (applies to all projects):

```bash
contextbase-cline install --global --api-url http://localhost:8888 --api-token YOUR_KEY
```

To remove it later: `contextbase-cline uninstall` (add `--global` if you installed globally).

This copies four hook scripts (`TaskStart`, `UserPromptSubmit`, `TaskComplete`, `TaskCancel`) plus their `lib/` and `settings.json` into:

- `.clinerules/hooks/` (project install — commit it to share with your team), or
- `~/Documents/Cline/Rules/Hooks/` (global install).

**Final step — enable hooks in Cline:** Settings → Features → Hooks.

## How It Works

```
Task starts ─ TaskStart ─────────► recall(task description) → inject memories
You send a message ─ UserPromptSubmit ─► recall(prompt) → inject memories
                                          (and append the prompt to the task transcript)
Task completes ─ TaskComplete ──► retain(accumulated transcript + summary)
Task cancelled ─ TaskCancel ────► retain(partial transcript)
```

Cline doesn't hand hooks a conversation transcript, so the integration accumulates each task's prompts in `~/.contextbase/cline/state/` and retains them at task end. Memories land in a single bank (`cline` by default).

## Configuration

Defaults live in the installed `settings.json`; put personal overrides in `~/.contextbase/cline.json` (stable across reinstalls). Common keys:

| Setting             | Default                  | Description                                                       |
| ------------------- | ------------------------ | ----------------------------------------------------------------- |
| `contextbaseApiUrl`   | (empty)                  | ContextBase server URL. Empty → use a local server on `apiPort`.    |
| `contextbaseApiToken` | `null`                   | API key for ContextBase remote service.                                      |
| `bankId`            | `cline`                  | Memory bank for this integration.                                 |
| `autoRecall`        | `true`                   | Inject memories before tasks/prompts.                             |
| `autoRetain`        | `true`                   | Retain the task transcript when it ends.                          |
| `recallBudget`      | `mid`                    | Recall depth: `low` / `mid` / `high`.                             |
| `recallTypes`       | `["world","experience"]` | Memory types to recall.                                           |
| `dynamicBankId`     | `false`                  | Separate bank per project/session (see `dynamicBankGranularity`). |
| `debug`             | `false`                  | Log to stderr.                                                    |

Every key can also be set via `CONTEXTBASE_*` environment variables (e.g. `CONTEXTBASE_BANK_ID`, `CONTEXTBASE_AUTO_RECALL=false`).

## Verifying Setup

1. Start Hindsight (`hindsight-api` or ContextBase remote service) and run `contextbase-cline install` with your URL/key.
2. Enable hooks in Cline (Settings → Features → Hooks).
3. Start a task — recalled memories appear in context as a `<contextbase_memories>` block.
4. Complete a task, then check the `cline` bank (via the API or dashboard) — a memory should appear.

You can smoke-test a hook without Cline:

```bash
echo '{"hookName":"UserPromptSubmit","prompt":"how do we authenticate?","taskId":"t1","workspaceRoots":["/tmp/x"]}' \
  | .clinerules/hooks/UserPromptSubmit
# → {"cancel": false, "contextModification": "<contextbase_memories>…", "errorMessage": ""}
```

## Development

```bash
uv sync
uv run pytest tests/ -v
```
