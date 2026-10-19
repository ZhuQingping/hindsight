# Independent review — AgentStratum brand/UI branch

Reviewer: Codex independent review agent `/root/independent_review`, separate from the implementation/fix owner. Date: 2026-10-18.

## Reviewed candidate and method

- Base: `f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`.
- Immutable initial review HEAD: `9341d473c75bc647b0cda3fadb4ac697390a8152`, branch `product/agentstratum-brand-ui-20261016`, draft PR #5.
- Initial worktree was clean. Subsequent fix-owner edits are **not** silently included in this initial verdict; findings below refer to the immutable HEAD and its line numbers.
- Reviewed the complete branch path/diff inventory (562 paths, including 549 source/config/test paths), all handwritten changes, and generated API structural differences. Read `AGENTS.md` → `CLAUDE.md` → `.claude/skills/code-review/SKILL.md`, control-plane `AGENTS.md`, relevant installed Next 16 Proxy/basePath guidance, and the branch PLAN/DESIGN/ACCEPTANCE/SOURCE-MAP. Prior implementation/self-review PASS conclusions were not adopted as review evidence.
- Source-only review. No lint, build, test suite, browser, server, database, generator, network deployment, or heavyweight command was launched by this reviewer. Only static reads/searches, Git comparisons, and lightweight JSON/text comparisons were executed. The fix owner must run verification through the unique shared bounded runner/resource lock.

## Findings, ordered by severity

### R1 — P2 — Operation archive download bypasses stale-tab rejection

Location: `hindsight-control-plane/src/components/bank-operations-view.tsx:961` (through line 974); `hindsight-control-plane/src/lib/product-guard.ts:7`.

The operation-detail Download button creates a normal anchor to `/api/files/download?path=…`. Unlike the other browser data calls, this request never goes through `productFetch` and carries no `X-Product-Name`. The guard checks staleness only when this header is present. After both services restart with a different valid name, an old, still-authenticated tab therefore forwards the archive download successfully. This violates the newly introduced stale-tab contract/A06; the session check itself still runs.

Minimum fix: fetch the archive through `productFetch`, reject non-success responses before saving, and download the successful Blob through an object URL. Preserve the rendered tab identity rather than a shared cookie.

Required regression: exercise the **actual operation-detail Download button** in an old tab, change both running product names, and assert a 409 response and zero native file-download calls. Header-only proxy tests cannot detect this entrypoint gap. Reviewer execution: `NOT_RUN`.

### R2 — P2 — Regeneration breaks existing Go SDK types without an API schema change

Locations: `hindsight-clients/go/model_memory_unit_list_item.go:55`, `hindsight-clients/go/model_bank_template_config.go:48`, `hindsight-clients/go/model_mental_model_delta_operations.go:23`; corresponding Python model fields in `models/{memory_unit_list_item,bank_template_config,mental_model_delta_operations}.py`.

`SourceMemoryIds` and its getter/setter change from `[]string` to `[]*string`. `ObservationScopeLimits`, `Applied`, and `Skipped` similarly change from slices of maps to slices of map pointers. Existing consumers such as `item.SetSourceMemoryIds([]string{"id"})` no longer compile. Python also acquires unexpected nullable array items in the same three existing models. These are executable public-type changes, not generated comment churn.

Independent JSON comparison confirms every pre-existing OpenAPI path and component schema is unchanged. `MemoryUnitListItem.source_memory_ids.items` is still non-nullable `{"type":"string"}`. Thus neither the new naming endpoint nor an intended schema change explains the SDK break; Go compile `NOT_RUN` cannot make it acceptable.

Minimum fix: correct the generation/adapter path, regenerate from the branch's final native specification, and preserve all pre-existing public model types. Do not merely restore files while retaining a generator that reproduces the defect.

Required regression: compare all existing generated model declarations/signatures with the baseline, allowing only intentional additive Product API changes and naming comments; where a toolchain is available, compile a consumer using the old setter/field signatures. Verify Python rejects null elements for previously non-null item schemas. Reviewer execution: `NOT_RUN` (the structural/signature differences themselves were statically verified).

### R3 — P2 — New Connect chooser stops after the first Workspace page

