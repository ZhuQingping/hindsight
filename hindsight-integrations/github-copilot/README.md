# contextbase-copilot

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Long-term memory for **GitHub Copilot** in VS Code, powered by [ContextBase](https://github.com/RSIXDB/hindsight).

`contextbase-copilot init` wires the ContextBase **MCP server** into VS Code's
`.vscode/mcp.json` and adds a recall/retain rule to `.github/copilot-instructions.md`.
Copilot's agent mode then has `recall` / `retain` / `reflect` tools and — guided
by the rule — recalls relevant memory at the start of a task and retains durable
facts as it works.

## How it works

VS Code Copilot supports two things this integration uses:

- **MCP servers** in `.vscode/mcp.json` (agent mode), including **HTTP servers**
  with headers — so the ContextBase MCP endpoint connects directly:

  ```json
  {
    "servers": {
      "contextbase": {
        "type": "http",
        "url": "http://localhost:8888/mcp/my-project/",
        "headers": { "Authorization": "Bearer hsk_..." }
      }
    }
  }
  ```

- **`.github/copilot-instructions.md`**, which Copilot applies to every chat in
  the workspace — that's where the recall/retain rule lives.

## Install

```bash
pip install contextbase-copilot
cd your-project
contextbase-copilot init --api-token YOUR_CONTEXTBASE_API_KEY --bank-id my-project
```

`init` merges the `servers` entry into `./.vscode/mcp.json` and writes the rule
into `./.github/copilot-instructions.md`. Reload VS Code, open Copilot Chat in
**agent mode**, and start the `contextbase` MCP server from the chat's tools menu.

Use a [ContextBase remote service](https://github.com/RSIXDB/hindsight) key, or a self-hosted
server with `--api-url http://localhost:8888` (no token needed for an open local
server). If `mcp.json` has comments, `init` prints the snippet to paste instead
of touching the file — or run `contextbase-copilot init --print-only` anytime.

## Commands

| Command | Description |
| --- | --- |
| `contextbase-copilot init` | Add the MCP server + recall/retain rule |
| `contextbase-copilot status` | Show whether the server + rule are configured |
| `contextbase-copilot uninstall` | Remove the server + rule |

## Configuration

| Setting | Env var | Default |
| --- | --- | --- |
| API URL | `CONTEXTBASE_API_URL` | `http://localhost:8888` |
| API token | `CONTEXTBASE_API_TOKEN` | _(none; required for Cloud)_ |
| Bank id | `CONTEXTBASE_COPILOT_BANK_ID` | `copilot` |

## Development

```bash
uv sync
uv run pytest tests -v -m 'not requires_real_llm'   # deterministic suite
uv run pytest tests -v -m requires_real_llm          # gated MCP-endpoint check
```

## License

MIT
