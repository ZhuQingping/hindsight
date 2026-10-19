# Independent integration review

Reviewer: Codex `/root/independent_review`, independent of the implementation owner. Date: 2026-10-19. This reviewer writes only this report; no source/index/ref/runtime changes or heavyweight checks were performed.

## Scope and reviewed inputs

- Accepted UI branch input: `b799f721f58e44b27a59cbabff6e8e1f32f030a6` (previous source `14c2d60ea`). Its earlier acceptance is historical evidence, not an integration PASS.
- Colleague PR #3 net input: `fd69ec9bf50ce97867ff35ee40eb2e71b356586d..2885dd33b9a7663b3dbb15c8a394ac60390bbf47`, 10 commits / 405 net paths. The incorrect earlier `74b522` starting point was not used.
- Integration replay HEAD: `a5954a0ff`; branch `integration/agentstratum-brand-ui-clients-20261019`, isolated integration worktree. Initial review also covers its uncommitted D1 runtime-name/health/Connect changes and SDK regeneration. Findings refer to this initial candidate, before the owner's review fixes.
- Read PLAN/PROGRESS and the imported client-distribution contract. Reviewed source path inventory/diffs across branding, API/MCP/error/log/worker boundaries, CLI connection/profile/filesystem behavior, client/plugin entrypoints/installers/distribution/CI, and the accepted UI's touched protection paths. No prior/self-review PASS conclusion was adopted.
- D1 authority: deployment UI/API/OpenAPI/MCP/runtime display names come from `contextdb_name`; installed commands/packages/config namespaces/telemetry and other protocol identifiers remain fixed `agentstratum` where specified. D2 explicitly permits the colleague's scoped engine/worker branding/error/log changes. The former UI-only requirement that all engine files be byte-identical to main is **not** imposed on this integration.
- Own multi-user/multi-key/access/schema-isolation work and the old hosted branch's additional 33 commits remain excluded. Static inspection found no changes to the excluded authorization extensions or migrations. Git merge-base remains `b799f721…`; all 10 replayed commits retain `cherry picked from` provenance.

## Initial findings

### I1 — P2 — Claude Code/Codex installers delete an externally managed same-name MCP server

Locations: `hindsight-integrations/coding-agents/src/installer.ts:597`, `:631`, `:675`, `:688`, `:712` (initial candidate).