Location: `hindsight-control-plane/src/components/connect-bank-chooser.tsx:10` and `:28`.

The chooser renders `bankInfos`, which the existing provider loads 50 at a time, but never consumes `hasMoreBanks`, `totalBanks`, or `loadMoreBanks`. There is no paging control or truncation indicator. With more than 50 Workspaces, later entries cannot be browsed from this new picker. Server search is a substring match ordered by activity; it does not guarantee that an old short-ID Workspace appears in the first 50 matches. The existing header selector already supports full pagination over the same provider.

Minimum fix: add bounded paging/load-more with the loading/end state, preserving server-side search.

Required regression: more than 50 Workspaces, including a search with more than one page of results; load and select a later-page entry using the Connect chooser. Reviewer execution: `NOT_RUN`.

### R4 — P2 — Connect chooser displays an empty query while retaining a filtered list

Location: `hindsight-control-plane/src/components/connect-bank-chooser.tsx:11` and `:20`; persistent `BankProvider` search state in `hindsight-control-plane/src/lib/bank-context.tsx:95`.

The chooser initializes its own input to `""`, but its list comes from persistent `BankProvider.bankSearch/bankInfos`. Search for `abc`, select a Workspace, then choose Change Workspace: the chooser remounts with an empty input while the provider still holds only the `abc` matches. The user sees an apparently unfiltered, incomplete list. Opening/searching the shared header selector can likewise change the list without updating the chooser's input.

Minimum fix: make the displayed query agree with the provider query (or explicitly reset and reload both together on mount), handling the header-selector interaction too.

Required regression: search → select → Change Workspace, and changing the shared search from the header while the chooser is mounted; assert the input and list describe the same query. Reviewer execution: `NOT_RUN`.

### R5 — P3 — Workspace IDs `guide` and `connect` hide the Add Document action

Location: `hindsight-control-plane/src/components/bank-selector.tsx:110` and `:797`.

Resource-page detection uses `pathname.endsWith("/guide")` / `endsWith("/connect")`. Ordinary native routes `/banks/guide` and `/banks/connect` therefore count as resource pages, hiding the header Add Document action on their home/memory views. The document view's own Add button remains available, so this is a limited UI regression rather than complete loss of retention.

Minimum fix: strip the configured base path and compare the complete app pathname with `/guide` or `/connect`.

Required regression: both reserved-looking Workspace IDs, ordinary IDs, actual resource pages, and a configured base path. Reviewer execution: `NOT_RUN`.

## Other reviewed boundaries

- No source changes to native engine, Worker, migrations, authorization extensions, or Hook integrations appeared in the initial candidate. No own multi-user/multi-key/workspace-schema implementation was found in the source diff.
- Existing OpenAPI paths/schemas compare structurally identical; `/product-config` and `ProductConfig` are the sole additions. This is a scope-purity check, not SDK compatibility proof (R2).
- API/MCP handwritten changes are confined to deployment naming, API metadata/default observability service name, and the non-secret no-store configuration endpoint. SDK/CLI packages, bank identifiers, native tool identifiers, and routes retain their protocol identity.
- Reviewed session creation/verification/revocation, fail-closed configuration, origin/host checks, base-path cookie namespace, public auth diagnostic exceptions, product mismatch/unavailable branches, file-path canonicalization, storage-key adaptation, multipart/binary transfer paths, localized errors/messages, URL-state language switching, graph escaping/render lifecycle/export changes, and retained native navigation/features. No additional confirmed finding is asserted for these areas.
- Existing baseline defects were not promoted to branch regressions. The absence of a finding is a static-review conclusion, not live security, browser, performance, or production proof.

## Initial independent judgment

`CHANGES_REQUIRED` for the immutable initial HEAD: R1–R4 need correction and regression coverage; R5 is a small confirmed regression worth fixing alongside them. No P0/P1 finding was established. The implementation report's `CODE_REVIEW_CLOSED` cannot substitute for closing these independent findings.

Fix re-review and actual bounded verification results must be recorded separately below before changing this judgment. The reviewer has not modified source, the index, commits, other worktrees, or runtime resources.

## Fix re-review

Initial findings above remain attached to `9341d473c75bc647b0cda3fadb4ac697390a8152` even after fixes.

