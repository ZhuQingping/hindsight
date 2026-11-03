# AGENTS.md

See [CLAUDE.md](./CLAUDE.md) for project documentation and coding conventions.

## Local ContextBase startup

Use [the local startup guide](hindsight-extensions/contextdb-service/docs/deployment-local.md)
for API, the embedded Worker, and the management UI. It is the single startup
reference for native Windows PowerShell and Linux Bash, including authentication
and persistent state. Package-level engine/embedded SDK quick starts describe
other entrypoints; use the linked guide for the ContextBase service.

## Shared maintenance skills

- When the user explicitly invokes `$hindsight-upstream-sync`, read
  [.agents/skills/hindsight-upstream-sync/SKILL.md](.agents/skills/hindsight-upstream-sync/SKILL.md).
  Team usage and repository contracts: [docs/upstream-sync/MAINTENANCE.md](docs/upstream-sync/MAINTENANCE.md).
  Do not automatically invoke it for ordinary development or source review.