Claude Code install/uninstall unconditionally removes the user-scope MCP registration named `agentstratum`. Codex install/uninstall strips the same-name TOML table without checking its command/URL. A user can already have a native remote MCP connection under this exact name (including the console's default-name connection example); installing Coding Agents destroys its URL/credential registration and replaces it with this plugin's stdio server. Uninstall can then remove that registration outright.

The imported PR adds `preserveMcpEntry`/`isOurMcpEntry` precisely because a name is not ownership, but applies this protection only to six JSON-host siblings. The new family test enumerates those six and omits Claude Code/Codex. This is a concrete integration collision and incomplete sibling protection, not a hypothetical namespace concern.

Minimum fix: check actual user-scope Claude configuration and parsed Codex MCP data using the shared script-ownership contract; replace/remove only plugin-owned registrations. Preserve an external same-name server and give configuration guidance. Preserve idempotent updates when the plugin's own installed path changes.

Required regressions: both install and uninstall for external HTTP/stdio same-name registrations, old/current owned script locations, and native registration preservation across repeated installation. Use private fixtures, never actual user configuration. Reviewer execution: `NOT_RUN`.

### I2 — P2 — Connect still derives MCP Endpoint from API Endpoint

Location: `hindsight-control-plane/src/app/[locale]/connect/page.tsx:24` (initial candidate).

The existing UI snippet constructs `<API_BASE_URL>/mcp/<encoded-bank>/`. The newly accepted client-distribution contract explicitly treats API Endpoint and complete MCP Endpoint as independent and forbids guessing `/mcp`. API/MCP behind separate gateways or path prefixes therefore produce an incorrect copied connection example after integration, despite the Git merge succeeding.

Minimum fix: show an independent, complete `<MCP_ENDPOINT>` placeholder (no new management endpoint is required for this repair). Preserve the selected bank through a supported native bank header or an explicitly provided bank-scoped endpoint. Keep the configured client/protocol identity fixed according to D1, while the native serverInfo name stays dynamic.

Required regression: inspect/render the actual Connect examples for two deployment names and a special-character bank ID; assert independent API/MCP placeholders, selected bank routing, and no API-derived MCP URL. Reviewer execution: `NOT_RUN`.

### I3 — P3 — Runtime startup display still uses the fixed distribution name

Locations: `hindsight-api-slim/hindsight_api/banner.py:50`, `:89`.

`print_banner` and `print_startup_info` read the fixed `PRODUCT_NAME`, so a `contextdb` deployment still prints `agentstratum` and `Starting agentstratum API…`. D1 makes runtime service display names dynamic; these are display messages rather than command/package/protocol tokens. Other D1 fixes already make API/MCP/health/observability service names dynamic.

Minimum fix: derive these two runtime display strings from `product_config().contextdb_name`; leave installed command names and protocol keys fixed. Alternatively explicitly document a user-approved distinction if operator banners are deliberately distribution identity; the current plan records no such exception.

Required regression: both legal names in actual formatted startup output after stripping ANSI escapes. Reviewer execution: `NOT_RUN`.

### I4 — P2 — Invalid remote configuration still rejects persistent-host initialization before the fail-open boundary

Locations: `hindsight-integrations/coding-agents/src/core/config.ts:879`; `src/harness/plugin-entry.ts:43`; same shared builder consumed by `src/{cline,dsh}.ts` and `src/harness/{pi-extension,opencode2}.ts`.

`loadConfig` throws `RemoteConnectionError` for `serverMode=daemon` or a non-empty invalid endpoint such as `file:///tmp/api`. The real persistent plugin entrypoint calls `resolveHostMemory` before any catch, so its async initialization rejects before creating `RuntimeCore`. The subsequent `seedIfCold` fail-open catch cannot contain this error: it is never reached. This can prevent memory-plugin initialization and propagate a configuration failure into the host's startup path.

The added real-entrypoint test covers only an empty endpoint, which `loadConfig` deliberately allows through. RuntimeCore tests for invalid/daemon settings construct a core with `resolveConfig` directly, bypassing the throwing loader. Thus those tests do not cover the failing composition even when all pass.

Minimum fix: contain remote-configuration errors at a shared persistent-host construction boundary, return an inert runtime/plugin with actionable diagnostics, and leave invalid configuration unable to send requests or start a local engine. Cover every consumer of the shared builder; retain installer validation and useful tool errors rather than silently accepting invalid endpoints.

Required regressions: real entrypoint/setup paths with empty, malformed/non-HTTP, and daemon configurations; explicit bank ID to avoid unrelated Git probing; assert no initialization rejection, no request/local-engine spawn, and a configuration notice. A family guard should prevent a sibling from missing this boundary. Reviewer execution: `NOT_RUN`.

## Other independently checked boundaries

- Lightweight source parsing against the existing fixture finds **zero declaration mismatches across all 432 baseline Python/Go SDK model/API paths**. This is static signature evidence, not a Go/Rust compile claim.
- Compared regenerated OpenAPI to `b799f721`: the only existing-path/schema differences are descriptions. Removing `description` fields makes the entire specification structurally identical. Native request paths, field types, models, operation IDs, and additive product-config contract are preserved at this review point.
- Runtime-name helper changes preserve fixed webhook/reranker headers and telemetry instrument identifiers. Unknown internal failures are classified before public response/task persistence, while original diagnostics remain in operator logs. Reviewed customer-data transport paths do not apply a brand-keyword replacement to response bodies/files/customer identifiers.
- The accepted UI's proxy/session/product-fetch/download/pagination/locale protections are not replaced by colleague implementations. Its touched session/i18n files have limited error/legacy-cookie wording changes; integration health now explicitly checks failed SDK results instead of treating a non-throwing error as connected.
- Client distribution remains manual candidate construction, explicit remote connection, and no customer local-engine auto-start. Internal local-engine source remains present by design. Cloud publication, real host behavior, and full multi-platform execution are separate verification boundaries.
- The implementation owner reported ongoing serial bounded validation, including failures caused by test temporary-directory ancestry and incomplete test namespaces. These failures are not accepted as passes, and the review does not alter product probes or skip cases to accommodate the environment.

## Initial judgment and verification boundary

`CHANGES_REQUIRED`: I1, I2, and I4 are confirmed P2 findings; I3 is a confirmed P3 runtime-display inconsistency. No P0/P1 is established. Earlier UI acceptance and imported PR reports do not close these integration findings.

This initial review did not run lint/build/unit/browser/API/database/generator/toolchain checks. The implementation owner must execute them through the unique shared bounded runner, retain failures, bind final source/artifact hashes, and provide evidence for a separate closure review.

## Fix re-review

Initial findings remain attached to the replay/D1 candidate described above even after later repairs.

### First repair-candidate review

The reviewer separately inspected the implementation owner's uncommitted repair candidate and the new regression tests; no additional Must fix was established in that inspection.

- **I1, statically responsive; latest test run pending.** Claude inspects actual user-scope registration ownership before removing/adding; an unreadable or foreign same-name registration is preserved. Codex parses TOML before removing an owned table; an unsupported textual form or parse failure preserves the file. Qwen now inspects its user configuration and removes in explicit user scope only. Factory, WorkBuddy, and CodeBuddy also use the shared preservation gate. The test family now covers 11 JSON-host storage locations plus dedicated Codex TOML cases; foreign HTTP/independent stdio registrations, moved owned scripts, malformed Claude/Codex/Qwen files, repeated installation, and uninstall are represented. Test CLI adapters use private files and never execute real user host configuration. The most recent stdio/repeated-install additions postdate unit-07 and are not treated as already executed.
- **I2, source/unit fix accepted.** Connect now uses a complete `<MCP_ENDPOINT>` independently of the API address and fixes the local configured alias to `agentstratum`. The administrator must provide the complete endpoint scoped to the selected Workspace. This avoids both guessing a route from API Endpoint and sending a raw Unicode bank ID in an HTTP header. The actual async page component regression parses the rendered MCP JSON under two runtime names and preserves encoded REST/SDK handling for a special-character bank ID.
- **I3, source/unit fix accepted.** API banner/startup and Worker startup display use the runtime deployment name. The regression checks actual API output with ANSI sequences stripped, under two legal names. Fixed command/package/protocol tokens remain fixed.
- **I4, source/unit fix accepted.** `resolveHostConfig` catches only `RemoteConnectionError` at the common persistent-host factory, before bank derivation, logs configuration guidance, and returns an explicitly disabled result. The strict installer/CLI loader remains strict. Real plugin-entrypoint negative cases cover malformed/non-HTTP endpoints and daemon mode, asserting no rejection, no fetch and no child-process function calls. All persistent builder consumers use the shared boundary and honor the disabled exit; a family guard checks that they do not call the throwing raw loader directly.

The reviewer independently read `runs/integration-20261019/unit-07/result.json` and its check logs: frontend 379 passed; Coding Agents 83 files / 1,362 passed / 6 skipped plus build/types passed; scoped API 303 passed / 71 skipped / 1 deselected; Claude Code 226 passed; installer 7 passed / 1 skipped. API skips include unavailable local-ML fixtures; the installer skip is the actual tarball-over-HTTPS story, to run after packaging. These are bounded fix-owner executions, not reviewer-launched tests. The test temporary-directory/namespace failures remain earlier recorded failures, not silently converted into passes.

Overall integration remains **verification pending**. The latest focused installer tests, final source identity, SDK/generator/compiler checks, production build, package/install story, and actual API/MCP/browser evidence must be checked before final closure. No production, cloud publication, real-host or remote-CI acceptance is inferred from this intermediate review.

### Fixed-source code-review closure — `5d350568ae3d7537e452999cb6d0fae86b64563b`

The reviewer separately inspected repair commits `2b777bc3f23e13813f90c03bf0ab1845e9387ce0` and `5d350568ae3d7537e452999cb6d0fae86b64563b`, including the Rust changes discovered by actual compilation/native testing after the initial review.

**I1–I4: CLOSED. No unresolved source Must fix remains at this checkpoint.**

- I1's final focused installer/shared-host/real-entrypoint run is recorded in `checks-02/coding-agents-focused.log`: 267 passed / 2 skipped, with type checking passed. The reviewer read the log and final installed-code/test changes. External same-name registration preservation, scoped deletion, moved owned scripts, malformed configurations, independent stdio entries, and repeated install/uninstall are represented. No real user's host registration was used.
- I2's independent complete Workspace MCP Endpoint/fixed alias is exercised by both the actual Connect component regression and `runtime-04`'s browser DOM assertions. The packaged standard-plugin manifest is also supplied a complete endpoint independently and performs an actual HTTP MCP call against the native API.
- I3's runtime banner/service-name code is dynamic while distribution/protocol identifiers stay fixed. The dual-name native API/MCP/browser run preserves this division on one production artifact.
- I4 is contained at the shared persistent-host construction boundary; invalid non-HTTP/malformed/daemon configurations are tested through the real plugin entrypoint, with zero network/subprocess calls, and covered across the factory consumers. Installer/CLI strict configuration validation remains intact.

Rust-specific review:

- The generated Rust pattern validator references `::regress::Regex`; adding `regress = "0.10"` as a direct runtime dependency fixes the actual compile defect. The committed Rust SDK lock diff adds only that root dependency edge. `build.rs` changes in the repair are formatting, not a different generation algorithm. `checks-04/rust-sdk-unit.log` records the compiled legal/illegal `ContextdbName` schema-deserialization test passing (1 passed; unrelated tests filtered).
- The CLI trigger fix is confined to a request containing a trigger. Its only command consumer first reads the stored trigger and builds the complete overlay. The new branch uses the existing authenticated/user-agent/timeout-configured HTTP client and sends explicit nulls for nullable `refresh_cron` / `tags_match`; it preserves other serialized fields. It builds the endpoint with URL path segments, preserving a configured prefix and encoding IDs. Non-success status and body are retained in the error. Updates without a trigger still use the generated/humanized client path.
- The native trigger regression actually clears both settings and asserts unrelated `keep_trace`/mode values survive. Ordinary `checks-07/rust-cli-tests.log` records 153 executed tests and **25 explicitly ignored live tests**. Separately, `runtime-04/cli-live.log` runs `--ignored` against an explicitly owned API fixture and records **25 passed / 0 ignored**. Tests now use the current compile-time `CARGO_BIN_EXE_agentstratum`, never a PATH/old-target fallback. Earlier compile/fixture/native failures remain failures in their original logs.
- Existing remote CI runs ordinary Cargo tests before starting its API and later runs a CLI smoke script; it does not currently run this explicit 25-test live suite. The result here is local bounded execution, not a claim that remote CI already executes those cases.

The reviewer independently read `runtime-04/result.json`, frozen `harness.py`, client protocol results, browser/operation request-response records, native forwarding records, SDK/CLI logs, and cleanup evidence. The final runtime is **PASS**, with 19 recorded groups: actual native API/MCP plus four client forms, two deployment names on the same production UI artifact, independent MCP endpoint, representative UI/locale/navigation/transfer/paging flows, actual archive Download 200 followed by old-tab 409 with no extra native download/replay/save, session/mismatch/offline/logout/restart boundaries, and 5 published SDK story tests. The Coding Agents built stdio adapter and actual packaged Claude warm launcher call the native API; this does not claim real third-party host-session or cold dependency-install acceptance. All owned API/UI/browser processes exit and the owned PostgreSQL instance is stopped with its data preserved.

Source/artifact binding independently rechecked:

- Commit: `5d350568ae3d7537e452999cb6d0fae86b64563b`.
- `source-checkpoint.json`: 3,314 recorded file hashes, recomputed map SHA-256 **`849aed4404a39482f1acff6dd1ba1880f2cc01aab317f8fea65d85b66b41876a`**, zero live-file drift.
- `SOURCE-MAP.json`: 974 provenance paths, zero live-file drift at review.
- `runtime-04/artifact-manifest.json`: 825 production files; recomputed SHA-256 **`7bb60c91851cc4d621a55293f66a18bc9e9a2c568ffe4717e8dffd4f65e111cb`**, zero current artifact drift.
- `native-runtime-04.log.resources.json`: exit 0, serial shared-runner execution, 3 GiB hard memory limit, CPU affinity 0–1; the requested 1.5-core CPU quota is explicitly **not** kernel enforced. No reviewer-started runtime resources.

Other independently read bounded evidence: unit-07 full frontend/Coding Agents/API/Claude scopes as above; checks-01 lint/blocking knip; checks-05 production build and all 8 HTTPS installer stories with 11 subtests including the actual npm tarball; checks-06 repeat generation (485 checked paths, zero drift), 432 baseline declarations, three Go consumer/marshal tests, manifest and formatting checks. Local-ML/API and system-sqlite skips remain explicitly recorded.

**Checkpoint judgment: `PASS_INDEPENDENT_SOURCE_REVIEW / ALL_I1_I4_CLOSED`.** Linux release candidate/license staging is still running and is not marked complete by this source-review conclusion. Remote GitHub CI, other platform binaries, real third-party host sessions, real-model quality, cloud OBS/CDN publication, and human product acceptance are not claimed. Final delivery documentation, artifact review, draft PR/push, and restored preview remain implementation-owner tasks; this review does not merge main.

### Local release artifacts and preview — supplemental closure

The release-stage evidence has since completed. The reviewer read `release-02/result.json` and actual logs: pinned `cargo-about 0.9.1` installation/version, independent CLI lock/dependency fetch, offline third-party-license generation, optimized default release-profile compilation, 9 release-binary process tests, and staging all exit 0. The failed earlier release-01 attempt (the tool was installed without its CLI feature and produced no executable) remains a recorded failure; it is not counted as a successful release build.

The reviewer independently checked `four-client-candidates/MANIFEST.json`, bound to source `5d350568ae3d7537e452999cb6d0fae86b64563b`:

- All 12 recorded artifact-file SHA-256 values match disk, and all seven entries in the version-local `SHA256SUMS` files independently match their targets.
- The CLI artifact is an actual Linux x86-64 ELF executable; its SHA-256 is **`9e7a3afb3b6e83babb6052628c9aeb99ec1b200b71492ec1c322df3aff4e92f9`**. Its directory includes the repository license, generated third-party licenses, and checksums. This is a Linux-amd64 candidate, not evidence for other platform binaries.
- Both plugin ZIPs pass full ZIP CRC validation and contain licenses. The Coding Agents gzip stream validates through its checksum/footer; its tar archive contains a license, no unsafe absolute/parent paths, and no distributed `daemon-start.js` entrypoint. The installation script is staged with its checksum.
- Source checkpoint remains **`849aed4404a39482f1acff6dd1ba1880f2cc01aab317f8fea65d85b66b41876a`** across 3,314 files; the reviewer rechecked every current source hash with zero drift. Subsequent delivery-document edits do not change the reviewed source checkpoint.

`release-02.log.resources.json` records bounded serial completion with exit 0, a 3 GiB hard memory limit, CPU affinity 0–1, and no kernel-enforced 1.5-core CPU quota. The reviewer did not build, install, execute, or publish these artifacts.

The owner-restored isolated preview has reached **READY** (`preview-01/result.json`) using the same production artifact **`7bb60c91851cc4d621a55293f66a18bc9e9a2c568ffe4717e8dffd4f65e111cb`** and fixed reviewed source. `browser-check.json` records successful Chinese UI rendering and native data requests. `release-cli-native-smoke.json` records a native API bank listing from the actual release binary, with its SHA-256 matching the staged candidate above. The preview uses synthetic data and local declared stubs; it has an owned stop file and a two-hour automatic stop lease. The reviewer did not wait for the lease to expire or claim that this intentionally running preview had been cleaned up.

**Supplemental judgment: `PASS_LOCAL_CANDIDATE_ARTIFACT_REVIEW`. No source Must fix or artifact-integrity finding remains within the reviewed local scope.** This does not claim public release, OBS/CDN upload, remote CI, macOS/arm64 binary acceptance, real third-party host installation/session acceptance, real-model quality, or human product acceptance. Git push/draft PR and final delivery-document completion were still pending at this review point. Main was not merged by this reviewer.
