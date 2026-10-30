# contextbase

Agent memory delivered as a hosted service. Each customer connects using their own API Endpoint, MCP Endpoint and credential from the console.

## Client distribution

| Client             | Distribution identity                                          | Connection                                                               |
| ------------------ | -------------------------------------------------------------- | ------------------------------------------------------------------------ |
| CLI                | `contextbase` executable                                       | API Endpoint; named Profiles supported                                   |
| Coding Agents      | `contextbase-coding-agents` npm tarball                        | One default API connection for hooks, native tools and local MCP adapter |
| Agent Plugin       | `contextbase` plugin                                           | One default remote MCP connection                                        |
| Claude Code plugin | `contextbase-memory` plugin; `contextbase-claude-code` archive | One default API connection for hooks and local MCP adapter               |

Python (`contextbase-client`, import `contextbase_client`) and Node.js (`contextbase-client`, `ContextBaseClient`) SDKs are also built as downloadable artifacts. See the [Python SDK](hindsight-clients/python/README.md) and [Node.js SDK](hindsight-clients/typescript/README.md). Server packages/images, local engines, local Web console packages, Go/Rust SDKs and Helm Charts are excluded. The operator deploys the hosted service separately; its source remains in this repository.

Public distribution uses Huawei Cloud OBS + CDN; Coding Agents installs from an explicit `.tgz` URL with npm. The actual resources and production download domain are pending. The release workflow builds reviewable client artifacts only; it does not publish to npm, PyPI, container registries or a customer download host.

## Connect

Install the approved client artifact, then copy your own endpoint and credential from the console. Download addresses and service addresses are separate. Packages contain neither customer endpoints nor credentials.

For the CLI:

```bash
contextbase profile create work --api-url "$CONTEXTBASE_API_URL" --api-key "$CONTEXTBASE_API_KEY"
contextbase -p work bank list
```

The standalone CLI installer is [scripts/install-contextbase.sh](scripts/install-contextbase.sh). Supply the approved HTTPS download root and an explicit version; it verifies SHA-256 before replacing the binary. There is no implicit localhost endpoint or local Web installer. Missing endpoint configuration produces an actionable error.

For agent integrations, see [Coding Agents](hindsight-integrations/coding-agents/README.md), [Agent Plugin](hindsight-integrations/agent-plugin/README.md) and [Claude Code](hindsight-integrations/claude-code/README.md). Standard Agent Plugin supplies Skills and MCP; automatic lifecycle hooks are provided by the other integrations where supported by the host.

## Delivery status

[Client distribution contract](docs/hosted-single-tenant/module-delivery/M2/CLIENT-DISTRIBUTION.md) records artifact paths, installation, validation and remaining publication decisions. [Issue #2](https://github.com/RSIXDB/hindsight/issues/2) and [PR #3](https://github.com/RSIXDB/hindsight/pull/3) track implementation and acceptance. A prepared artifact is not a published or production-validated release.

## Development and attribution

ContextDB service operators and contributors: start with the [extension guide](hindsight-extensions/contextdb-service/README.md#reading-order) for the reading order, deployment, administrator usage and design references.

See [CLAUDE.md](CLAUDE.md) for repository development instructions. This project derives from Hindsight; upstream attribution and licensing remain in [LICENSE](LICENSE). Internal directory names remain repository implementation details. Python and Node.js SDK package names and public imports use ContextBase.