### Working-tree candidate: first static pass

The fix owner supplied an uncommitted candidate for a separate review. Static inspection confirms:

- R1 now routes the actual operation-detail Download action through `productFetch`, checks success before Blob saving, retains a visible error, and disables the button during download. Its component regression exercises this actual action and asserts the rendered tab header, base path, success/error branches, and no saved error response.
- R3 now exposes the provider's bounded `loadMoreBanks`, count, loading, and end states. The regression mounts the real `BankProvider` and walks both the initial list and server search through 61 results.
- R4 now renders `bankSearch` from the same provider as the result list. Its regression covers remount after selection and externally changing the shared search.
- R5 now compares the complete app path after `stripBasePath`. Its regression covers normal routes, both `guide`/`connect` Workspace IDs, actual resource pages, and both empty/configured base paths.
- The reviewer independently read `runs/review-unit-third.log`: 3 component files / 6 tests passed. This is fix-owner-run bounded evidence, not a new test execution by the reviewer. Final full-suite/build/browser gates remain pending.
- R2's generation fix prepares a private input for Python/Go only, leaving the published native spec and Rust/TypeScript input unchanged. It adds explicit non-nullability only to bare string/free-form-object array items and preserves explicit nullable items, references, and compositions. The all-model/request baseline fixture and Python validation regressions were inspected; final regenerated output, fixture provenance/coverage, and actual test results remain pending before closure.

R1 sibling boundary: unchanged native inline-attachment `<a>`/`<img>` requests do not carry the tab product-name header. This is not recorded as an independently introduced baseline-component defect. However, final DESIGN/ACCEPTANCE/RESULT wording must explicitly restrict stale-tab protection to the adapted API/archive requests carrying the tab identity, and record native read-only attachment behavior as retained baseline behavior. A statement claiming every browser file/resource request is stale-guarded would remain unsupported.

Current judgment: fixes are statically responsive; final finding closure and verification judgment are pending. No dynamic gate has been closed by this intermediate review.

### R2 closure and final static candidate

Reviewed source snapshot: 558 non-documentation paths, sorted candidate-map SHA-256 `e0680fc955f976278832fc810a0dbf91e7c8f37e5132c478df47e0ba8d1d84e7` (`runs/static-review-result.json`). The reviewer independently recomputed this digest and all current file hashes; there were no mismatches.

**R2: CLOSED.** Beyond inspecting the implementation and supplied reports, the reviewer independently re-parsed Git baseline and current sources using the guard's declaration extractor (a lightweight static comparison, not test/generator execution):

- All 430 existing Python/Go model/API source files are covered; the fixture additionally includes the two generated Python `__init__.py` files (432 paths total).
- Every fixture digest matches `git show f51b165a…:<path>`; every current candidate digest matches that independently verified fixture.
- The original `9341d473…` candidate fails exactly the six reported Go/Python model files. The guard detects the original defect rather than blessing a post-fix fixture.
- `runs/review-final-extra.log` records 6 pytest passes: full baseline declarations, preparation boundaries, and four null-item regressions. The latter now first validate an otherwise-valid model and assert the rejected element's exact `(field, 0)` location.
- `runs/api-generation-review-r2d/result.json` records successful Python/TypeScript/Go regeneration with the pinned 7.10.0 jar. `runs/repeat-generation-review-result.json` records a second generation with zero changes across 566 tracked SDK paths; the reviewer independently checked that every reported final SDK hash still matches disk.
- The new `.github/workflows/test.yml` conditions run `test-dev` for Python/Go client changes in addition to existing core/dev/CI triggers. The generation preparation is shared by both Python and Go Docker inputs, with cleanup, and leaves the native published JSON specification/Rust/TypeScript input unchanged.

Go/Rust compilation remains `NOT_RUN_NO_TOOLCHAIN`. R2 closure rests on corrected public declarations, targeted Python validation, and repeatable generation; it does not assert a compiler run that did not happen.

**R3/R4/R5: CLOSED.** In addition to the six component regressions already reviewed, `runs/runtime-c10/result.json` independently records a 61-Workspace server search, initial 50-result page, loading/selecting an entry absent from page one, Change Workspace preserving the visible query, and Add Document controls for actual `guide`/`connect` bank IDs under `/brand-ui`. The reviewer inspected the browser assertions behind these checks. The overall c10 run remains **FAIL** because its later operation-list locator was wrong; that failure is preserved and does not negate the preceding completed checks or close R1.

