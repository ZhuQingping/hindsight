# agentstratum

Agent memory delivered as a hosted service. Each customer connects using their own API Endpoint, MCP Endpoint and credential from the console.

## Client distribution

| Client | Distribution identity | Connection |
| --- | --- | --- |
| CLI | `agentstratum` executable | API Endpoint; named Profiles supported |
| Coding Agents | `agentstratum-coding-agents` npm tarball | One default API connection for hooks, native tools and local MCP adapter |
| Agent Plugin | `agentstratum` plugin | One default remote MCP connection |
| Claude Code plugin | `agentstratum-memory` plugin; `agentstratum-claude-code` archive | One default API connection for hooks and local MCP adapter |

Only these clients are included in the public release scope. Server packages/images, local engines, local Web console packages, SDKs and Helm Charts are excluded. The operator deploys the hosted service separately; its source remains in this repository.

Huawei Cloud public download resources and the production domain are pending. The release workflow builds reviewable client artifacts only; it does not publish to npm, PyPI, container registries or a customer download host.

## Connect

Install the approved client artifact, then copy your own endpoint and credential from the console. Download addresses and service addresses are separate. Packages contain neither customer endpoints nor credentials.

For the CLI:

```bash
agentstratum profile create work --api-url "$AGENTSTRATUM_API_URL" --api-key "$AGENTSTRATUM_API_KEY"
agentstratum -p work bank list
```

There is no implicit localhost endpoint or local Web installer. Missing endpoint configuration produces an actionable error.

For agent integrations, see [Coding Agents](hindsight-integrations/coding-agents/README.md), [Agent Plugin](hindsight-integrations/agent-plugin/README.md) and [Claude Code](hindsight-integrations/claude-code/README.md). Standard Agent Plugin supplies Skills and MCP; automatic lifecycle hooks are provided by the other integrations where supported by the host.

## Delivery status

[Client distribution contract](docs/hosted-single-tenant/module-delivery/M2/CLIENT-DISTRIBUTION.md) records artifact paths, installation, validation and remaining publication decisions. [Issue #2](https://github.com/RSIXDB/hindsight/issues/2) and [PR #3](https://github.com/RSIXDB/hindsight/pull/3) track implementation and acceptance. A prepared artifact is not a published or production-validated release.

## Development and attribution

See [CLAUDE.md](CLAUDE.md) for repository development instructions. This project derives from Hindsight; upstream attribution and licensing remain in [LICENSE](LICENSE). Internal directory and SDK names are retained where they are outside the public branding boundary.
