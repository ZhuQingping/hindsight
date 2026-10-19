# ContextBase public identity validation

Date: 2026-10-19. Base: `3f2cd188e5315995622b1d7b947b2b761f068e44`
(main after PR #10, Hindsight v1.0.0).

This replaces the unmerged, closed PR #11 implementation based on `4f7a278`.
The public identity changes were reapplied to the new main and the checks below
were executed again on the resulting sources. Previous validation counts were
not inherited.

## Scope and integration review

Display prose uses `ContextBase`; public machine identities use `contextbase`,
`contextbase_*`, `contextbase-*` and `CONTEXTBASE_*`. The change covers
REST/Web API metadata, MCP registration/tools, Webhook headers, three client
plugin distributions, CLI/configuration/installers, model outbound attribution,
telemetry and dashboards. SDK package/import identities and business API paths
remain unchanged. Customer content, resource IDs and full internal diagnostics
are preserved; old installation aliases and automatic config migration are not
introduced. See [NAMING-MAP.md](NAMING-MAP.md).

The merge review explicitly preserved new-main behavior where edits intersected:

- Coding Agents stays at 0.8.1; API/CLI/local-engine versions stay at 1.0.0.
- Auto-update keeps registry package validation and the new cross-platform
  `spawnNpm` path.
- HTTP requests keep the new signal-owned dispatcher and timeout behavior.
- Local usage recording remains independent of remote write-back being enabled.
- New health probes keep their User-Agent and use the renamed product identity.
- Claude provider JSON repair, tracing and the new-main provider changes remain.
- The integration lockfile checker retains its exact private, development-only
  local-helper exception; its package names and regression fixture now agree
  with `contextbase-coding-agents` / `contextbase-local-engine`.
- Historical upstream integration records remain unchanged. The current
  maintenance difference register points at the new naming contract.

## Verification performed on this base

| Check | Result |
|---|---|
| API identity/product configuration, Webhook HMAC and payload preservation, Prometheus/tracing/logging, provider attribution, Claude tool rounds/errors, Cursor and reranker headers | 148 passed, 6 credential-dependent cases skipped |
| Coding Agents TypeScript check | Passed |
| Coding Agents tests | 1,427 passed, 6 existing opt-in cases skipped; 1 documentation icon case excluded because binary icons were unavailable in this checkout |
| Coding Agents build | ESM bundles and declarations passed |
| Claude Code tests using its declared MCP v1 dependency | 228 passed |
| Web product configuration, health, errors and affected UI consumers | 52 passed |
| CLI installer against local HTTPS artifact fixtures | 7 passed, 1 native-binary case skipped |
| Integration lockfiles | All 8 locally available integration lockfiles passed; policy regression test passed, including rejection of non-private/runtime links |
| Agent Plugin manifest/MCP/skill validation | Passed |
| Brand generator round-trip and identity drift rejection | Passed, 19 targets |
| Brand/skill/docs freshness | Passed |
| OpenAPI generated from the actual application | Exact JSON equality with the checked-in spec, 79 business paths |
| Plugin candidate packaging | ZIPs for contextbase-agent-plugin 1.0.0 and contextbase-claude-code 0.7.6; TGZ for contextbase-coding-agents 0.8.1; manifest identities and all 39 command names checked |
| Changed Python sources | 121 syntax checks; differential Ruff on 120 non-generated files: 19 baseline findings, zero new findings |
| Patch whitespace | Passed |

The API test selection was:
`test_brand_identity_layers.py`, `test_product_config.py`,
`test_public_brand.py`, `test_server_logging.py`,
`test_bank_attribution.py`, `test_claude_code_llm_tool_round.py`,
`test_claude_code_llm_error_result.py`, `test_cursor_llm.py`,
`test_tei_cross_encoder.py`, `test_cohere_cross_encoder.py`, and
`test_litellm_sdk_cross_encoder.py`, run with
`pytest --noconftest -q -o addopts=''`.

Coding Agents ran `npm ci --ignore-scripts --workspaces=false`,
`npm run typecheck`, `npm test -- --exclude src/docs-harness-roster.test.ts`,
and `npm run build`. The roster's three non-image cases were run separately
with `vitest run src/docs-harness-roster.test.ts -t 'lists exactly|names every|gives every'`.

Other checks included `bash scripts/sync-product-brand.sh --check`,
`node scripts/test-brand-generation.mjs`,
`bash scripts/check-integration-lockfiles.sh`,
`python -m unittest discover -s scripts/upstream-sync -p test_lockfile_policy.py`,
`python hindsight-integrations/agent-plugin/validate.py`,
`python hindsight-system-tests/tests/test_client_installation.py`, and
`python scripts/package-client-plugins.py --output <local-candidate-directory>`.

## Limits

- Repository-wide `scripts/hooks/lint.sh` was attempted but stopped during
  dependency sync: the sparse checkout lacks the Python SDK project manifest.
  Differential Ruff is narrower evidence, not a full lint pass.
- No native Rust CLI build, complete database-backed system suite, complete
  documentation build, remote CI run, real-host installation or public CDN
  publication was completed here.
- Candidate archives are local build evidence. Distribution/acceptance work in
  Issue #2 is not closed by this rename.
- Old RESULT/VALIDATION records preserve their original commits and results.

## Review outcome

Manual code review checked branch hygiene, semantic intersections with main,
sender/receiver header agreement, emitted metrics/dashboard queries, plugin
manifests/installers, package versions and generated-file consistency. No
new authentication logic, database migration or SDK method changes were added.
No new must-fix implementation finding remained in this reviewed scope; the
unexecuted gates above remain explicit.
