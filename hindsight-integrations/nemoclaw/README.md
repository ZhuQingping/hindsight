# contextbase-nemoclaw

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying ContextBase SDK dependency keeps its published package/import names.

One-command setup for [ContextBase](.) persistent memory on [NemoClaw](https://nemoclaw.ai) sandboxes.

NemoClaw runs [OpenClaw](https://openclaw.ai) inside an OpenShell sandbox with strict network egress policies. This package automates the full setup: installing the `contextbase-openclaw` plugin, configuring external API mode, merging the ContextBase egress rule into your sandbox policy, and restarting the gateway.

## Quick Start

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

```bash
npx contextbase-nemoclaw setup \
  --sandbox my-assistant \
  --api-token <your-api-key> \
  --bank-prefix my-sandbox
```

## Documentation

Full setup guide, pitfalls, and troubleshooting:

**[NemoClaw Integration Documentation](../../docs/contextbase/CUSTOMER-GUIDE.md)**

Or see [NEMOCLAW.md](./NEMOCLAW.md) in this directory for a step-by-step walkthrough.

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

## What It Does

1. **Preflight** — verifies `openshell` and `openclaw` are installed
2. **Install plugin** — runs `openclaw plugins install contextbase-openclaw`
3. **Configure plugin** — writes external API mode config to `~/.openclaw/openclaw.json`
4. **Apply policy** — reads current sandbox policy, merges ContextBase egress rule, re-applies via `openshell policy set`
5. **Restart gateway** — runs `openclaw gateway restart`

## Links

- [ContextBase Documentation](.)
- [NemoClaw](https://nemoclaw.ai)
- [OpenClaw](https://openclaw.ai)
- [GitHub Repository](.)

## License

MIT
