---
sidebar_position: 5
title: "NemoClaw Persistent Memory with ContextBase | Integration Guide"
description: "Add persistent memory to NemoClaw sandboxed agents with ContextBase. One command adds automated memory extraction and auto-recall to any NemoClaw sandbox — no code changes required."
---

# NemoClaw

Persistent memory for [NemoClaw](https://nemoclaw.ai) sandboxed agents using [ContextBase](https://github.com/RSIXDB/hindsight).

NemoClaw runs [OpenClaw](https://openclaw.ai) inside an OpenShell sandbox with controlled filesystem, process, and network egress policies. The `contextbase-nemoclaw` package automates adding ContextBase memory to a sandbox in one command — no code changes required.

[View Changelog →](/changelog/integrations/nemoclaw)

## Quick Start

:::tip Configure your deployment
Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
:::

```bash
npx contextbase-nemoclaw setup \
  --sandbox my-assistant \
  --api-token <your-api-key> \
  --bank-prefix my-sandbox
```

You'll see output like:

```
[0] Preflight checks...
  ✓ openshell found
  ✓ openclaw found

[1] Installing contextbase-openclaw plugin...
  ✓ Plugin installed

[2] Configuring plugin in ~/.openclaw/openclaw.json...
  ✓ Plugin config written (bank: my-sandbox-openclaw)

[3] Applying ContextBase network policy to sandbox "my-assistant"...
  ✓ Policy version 2 submitted
  ✓ Policy version 2 loaded (active version: 2)

[4] Restarting OpenClaw gateway...
  ✓ Gateway restarted

✓ Setup complete!
```

## How It Works

### The sandbox problem

OpenShell enforces strict network egress — every outbound endpoint must be explicitly permitted in the sandbox policy. By default, the ContextBase API (`memory.example.com`) is not in that list.

The `contextbase-openclaw` plugin supports **external API mode**, where it skips the local daemon entirely and makes direct HTTPS calls to ContextBase remote service. This is the natural fit for sandboxed environments: the plugin becomes a thin HTTP client, and the only sandbox change needed is one egress rule.

### What the setup command does

1. **Preflight** — verifies `openshell` and `openclaw` are installed
2. **Install plugin** — runs `openclaw plugins install contextbase-openclaw`
3. **Configure plugin** — writes external API mode config to `~/.openclaw/openclaw.json`
4. **Apply policy** — reads the current sandbox policy, merges the ContextBase egress block, and re-applies via `openshell policy set`
5. **Restart gateway** — runs `openclaw gateway restart`

### Memory flow

Once set up, the `contextbase-openclaw` plugin hooks into the OpenClaw gateway lifecycle:

- **`before_agent_start`** — recalls relevant memories from past sessions and injects them into context
- **`agent_end`** — retains the conversation to the ContextBase memory bank

The sandbox doesn't interfere with either step — it sees the ContextBase calls as normal HTTPS egress to a permitted endpoint.

## CLI Reference

```
contextbase-nemoclaw setup [options]

Options:
  --sandbox <name>       NemoClaw sandbox name (required)
  --api-token <token>    ContextBase API token (required)
  --api-url <url>        ContextBase API URL (required)
  --bank-prefix <prefix> Memory bank prefix (default: "nemoclaw")
  --skip-policy          Skip sandbox network policy update
  --skip-plugin-install  Skip openclaw plugin installation
  --dry-run              Preview changes without applying
  --help                 Show help
```

Use `--dry-run` to preview all changes before applying anything. Use `--skip-policy` if you manage sandbox policies manually.

## Manual Setup

If you prefer to apply the steps yourself instead of using the CLI:

### 1. Install the plugin

```bash
openclaw plugins install contextbase-openclaw
```

### 2. Configure `~/.openclaw/openclaw.json`

```json
{
  "plugins": {
    "entries": {
      "contextbase-openclaw": {
        "enabled": true,
        "config": {
          "contextbaseApiUrl": "http://localhost:8888",
          "contextbaseApiToken": "<your-api-key>",
          "llmProvider": "claude-code",
          "dynamicBankId": false,
          "bankIdPrefix": "my-sandbox"
        }
      }
    }
  }
}
```

`llmProvider: "claude-code"` uses the Claude Code process already present in the sandbox — no additional API key needed.

### 3. Add the ContextBase network policy

`openshell policy set` replaces the entire policy document. Export your current policy first, add the ContextBase block, then re-apply:

```yaml
network_policies:
  contextbase:
    name: contextbase
    endpoints:
      - host: memory.example.com
        port: 443
        protocol: rest
        tls: terminate
        enforcement: enforce
        rules:
          - allow:
              method: GET
              path: /**
          - allow:
              method: POST
              path: /**
          - allow:
              method: PUT
              path: /**
    binaries:
      - path: /usr/local/bin/openclaw
```

```bash
openshell policy set my-sandbox --policy /path/to/full-policy.yaml --wait
openclaw gateway restart
```

## Configuration Options

| Option | Type | Default | Description |
|---|---|---|---|
| `contextbaseApiUrl` | string | — | ContextBase API base URL |
| `contextbaseApiToken` | string | — | API token for authentication |
| `llmProvider` | string | auto-detect | LLM provider for memory extraction |
| `dynamicBankId` | boolean | `false` | Isolate memory per user (`true`) or share across sessions (`false`) |
| `bankIdPrefix` | string | `"nemoclaw"` | Prefix for the memory bank name |

### Bank naming

When `dynamicBankId: false`, all sessions write to a single bank named `{bankIdPrefix}-openclaw`. When `dynamicBankId: true`, each user gets an isolated bank — useful for multi-tenant deployments.

## Verifying It Works

After setup, check the gateway logs:

```bash
tail -f /tmp/openclaw/openclaw-*.log | grep ContextBase
```

On startup you should see:

```
[ContextBase] Plugin loaded successfully
[ContextBase] ✓ Using external API: http://localhost:8888
[ContextBase] External API health: {"status":"healthy","database":"connected"}
[ContextBase] Default bank: my-sandbox-openclaw
[ContextBase] ✓ Ready (external API mode)
```

After a conversation:

```
[ContextBase] before_agent_start - bank: my-sandbox-openclaw, channel: undefined/webchat
[ContextBase Hook] agent_end triggered - bank: my-sandbox-openclaw
[ContextBase] Retained 6 messages to bank my-sandbox-openclaw for session agent:main:...
```

## Pitfalls

### Policy replacement is full-document

`openshell policy set` replaces the entire policy document. The `contextbase-nemoclaw setup` command handles this automatically. If you're applying manually, export the current policy first so existing rules aren't lost.

### LaunchAgent can't follow symlinks on macOS

On macOS, the OpenClaw gateway runs as a LaunchAgent under a restricted security context. `openclaw plugins install --link` creates a symlink the LaunchAgent can't follow — the setup command installs as a copy instead. If you see `EPERM: operation not permitted, scandir` in gateway logs, this is the cause.

### Memory retention is asynchronous

Fact extraction and entity resolution happen in the background after `retain`. If you open a new session immediately after closing one, the most recent memories may not be indexed yet — typically a few seconds.

### Binary-scoped egress

The `binaries` field in the network policy restricts the egress rule to a specific executable path. If OpenClaw updates and the binary path changes, the rule silently stops working. Check your binary path after upgrades.

## Troubleshooting

### Plugin not loading

```bash
openclaw plugins list | grep contextbase
# Should show: ✓ enabled │ ContextBase Memory │ ...

# Reinstall
openclaw plugins install contextbase-openclaw
```

### Egress blocked

If calls to `memory.example.com` are being blocked, check the active sandbox policy:

```bash
openshell sandbox get my-assistant
```

Verify the `contextbase` block is present and the `binaries` path matches your OpenClaw binary:

```bash
which openclaw
```

### External API not connecting

```bash
tail -f /tmp/openclaw/openclaw-*.log | grep ContextBase

# If you see daemon startup messages instead of "Using external API",
# the plugin config isn't being read — check ~/.openclaw/openclaw.json
```