Final static verification evidence independently read: `runs/verify-review-20261018-result.json` plus corresponding logs record frontend 354 tests across 58 files, TypeScript/SDK checks, serial repository lint, and production build passing. That same result retains c09's failed runtime validator. Remote CI and a full successful final runtime are not inferred from these local passes.

DESIGN §4.2 and ACCEPTANCE now explicitly retain the native read-only inline-attachment exception, so the R1 sibling scope clarification is satisfied. **R1 remains OPEN for the actual successful-download/old-tab-rejection browser story in c11; no overall final acceptance is asserted here.**

### Final independent closure

Final reviewed source commit: **`14c2d60eacf9be3e67093f374082eb4fbda3ba39`**. The 558-path source manifest remains **`e0680fc955f976278832fc810a0dbf91e7c8f37e5132c478df47e0ba8d1d84e7`**. The reviewer checked the current source map again after the completed run: no file drift. Documentation-only finalization does not change this source identity.

**R1: CLOSED.** The successful final run is `runs/runtime-c12`, with the exact executed harness frozen as `harness.py`. The reviewer inspected the real browser input-event chain and observer implementation, the operation-tab JSON records, the refusal screenshot, and the final frozen native-request log:

- The completed native **Export Workspace** operation's real Download button sends one same-origin GET carrying `X-Product-Name: agentstratum`, returns HTTP 200, and saves a native ZIP whose CRC validation succeeds.
- After both services restart with `contextdb`, the same existing tab's same Download button sends one further GET carrying the original `agentstratum` header and receives HTTP 409. It displays `PRODUCT_NAME_STALE`; it adds no native file request and no saved ZIP. There is no automatic replay.
- `operation-tab-requests.json` and `operation-tab-responses.json` contain exactly these two archive requests/responses, in order (200 then 409). The observer records requests before forwarding. The frozen `forwarded-native-requests.json` contains the two expected earlier native file reads (the transfer story and actual successful button); no third file read was forwarded for the refused old-tab action.
- Evidence: `runtime-c12/{result.json,harness.py,operation-tab-requests.json,operation-tab-responses.json,forwarded-native-requests.json,actual-operation-old-tab-refused.png}`. These are all under the main repository's `.local/product-brand-ui/runs/` directory.

The reviewer independently recalculated the production artifact digest **`ce68572d2ae61a4bd7eb9bd89781a9e833cb5c7082da2d0e2e8fb93713c84514`** from its 825 recorded files and checked every current artifact file: no drift. c12 tests both runtime names against this same artifact, including actual MCP initialize/get-bank, retains the native identifier contracts, and completes the published Python SDK story (2 passed in `runtime-c12/sdk-story.log`).

`runtime-c12/result.json` is now **PASS**, including the completed earlier UI/transfer/chooser/language checks, mismatch/offline refusal, logout and restart revocation. Its cleanup records all owned child processes exited and PostgreSQL stopped with its data preserved. `verify-review-rest3-result.json` records native-c12, blocking knip, advisory checks, and extra style checks all exiting 0. The outer `review-verification-rest3.log.resources.json` records exit 0, serial execution, a 3 GiB hard memory limit, CPU affinity 0–1, and explicitly **no kernel-enforced 1.5-core CPU quota**. The reviewer did not launch or modify these resources.

Earlier c09/c10/c11 runtime-validator failures remain recorded failures; c12 corrects the validator's actual operation location/type selection and supplies the completed proof. Their results are not rewritten as passes.

**Final judgment: `PASS_INDEPENDENT_CODE_REVIEW / ALL_R1_R5_CLOSED`. No unresolved Must fix finding remains within this branch's agreed scope.** R2–R5 closure above remains valid. The retained native read-only inline-attachment exception is explicit; this is not universal browser-resource stale-tab protection. Go/Rust compilation, remote CI, real-model quality, production deployment, and human product acceptance remain outside the verified result (`NOT_RUN` or not claimed as applicable). Main-branch merge is not part of this review.
