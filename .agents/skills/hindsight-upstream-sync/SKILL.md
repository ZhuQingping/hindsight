---
name: hindsight-upstream-sync
description: Integrate a pinned official Hindsight release into the ContextBase fork, resolve conflicts while preserving product contracts, and validate the integration. Use when explicitly requested to assess or perform upstream synchronization.
---

# Hindsight upstream sync

Use the selected checkout, not a remembered branch. Read `AGENTS.md`, `CLAUDE.md`,
`docs/upstream-sync/MAINTENANCE.md`, and the current brand definition/identity contract.
Keep assessment-only requests read-only apart from fetched Git objects and explicit reports.

## Pin and assess

Verify origin/upstream URLs, remote target branch, release tag and peeled commit SHA.
Record ours, theirs, merge base, status and active worktrees. Release integration targets
the release commit, not moving upstream/main. Inspect outstanding changes without stashing
or committing someone else's work. Run `scripts/upstream-sync/preflight.py` with explicit
refs. Its merge simulation writes Git objects only; conflict-free does not mean validated.
Read `simulation_clean` and `conflict_paths`: exit zero means the assessment completed,
including when conflicts were found. Select each package's test configuration and explicit
owned server fixtures; do not run server-dependent SDK suites against their localhost defaults.
If the pinned release is already an ancestor of the target, report it as already integrated;
perform only any explicitly requested revalidation instead of opening a duplicate integration.

## Integrate

Create an isolated worktree under the main checkout's `.local/upstream-sync/<run>/` from
the verified target SHA. Keep raw logs there. Commit maintenance setup separately, then
merge the pinned upstream SHA with `--no-ff --no-commit`. Preserve upstream ancestry
through the eventual PR merge; do not squash the integration or rebase shared history.

Resolve semantic changes before generated files. For each substantive conflict record
both intentions, final behavior and checks. Review automatically merged intersections too.
Use the maintained difference register, not blanket ours/theirs or global name replacement.
Regenerate SDK/docs/locks from reconciled sources with the pinned tools. Inspect maintained
wrappers, generator patches, package identities and release destinations separately.
`rerere` is optional; replayed resolutions still need inspection and regression tests.

## Validate and deliver

Use the checkout's existing resource runner and owned test resources where required.
Run affected upstream tests and fork contract checks, plus real API/SDK blackbox stories,
CLI/client builds and relevant UI checks. Review migrations each round; code rollback is
not data rollback. Keep model-backed quality, deployment and unsupported platforms explicitly
NOT_RUN when not exercised. Never inherit prior PASS results onto a new tree.

Follow repository code review requirements, fix implementation findings within the authorized
task, and record scope/limitations. Bind validation to the tested source tree and commands.
Recheck remote target drift before delivery; changed inputs invalidate affected evidence.
Deliver the merge commit and reviewable PR when authorized, leaving main merge and deployment
to the user unless separately requested.

## Resume

Read the run's tracked plan/results and local logs; verify HEAD, MERGE_HEAD, index conflicts,
owned resources and pinned inputs before continuing. Never start a second merge over an
unfinished one or delete a shared lock. Abort only this run's merge if requested; preserve
resolution work first. A clean Git index is an intermediate state, not completion.
