---
sidebar_position: 6
title: "Coding Agents"
description: "One ContextBase memory plugin for coding agents — per-repo memory banks built automatically from git history and past sessions, injected into the agent as it works."
---

{/* GENERATED from hindsight-integrations/coding-agents/README.md — edit that file, then run
    node hindsight-docs/scripts/sync-coding-agents-doc.mjs */}

import Figure from '@site/src/components/Figure';
import codingAgents from '@site/figures/coding-agents.json';
import CodingAgentsChart from '@site/src/components/CodingAgentsChart';

Long-term project memory for **coding agents**, backed by ContextBase.
One package, several agents: a shared reflect-and-inject core with a thin entry point per agent
(**Claude Code**, **Codex CLI**, **DeepAgents Dcode**, **opencode**, **opencode 2**, **Kilo CLI**, **Cursor CLI**, **GitHub Copilot CLI**, **Grok Build**, **Qwen Code**, **Kimi Code**, **Factory Droid**, **ZCode**, **TraeCode**, **Antigravity CLI**, **Devin CLI**, **Cline CLI**, **pi**, **Prime Agent**, **DeepSeek Harness**, **WorkBuddy**, **CodeBuddy**). Ingestion is fully
automatic after you configure an existing workspace: conversations flow into that workspace as you work.

The premise: most of a real fix is derivable from the code, but the _last mile_ often hinges on a
project-specific decision that isn't in the code at all — a rounding rule, a retry allowlist, a
tie-break policy. Those decisions live in git history and past conversations. This package puts them
in front of the agent at the moment it starts working, and keeps a curated set of **knowledge pages**
(architecture, conventions, in-flight initiatives) that future sessions start from.

<Figure doc={codingAgents} />

## Does it work?

[AMB's sdebench](https://agentmemorybenchmark.ai/dataset/sdebench) is the measurement: a coding
agent over 61 real repository tasks, three runs each, with and without memory.

Accuracy is not what moves — every run solves 60–61 of the 61 either way. These are tasks a good
agent can already do. What memory changes is how much it costs you to get there: how often you have
to stop and correct the agent, and what the tokens cost.

<CodingAgentsChart title="AMB · sdebench" />

| Agent       | Corrections / task | Cost / task         |
| ----------- | ------------------ | ------------------- |
| Claude Code | 0.85 → **0.36**    | $0.445 → **$0.338** |
| Codex CLI   | 1.34 → **0.47**    | $0.577 → **$0.276** |
| opencode    | 1.20 → **0.80**    | $0.634 → **$0.553** |

No memory → with contextbase, mean of 3 runs. Corrections reproduce the labels AMB prints on its own
chart; cost is derived from the same per-run table.

Both numbers move together, and that is the mechanism rather than a coincidence. A correction is a
round trip: the agent guesses a project-specific decision wrong, you stop it, you explain, it redoes
the work. Every one of those costs a turn of tokens and a turn of your attention. Handing the agent
the decision _before_ it starts — the rounding rule, the retry allowlist, the tie-break policy that
was settled in a commit message or a conversation months ago — removes the guess, and the round trip
with it.

## Install

Run these commands from the project directory. Node.js 18 or later is required.
Set `CONTEXTBASE_API_TOKEN` in your environment, then install the integration you use:

```bash
npx @huaweicloud/contextbase-coding-agents@latest install claude-code --bank-id <BANK_ID>
npx @huaweicloud/contextbase-coding-agents@latest install codex --bank-id <BANK_ID>
npx @huaweicloud/contextbase-coding-agents@latest install cursor-cli --bank-id <BANK_ID>
```

`--api-url <API_ENDPOINT>` sets the service address; when omitted, the installer uses
existing configuration or environment variables and prompts if the address is missing.
In scripts or CI without an interactive terminal, provide the address explicitly or through configuration.
`--bank-id <BANK_ID>` saves one existing workspace for every project and agent. Later installs may omit it when `bankId` is already configured (or supplied by `CONTEXTBASE_BANK_ID`). Missing `bankId` stops installation and disables memory at runtime; no workspace ID is generated or inferred from a directory.

Switch the configured workspace without reinstalling:

```bash
npx @huaweicloud/contextbase-coding-agents@latest bank use <BANK_ID>
```

The command preserves the endpoint and token. Restart your agent and its MCP server after switching.
`--project-path <PROJECT_PATH>` selects the directory for project-specific client registration, such as TraeCode; it does not select a workspace and defaults to the current directory.
Restart your agent after installation.

To upgrade, re-run the same `npx @huaweicloud/contextbase-coding-agents@latest install <harness>` command.
Use `@<version>` instead of `@latest` when you need a specific release. The `update` command
only re-stages the package you invoke; it does not fetch a newer release itself.

```bash
npx @huaweicloud/contextbase-coding-agents@latest uninstall claude-code
npx @huaweicloud/contextbase-coding-agents@latest --help
```

`install` requires an explicit target: one or more harness names, or `all` for every
detected agent. Use `stats` to inspect memory usage.

Before installation, copy your API Endpoint and credential from the console. Set `CONTEXTBASE_API_URL` and `CONTEXTBASE_API_TOKEN`, or pass `--api-url` and `--api-token` to `install`. There is no default service address. Installation stops before registering hooks if the endpoint is missing. This package connects to a remote service; it never installs or starts a local engine.

### Connect a service-managed Workspace

Run in the project directory with the API endpoint and a business API key from your service provider:

```bash
export CONTEXTBASE_API_TOKEN='your-business-key'
npm exec --yes --package=@huaweicloud/contextbase-coding-agents@latest -- contextbase-coding-agents install claude-code codex --api-url 'https://api.example.com' --bank-id 'your-bank-id' --project-path '.'
```

Use the actual versioned HTTPS tarball URL. In PowerShell, set
`$env:CONTEXTBASE_API_TOKEN = 'your-business-key'` and use `npm.cmd exec` for the same arguments.
Keep only `claude-code` or `codex` if you use one client. Restart clients after installation;
Codex may also require approval of hooks in its trusted project.

`--bank-id` maps `--project-path` (the current directory by default) to an existing Workspace,
merges other project mappings, and preserves the existing `optInOnly` policy (default: `false`). It does not create a Workspace or grant
permissions. The connection remains shared across the configured projects. A bound Workspace
uses `manageBankConfig: false`, `autoSeed: false`, and `codebaseSurvey: false`: service-owned
configuration and knowledge-page initialization are left to the provider. Session write-back,
retrieval and explicit document ingestion remain available. Do not use an administrator key.
Manual history import and knowledge-page creation require additional server permissions.

Missing or conflicting MCP registrations return a non-zero exit status; follow the reported
instructions and re-run installation. Existing external MCP registrations are preserved.

### Per agent

Same command, only the harness name changes. Run after installing the package globally.

#### Claude Code

```bash
contextbase-coding-agents install claude-code
```

3 hooks in `~/.claude/settings.json`, MCP via `claude mcp add` (user scope), and the companion skill.

#### Codex CLI

```bash
contextbase-coding-agents install codex
```

3 hooks in `~/.codex/hooks.json` plus `[mcp_servers]` in `config.toml` (the installer enables `[features].hooks = true`).

#### DeepAgents Dcode

```bash
contextbase-coding-agents install dcode
```

The installer registers this package as a local marketplace with Dcode, then invokes Dcode's own
`plugin install` command. The package is a native Agent Plugin: its root `plugin.json` contributes the shared skill, the
Hooks V2 `SessionStart`, `UserPromptSubmit`, and `Stop` lifecycle, and the namespaced
`contextbase_*` MCP server. Enable the plugin through Dcode's normal plugin manager; no Dcode config
patcher or compatibility bridge is required.

Dcode namespaces a plugin's MCP tools, so they appear as
`plugin__contextbase-coding-…__contextbase_…` rather than under their bare names — the agent resolves
them from the tool guide either way. In headless runs (`dcode -n`) Dcode allows the read-only
ContextBase tools and gates the two that write (`contextbase_ingest_document`,
`contextbase_capture_initiative`) behind an approval it has no UI for; use the interactive TUI to
capture an initiative or ingest a document. For the same reason the one-time codebase survey runs
under another installed agent's CLI when there is one, exactly as it does for Cursor, Copilot,
Devin, Grok Build, Cline, Kilo and Prime Agent.

#### opencode

```bash
contextbase-coding-agents install opencode
```

A plugin entry in `~/.config/opencode/opencode.json` — native tools, no MCP needed.

#### opencode 2

```bash
contextbase-coding-agents install opencode2
```

opencode v2 (`npm @opencode/cli`) exposes an `opencode2` binary alias **alongside** `opencode` and
rewrote the plugin API, so it is a harness of its own. It writes the same plugin entry to the same
`~/.config/opencode/opencode.json` — the two CLIs share that file, and v1 rejects the whole config
if it sees v2's `plugins` key — and each CLI then loads its own entry point from the one registered
path. So installing either harness wires both, and uninstalling either removes the shared entry.

Two differences from v1, both because of the host: the one-time codebase survey runs under another
installed agent's CLI (v2 plugins cannot define the read-only agent the survey needs), and the seed
banner is written to the plugin log instead of a TUI toast (v2 plugins cannot raise one). Recall,
injection, the native `contextbase_*` tools and session write-back are identical. The companion skill
is identical too, but it is registered in memory through v2's skill API rather than copied into a
skills directory — opencode2 has none of its own, and the two it reads belong to other agents.

#### Kilo CLI

```bash
contextbase-coding-agents install kilo
```

A plugin entry in `~/.config/kilo/kilo.json[c]`.

#### Cursor CLI

```bash
contextbase-coding-agents install cursor-cli
```

Hooks in `~/.cursor/hooks.json`, `~/.cursor/mcp.json`, and the companion skill.

#### GitHub Copilot CLI

```bash
contextbase-coding-agents install copilot-cli
```

`~/.copilot/hooks/`, `mcp-config.json`, and the companion skill.

#### Grok Build

```bash
contextbase-coding-agents install grok-build
```

Native hooks in `~/.grok/hooks/contextbase.json`, MCP in `~/.grok/config.toml`, plus the companion
skill. Grok also runs Claude Code's hooks from `~/.claude/settings.json`; those stay silent inside
Grok, so a machine wired for both hosts records each Grok session once. Grok passes hook context to
the model only from tool hooks, so the session and prompt context arrive with the result of the
agent's first tool call after each prompt (a `PostToolUse` hook).

#### Qwen Code

```bash
contextbase-coding-agents install qwen-code
```

Native hooks in `~/.qwen/settings.json`, plus MCP and the companion skill.

> Qwen's hook `timeout` is in **milliseconds** (its own docs: "Timeout in milliseconds, default
> 60000"), unlike every other supported agent, so the installed values are `30000/30000/60000`.
> Recall fires on genuine submissions only — `UserPromptSubmit` also fires on tool-result
> continuations, so interactive sessions recall once per prompt while headless (`qwen -p`),
> `serve`, SDK and ACP sessions seed and retain but do not recall.

#### Kimi Code

```bash
contextbase-coding-agents install kimi-code
```

Native hooks in `~/.kimi-code/config.toml`, plus MCP in `~/.kimi-code/mcp.json` and the companion skill.
(Hooks and MCP go under `$KIMI_CODE_HOME` instead when it is set.)

> Kimi's SessionStart hook cannot reach the model, so the session briefing is silent there;
> recalled memory arrives on the first prompt instead, as a `<hook_result>` block. Sessions are
> retained from every agent's `wire.jsonl` under the session directory, subagents included.

#### Factory Droid

```bash
contextbase-coding-agents install factory-droid
```

4 hook registrations in `~/.factory/hooks.json` (user scope), including a cancellation-safe
`Notification` write-back, plus a stdio MCP registration under
`mcpServers.contextbase` in `~/.factory/mcp.json`, and the companion skill in `~/.factory/skills`.
The installer touches only JSON files - no Droid CLI round-trip - and refuses to overwrite a
user-managed MCP server already named `contextbase`. Droid's hook protocol matches Claude Code's
(`session_id`/`transcript_path`/`cwd` in, `hookSpecificOutput.additionalContext` out). Recall and
injection use the same protocol; write-back also handles Droid's cancellation notification because
Droid does not emit `Stop` after a cancelled turn.

#### ZCode

```bash
contextbase-coding-agents install zcode
```

Three hook registrations plus a stdio MCP server under `mcp.servers.contextbase`, both in ZCode's own
CLI config `~/.zcode/cli/config.json` - never your real Claude Code settings, even though ZCode
embeds the Claude Code agent runtime and speaks its hook protocol. The companion skill goes to
`~/.zcode/skills`. Config hooks ship **disabled**, so the installer also sets `hooks.enabled` to
`true`; `uninstall` removes the whole block again when nothing else is registered there, and
refuses to touch an MCP server named `contextbase` that it did not write.

> ZCode's hook `timeoutMs` is in **milliseconds** (installed values `30000/30000/60000`), and
> `hooks.maxOutputBytes` caps what a hook may print - anything larger is dropped, injection and
> all. The installer seeds it at `32768` only when your config does not already set one.
>
> ZCode keeps no durable session transcript: `Stop` carries the reply plus a temp, assistant-only
> file it deletes as soon as the hook returns, and no user prompt at all. So this is the one agent
> whose conversation the plugin journals itself - the prompt hook records what you asked, the
> `Stop` hook records the reply - and the write-back then behaves like every other agent's,
> appending each new turn to the same session document. `--import-conversations` is therefore not
> available for ZCode: there is no past history on disk to backfill from.

#### TraeCode

```bash
contextbase-coding-agents install traecode
```

Three hook registrations in TraeCode's user-level `hooks.json`, the companion skill under the
same dot-dir's `skills/`, and two `filesystem.readWrite` rules in `sandbox.json` — one for
`~/.contextbase`, without which the hooks fail silently (exit 0, no effect) because the sandbox
blocks those writes, and one for Trae's per-window storage DBs
(`<userData>/User/workspaceStorage`), which the SessionStart hook seeds with the workspace's
MCP enable switch. Network is allowed by default. TRAE ships two editions with different brand
roots — the CN build uses `~/.trae-cn` and "Trae CN", the international build `~/.trae` and
"Trae" — so every path resolves by probing for the edition dir that exists and defaulting to the
CN names. Plain JSON files, no CLI round-trip. TraeCode speaks Claude Code's hook protocol, so
recall and injection work exactly as they do there; the event map lives under the top-level
`hooks` key and the `version` field the host writes is preserved.

MCP is registered per repo, never at the user level: Trae launches user-level servers with the
Electron process's cwd (your home directory), where a ContextBase entry either self-disables under
`optInOnly` (zero tools). The installer registers a
`mcpServers.contextbase` stdio server in `<repo>/.trae/mcp.json`, pinned to that repo via
`CONTEXTBASE_MCP_PROJECT_CWD` — migrates any stale user-level entry back out of
`<userData>/User/mcp.json`, and seeds the per-workspace enable switch directly. The SessionStart
hook re-checks both on every session and writes them only when missing or stale (idempotent
fallback) — Trae's hook sandbox cannot be relied on to perform those writes itself. The per-repo
file is merged not clobbered, and gitignored when the repo has a `.gitignore` (the path is
machine-specific). A foreign `contextbase` entry — in either file — is the user's own server and
is never touched.

Trae only reads that per-repo file once the global `trae.mcp.enableWorkspaceMcp` setting is on
(default off), so the installer handles the gate: an interactive run asks, a non-interactive run
takes `--enable-workspace-mcp`, and either way the setting is written and Trae windows must be
restarted to pick it up (declining, or a settings file with comments, prints the manual step).
Registrations and enable switches take effect after restarting the Trae window. Run `install traecode --project-path <PROJECT_PATH>` for another project. If its server still shows disabled in the MCP panel, enable it there.

> One manual step remains after install (UI state the installer cannot write): enable the hooks
> under TraeCode Settings > Hooks. If you declined the workspace-MCP prompt, enable it later in
> Trae settings (search "enableWorkspaceMcp").

> TraeCode keeps no readable session transcript - sessions live in an encrypted local DB or the
> cloud. Like ZCode, its conversation is journaled by the plugin itself: the prompt hook records
> what you asked, and the `Stop` hook closes the turn with the reply it carries in
> `last_assistant_message`. `--import-conversations` is therefore not available for TraeCode:
> there is no past history on disk to backfill from.

#### Antigravity CLI

```bash
contextbase-coding-agents install agy
```

Lifecycle hooks, MCP, and the `contextbase · <bank>` status line.

#### Devin CLI

```bash
contextbase-coding-agents install devin-cli
```

Hooks in `~/.config/devin/config.json` plus MCP. Needs Node 22.5+ — see below.

#### Cline CLI

```bash
contextbase-coding-agents install cline-cli
```

A native plugin via `cline plugin install`, plus MCP and the companion skill.

#### pi

```bash
contextbase-coding-agents install pi
```

An extension entry in `~/.pi/agent/settings.json`, plus the companion skill in
`~/.pi/agent/skills` — native tools, no MCP needed.

This command is the only supported route, for pi and for Prime Agent below. Installing us as a pi
package (`pi install npm:@huaweicloud/contextbase-coding-agents`) is deliberately not wired: both
hosts read the same `pi` key of a package's `package.json`, and that key can only name one entry —
whichever host it did not name would load the other's bundle and report itself as the wrong agent,
taking that harness's config section and stamping every document it retains with it. So the package
carries no `pi` key at all, and each host is pointed at its own bundle by the install command above.

#### Prime Agent

```bash
contextbase-coding-agents install prime-agent
```

Prime Agent is a fork of pi, so it is wired the same way: an extension entry, here in
`~/.prime/agent/settings.json`, plus the companion skill in `~/.prime/agent/skills` — native tools,
no MCP needed. Installing both is fine and expected:
each host loads its own entry from its own settings file, and like every other pair of agents they
**share one bank per repo** (the default `coding-agent::{gitProject}`), so what you tell pi is there
when you open Prime Agent. Separate entries are what keeps each side attributable — its own
`harnesses.<name>` config section, and its own agent stamped on every document it retains.

#### DeepSeek Harness

```bash
contextbase-coding-agents install dsh
```

A Cordis plugin row in `$DSH_HOME/cordis.patch.yml` (`~/.dsh` by default), which every dsh profile
composes — native tools, no MCP needed. Two dsh-specific notes: one dsh process serves **several
repositories** (its Web UI opens each session in whatever directory you pick), so the bank is
resolved per session workspace rather than once per process; and dsh has no plugin-facing notice
channel, so the seed line goes to the plugin log rather than the UI. Everything model-facing —
recalled memory, the knowledge preamble, the `contextbase_*` tools — is unaffected. Use the locally
built CLI shown above. A registry package name has not been selected; only use the host plugin
manager with a distribution explicitly supplied by your service administrator. The package
includes its profile patch layer and installs the companion skill on the first session.

#### WorkBuddy

```bash
contextbase-coding-agents install workbuddy
```

3 hooks in `~/.workbuddy/settings.json`, the stdio MCP server in `~/.workbuddy/mcp.json`, and the
companion skill in `~/.workbuddy/skills`. WorkBuddy (Tencent's AI workbench) is built on the shared
`@genie/agent-cli` engine, so its hooks follow Claude Code's protocol — the main difference is the
transcript schema (`type:"message"` records carrying top-level `role`/`content`), which the
package's own reader normalizes.

#### CodeBuddy

```bash
contextbase-coding-agents install codebuddy
```

3 hooks in `~/.codebuddy/settings.json`, the stdio MCP server in `~/.codebuddy/.mcp.json` — the
recommended file: the installer follows CodeBuddy's documented fallback chain, merging into an
existing deprecated `~/.codebuddy/mcp.json` or legacy `~/.codebuddy.json` rather than shadowing it —
and the companion skill in `~/.codebuddy/skills`. CodeBuddy Code runs the same `@genie/agent-cli`
engine as WorkBuddy — WorkBuddy merely ships it with a different home folder — so it reuses
WorkBuddy's hook runtime, and differs only in the root it writes to.

**Both CodeBuddy hosts are covered, and they do not store sessions alike.** CodeBuddy Code (the CLI)
writes the WorkBuddy JSONL that the shared reader parses. The IDE hands the Stop hook its own
per-conversation directory instead — `CodeBuddyIDE/<uid>/history/<md5(workspace)>/<conversationId>/`,
whose `index.json` _is_ the `transcript_path` and whose prose sits one level down, in
`messages/<messageId>.json` — so the reader dispatches on the shape it was handed
(core/transcript-codebuddy-ide.ts).

Uninstall the same way: `contextbase-coding-agents uninstall claude-code` (or `uninstall all`).

**Devin CLI needs Node 22.5 or newer.** Its hooks pass only a session id — the conversation itself
lives in `~/.local/share/devin/cli/sessions.db` — so reading it depends on Node's built-in
`node:sqlite`. Installing `devin-cli` checks for this first and refuses (with the reason) rather
than wiring hooks that could never retain anything. Every other agent works on any supported Node.

`install` copies what it needs into `~/.contextbase/coding-agents` and points each agent's wiring
there, so nothing depends on where you ran it from. **Updating** is the same command again — it
re-copies the runtime in place, leaving the wiring valid and every new session on the new version.

`install` merges the native wiring (hooks + MCP registration where the host wants them) into each
agent's own config, preserving everything already there; it is idempotent (re-run after moving the
package) and backs up any pre-existing file it touches as `<file>.contextbase-backup`. `uninstall`
removes only our entries. On Claude Code the install also ships a **companion skill**
(`~/.claude/skills/contextbase-coding-agent`) that teaches the agent how this memory works — what
"store this in ContextBase" should do, the tool surface, per-repo configuration, debugging — so users
can ask the agent itself. Manual wiring per harness, if you prefer:

**opencode** and **opencode 2** install directly — point `opencode.json` at the package dir:

```json
{ "plugin": ["/path/to/contextbase-coding-agents"] }
```

One entry, both CLIs: v1 resolves that directory through `package.json` `main`, v2 through its
`index.js`, so each loads its own plugin.

**Claude Code** and **Codex** get their full three-hook + MCP wiring from this package's own
installer — `contextbase-coding-agents install claude-code` / `install codex`. This package's `bin`
entries (`contextbase-claude-hook`, `contextbase-codex-hook`,
`contextbase-cursor-hook`) are the individual injection-only `UserPromptSubmit` entrypoints for a
minimal, hand-wired setup.

Adding an agent: hook-based → write a `HookSpec` entry point (see `src/cursor-hook.ts`) and register
a `hookAdapter` in `src/harness/registry.ts`; persistent-plugin → implement `HarnessAdapter`
(`src/core/types.ts`) fully (see `src/harness/opencode.ts`), or bind the host's own plugin API to
`RuntimeCore` directly when it is not an opencode fork (see `src/cline.ts`, `src/dsh.ts`).

## Import local conversations

You can import existing conversations from local disk as new documents:

```bash
cd /path/to/your/repo
contextbase-coding-agents install claude-code --import-conversations   # or: install codex --import-conversations
```

This re-extracts the transcripts the agent already wrote, so it costs tokens roughly in proportion
to the history imported, and it is safe to re-run (ingestion dedups by document id).

**How sessions are matched.** A conversation is imported only when the session itself records the
directory it ran in — never inferred from a file or folder name. Claude Code writes that directory
on its entries, Codex in its `session_meta` header and DeepSeek Harness in its session-log header,
and pi and Prime Agent in their session header, so all five can be attributed exactly, including
sessions started in a subdirectory of the repo. Guessing was tempting (Claude names its history
folders after the project path) but unsafe: `/` and `.` both encode to `-`, so `repo-sub` is either
the subdirectory `repo/sub` or an unrelated sibling repo — and a wrong guess files someone else's
conversation into your bank. Sessions that record nothing are skipped and the count is reported.
DeepSeek Harness logs are Zstandard-framed JSONL under `$DSH_HOME/sessions`, which needs Node 22.15+
to read; an older Node skips the import with that reason rather than silently importing nothing.
Dcode's transcripts record no directory at all — the working directory lives only in its LangGraph
checkpoint database — so the repo comes from `dcode threads list --json`, a declared, versioned
command contract rather than that internal schema; with the `dcode` CLI unavailable the import is
skipped with that reason. The other harnesses (opencode, opencode 2, Kilo, Cursor, Cline, Copilot, Devin) keep
history in internal SQLite databases with unversioned schemas and are skipped with a reason.

## Where memory lives

Memory lives in the remote service assigned to your account. The API Endpoint is independent of the download URL. Set the endpoint once in `~/.contextbase/coding-agent.json`; hooks, native tools and the local MCP adapter share that connection. The adapter translates local MCP calls into remote API requests; it does not run a memory engine.

```json
{
  "apiUrl": "https://your-api-endpoint.example",
  "apiToken": "your-credential",
  "autoUpdate": false
}
```

The example host is a placeholder. Copy the real API Endpoint from your console; do not substitute the MCP Endpoint here. `cloud` and `self-hosted` both connect to explicit URLs. `--server daemon` is rejected.

Use one default API connection across all harnesses, paths and banks. Configure `apiUrl` / `CONTEXTBASE_API_URL` and `apiToken` / `CONTEXTBASE_API_TOKEN`. Missing addresses produce configuration guidance; no localhost discovery or engine download occurs. Per-harness, per-path and per-bank connection overrides are ignored. CLI Profiles belong to the separate ContextBase CLI.

`serverMode` / `CONTEXTBASE_SERVER_MODE` accepts `cloud` or `self-hosted` (default `cloud`). Both connect to your configured remote API; this package does not install or start a local server.

The public npm package is `@huaweicloud/contextbase-coding-agents`. Install and upgrade integrations with
`npx @huaweicloud/contextbase-coding-agents@latest install <harness>`. The examples below use
`contextbase-coding-agents` for brevity; prefix commands with `npx @huaweicloud/contextbase-coding-agents@latest`
when the executable is not installed globally.

## Configuration

Configuration is **one JSON file**: `~/.contextbase/coding-agent.json`. Layering, later wins per field:

1. built-in defaults
2. environment variables — `CONTEXTBASE_API_URL`, `CONTEXTBASE_API_TOKEN`, and one per scalar setting
   (`CONTEXTBASE_<FIELD_IN_CAPS>`), for containers and CI that inject config rather than write a file
3. the file's top level
4. its `harnesses.<name>` section — per-agent override
5. its `paths.<prefix>` section — per-directory override, applied after the bank is resolved
   (see Per-directory overrides)
6. its `banks.<bankId>` section — behavioral overrides for the configured workspace

Environment variables are a **fallback**: the file wins wherever it sets a value, so adding env to
an existing setup changes nothing. The two list-valued settings, `retainTags` and `optInPaths`, take
a comma-separated value (`CONTEXTBASE_RETAIN_TAGS="project:{gitProject},env:work"`); entries are
trimmed and blanks dropped.
The map-valued settings (`harnesses`, `paths`, `banks`, `retainMetadata`) are file-only —
per-key branching doesn't survive flattening into one variable. `maxParallelRetains` is available
as `CONTEXTBASE_MAX_PARALLEL_RETAINS` for containers and CI.

`CONTEXTBASE_CONFIG` moves the file itself — point it at another path for a container or a test
harness where `$HOME` is not the right anchor. It is still exactly one file; only its location
changes. (The other variables that are not settings are `CONTEXTBASE_LOG_FILE`, `CONTEXTBASE_DIAG_FILE`,
`CONTEXTBASE_USAGE_FILE` and `CONTEXTBASE_LOG_LEVEL` — see Diagnostics & logging.)

### When a change takes effect

Config is read when a process starts — the file is not watched — so when an edit applies depends on
what reads it:

| host                                                                                                        | reads the file                                                      | an edit applies            |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- | -------------------------- |
| hook harnesses (Claude Code, Codex CLI, Cursor CLI, GitHub Copilot CLI, Grok Build, Antigravity CLI, Devin) | once per hook invocation — each hook is its own short-lived process | on your next prompt        |
| persistent plugins (opencode, opencode 2, Kilo CLI, Cline CLI, pi, Prime Agent, DeepSeek Harness)           | once per workspace, when the host loads the plugin                  | after restarting the agent |
| the MCP server behind the `contextbase_*` tools                                                             | once at startup                                                     | in your next session       |

`apiToken` is the exception. Every host re-reads it when the server rejects a request, so enabling
authentication or rotating the key is picked up on the next call with nothing to restart —
otherwise a rotation would leave a long-running agent failing every memory call until it was
restarted. Everything else follows the table: `apiUrl`, `disabled`, bank routing, `gitIngest`, and
the survey and knowledge-page settings.

`contextbase_diagnose` reports both sides of that gap — what the file says now, and what the running
client is actually using.

### Opt-in only

After a workspace is configured, every project may use it by default. If you would
rather nothing be remembered until you say so, turn memory off everywhere and name the projects
that may use it:

```jsonc
{
  "optInOnly": true,
  "optInPaths": ["~/work/client-x", "~/oss"],
}
```

Anything outside those paths is **inert**: nothing is retained and no seed runs.
`optInPaths` controls which projects may use memory; every approved project uses the same configured `bankId`. Paths are prefixes, so approving `~/work` approves the projects beneath it.
A configured workspace does not itself approve a path when `optInOnly` is enabled.
There is no repository-local configuration file: a cloned repository cannot change the endpoint, token, workspace or approval policy. `harnesses.<name>` customizes behavior per agent.

Each entry point knows which harness it _is_ (the opencode plugin is loaded by opencode, the codex
hook by Codex...), so one shared config serves several agents side by side:

```jsonc
{
  "apiUrl": "<configured-service-url>",
  "harnesses": {
    "opencode": { "reflectTimeoutMs": 60000 },
    "claude-code": { "disabled": true }, // e.g. memory off for Claude only
  },
}
```

### Reference

| field                   | default         | meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apiUrl`                | required        | API Endpoint copied from the console; no default                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `apiToken`              | —               | bearer token (ContextBase Cloud). Picked up without restarting the agent: a long-lived host re-reads it after a rejected request, so enabling auth or rotating the key mid-session recovers on the next call                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `bankId`                | required        | Existing workspace ID shared by every directory and agent. Set with `--bank-id` during installation or `bank use <BANK_ID>` afterwards. No automatic selection or creation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `optInOnly`             | `false`         | run memory ONLY in opted-in projects — everything else is inert, with no bank created; see Opt-in only                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `optInPaths`            | —               | directories opted in, matched as prefixes with `~` expanded; each repo beneath and its linked worktrees are approved while keeping their own dynamic bank                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `resolveWorktrees`      | `true`          | linked worktrees inherit the main checkout's bank identity, path approval, and mapping                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `retainTags`            | —               | extra tags on every document written by the integration, e.g. `["project:{gitProject}"]` — see **Recording where a memory came from** below                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `retainMetadata`        | —               | extra metadata on every document written by the integration, e.g. `{"repo": "{gitProject}"}`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `retainContext`         | see description | the `context` sent with every session write-back. Extraction reads it to decide whose claim a sentence is, so the default names both speakers, and asks for an agent's own "fixed" or "passes" to be stored as its claim rather than as fact. Accepts the same `{placeholder}` templates as `retainTags`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `manageBankConfig`      | `false`         | Leave workspace configuration and knowledge pages under the owner’s control. Set `true` explicitly to apply coding settings and seed pages on an existing workspace.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `retainExtractionMode`  | `"concise"`     | how the server extracts memories from sessions, commits and documents: `"concise"`, `"verbose"`, `"verbatim"` or `"chunks"` (store the text, no extraction). Every Stop writes the session back, so this is what each turn costs — `"verbose"` pulls more detail for several times the tokens. Kept in sync on the plugin's own retain strategies every session, so a change reaches existing banks too (not with `manageBankConfig: false`)                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `defaultBankConfig`     | —               | bank-config fields of your own for the banks the plugin shapes, e.g. `{"enable_observations": false, "enable_auto_consolidation": false, "mental_model_min_refresh_interval_seconds": 21600}`. Keys are the bank-config API's own field names. Written under the same additive rule as the rest: only where the bank does not define the field, so an existing workspace receives these where it has no override and a value you set in the control plane is never overwritten. Wins over the template on a key both name (`enable_observations`); `retain_strategies`, `entity_labels` and `retain_extraction_mode` are refused, since the plugin governs them itself. Ignored with `manageBankConfig: false` — see **A bank you shape yourself** below. File-only, like `recallOptions`; in a `banks.<id>` section it replaces the global map rather than merging into it                                     |
| `observationScopes`     | `"shared"`      | how consolidation groups observations: `"shared"` (default) = ONE global scope per bank, so every agent on a repo builds one set of beliefs; also `"combined"` (the server default), `"per_tag"`, `"all_combinations"`, `[["t"]]`; `"per_source"` adds a scope per `source:` kind alongside the global one, so commit knowledge and conversation knowledge consolidate apart                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `disabled`              | `false`         | hard off-switch (inert plugin/hook — a no-memory baseline)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `reflectTimeoutMs`      | `20000`         | **automatic** session-reflect timeout; on hook harnesses the installer registers a 30s prompt-hook timeout, so going above ~20s also means raising that hook's `timeout` in the host's config, or the host kills the hook mid-reflect; on timeout or a 5xx the hook falls back to knowledge-page search, then to a raw recall of observations (recorded)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `reflectToolTimeoutMs`  | `330000`        | timeout for the agent-invoked `contextbase_reflect` tool — a call the agent waits on, whose high-budget synthesis on a populated bank runs for minutes. Defaults above the server's own reflect wall timeout (`CONTEXTBASE_API_REFLECT_WALL_TIMEOUT`, 300s) so the server decides when to give up. Unset, it inherits an explicitly raised `reflectTimeoutMs`, but a short one never lowers it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `injectTimeoutMs`       | `7000`          | retrieval timeout in milliseconds for `autoInject: "pages"` and `autoInject: "recall"`; also the **shared** budget for page search then recall after a reflect timeout/5xx (recall gets only the time left after page search). Set e.g. `2000` to limit turn latency or `15000` for a slower self-hosted bank. Environment fallback: `CONTEXTBASE_INJECT_TIMEOUT_MS`. On hook harnesses, injection must fit the host's prompt-hook timeout (30s by default); for reflect with fallback, allow for **`reflectTimeoutMs` + `injectTimeoutMs`**, and raise the host hook's `timeout` when needed                                                                                                                                                                                                                                                                                                                   |
| `reflectBudget`         | `"high"`        | reflect budget for the `contextbase_reflect` tool: `"low"`, `"mid"` or `"high"`. Drop it on a large bank where high-budget synthesis exceeds the server's wall timeout. The automatic session-start reflect always uses `"low"` to fit its hook window and is unaffected                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `autoInject`            | `"reflect"`     | what to inject once, on the session's **first prompt**: `"reflect"` = a low-budget reflect synthesis (on timeout/5xx it falls back to page search, then recall); `"pages"` = the knowledge pages matching the prompt by search; `"recall"` = the bank's memories recalled for the prompt (what it asks for is `recallOptions`, observations by default); `"none"` = nothing — the agent searches knowledge pages first and reflects only when they are too shallow. `"pages"` and `"recall"` are retrieval only (no LLM), their time budget is `injectTimeoutMs`, and when one finds nothing for the prompt it tries again on the next one, up to 5 prompts                                                                                                                                                                                                                                                     |
| `autoReflect`           | `true`          | **deprecated** — use `autoInject`. Still honoured (`false` = `autoInject: "none"`), ignored when `autoInject` is set, and logs a deprecation warning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `pageSearchLimit`       | `3`             | knowledge pages ONE search returns. Applies to every search of the bank — the `autoInject: "pages"` injection, the reflect fallback, and the agent's own `contextbase_search_knowledge_pages` tool — because the limit lives on the client they all share                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `recallOptions`         | see description | overrides merged key-by-key into the body of every recall — the `autoInject: "recall"` source and the reflect fallback. Keys are the API's own recall parameters, passed straight through, so anything recall accepts is settable without a new option here; `query` is the one field it cannot replace. The default body is `{"types": ["observation"], "budget": "low", "max_tokens": 2000, "include": {"entities": null}}`, and what you set is merged over it one key at a time — `{"max_tokens": 4000}` changes the budget and leaves the rest alone. Observations are the consolidated layer, so they answer best per token, but a bank with **consolidation disabled never grows any** and the default recall comes back empty on it: set `{"types": ["world", "experience"]}` there, or `{"types": null}` for every type. File-only, like `retainMetadata` — an object does not flatten into an env var |
| `toolGuideExtra`        | —               | your own guidance on how the agent should treat memory, added **after** the built-in tool guide (at session start and on every refresh) and after the crediting note returned with `contextbase_search_knowledge_pages` results. It adds to the built-in text, never replaces it. Set it per harness or per bank like any other key, e.g. `"Memory is a past record, not current state: verify any claim against the code before acting on it."`                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `pageRefreshEveryTurns` | `1`             | refetch the knowledge pages and re-inject the page roster + tool guide every N user turns (`0` also means 1)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `pageTriggerType`       | `"cron"`        | when NEW knowledge pages refresh, i.e. what keeping them current costs — `"cron"` (default) on `pageTriggerCron` only and only when actually stale, `"auto-refresh"` after every consolidation that produced new material, `"manual"` never on their own. Auto-refresh is the most current and by far the most expensive: one synthesis per page per consolidation. Maps to the page's `trigger.refresh_cron`, or `trigger.refresh_after_consolidation` in the ContextBase API (`true` for auto-refresh, `false` for manual)                                                                                                                                                                                                                                                                                                                                                                                    |
| `pageTriggerCron`       | `"H * * * *"`   | schedule for `pageTriggerType: "cron"` — UTC, standard 5-field cron, e.g. `"0 3 * * *"`. The default is hourly, each page on its own hashed minute. Sets the page's `trigger.refresh_cron`, which the API treats as mutually exclusive with `refresh_after_consolidation`; a scheduled refresh is skipped when nothing changed. Write a field as `H` to give each page its own value there — see **Spreading refreshes with `H`** below                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `pages`                 | every page      | per-page configuration for the seeded knowledge pages, keyed by page name (case-insensitive): `false` skips a page entirely, `{"source_query": "..."}` seeds it with your question instead of the built-in one. Omitted, all five pages are seeded with their built-in queries. This is the supported way to own a page's wording — the plugin re-syncs a page whose live query differs from the one it is configured to have, so a query edited through the API or the control plane is replaced on the next session. A skipped page is **not deleted**: one already seeded keeps its content and stops being re-synced. The scoping clause is appended to your query too, so a reworded page cannot start reporting a dependency's decisions as this project's. File-only, like `recallOptions`; in a `banks.<id>` section it replaces the global map rather than merging into it                             |
| `customPages`           | —               | knowledge pages of your own, seeded alongside the five above and keyed by the name they get: `{"Security posture": {"source_query": "...", "tags": ["knowledge:decision"]}}`. `source_query` is required; `tags` picks which facts feed the page and is optional — omitted, the page draws on everything the bank holds. A separate setting from `pages` on purpose, so that an unknown name there stays a typo warning rather than quietly creating a page. File-only, and replaced (not merged) by a `banks.<id>` section                                                                                                                                                                                                                                                                                                                                                                                     |
| `autoSeed`              | `true`          | SessionStart: auto-seed a cold repo's bank from git history                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `seedLimit`             | `300`           | auto-seed: most-recent-N-commits cap                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `codebaseSurvey`        | `true`          | SessionStart: headless survey of a cold repo's structure, run under the current harness's own CLI (claude/codex/antigravity/opencode), falling back to any available agent                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `surveyModel`           | `haiku`         | model for the survey — Claude recipe only (`claude -p --model`); other agents use their configured default                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `surveyBudgetUsd`       | `2`             | survey spend cap — Claude recipe only (`claude -p --max-budget-usd`); other agents rely on their read-only sandbox                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `surveyRefreshCommits`  | `20`            | re-run the survey at SessionStart once this many commits have accrued since the last one, so the structural pages track an architecture that keeps moving (`0` = survey a cold repo only, never again)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `retainSessions`        | `true`          | session write-back, honored by every harness: hook harnesses write the transcript on Stop, Factory Droid also writes on its cancellation notification, and plugin harnesses (opencode, opencode 2, Kilo) upsert it every turn plus an idle flush that captures the reply the per-turn pass can't see. Set `false` - globally, per harness, or per bank - to stop writing transcripts (the background history import stops with it) while recall, git ingest and the memory tools keep working                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `maxParallelRetains`    | `10`            | cap on concurrent retain-related requests: drain()'s per-op polls plus deepen's chat/git retain pools. The API rate-limits bursts, not single requests — if you see 429s, lower this rather than raising it                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `logLevel`              | `"info"`        | plugin-log verbosity (`"debug"` \| `"info"` \| `"warn"` \| `"error"`); `CONTEXTBASE_LOG_LEVEL` env overrides                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `autoUpdate`            | `true`          | keep the installed runtime current by itself: when `CONTEXTBASE_CODING_AGENTS_PACKAGE` names an administrator-approved distribution, once a day a session start asks npm for its published version and, when it is newer, re-stages `~/.contextbase/coding-agents` in the background. It rewires no host config, so a release adding a **new** hook entry point still needs a manual `install`. Set `false` to pin the installed version; `disabled` stops it too, since an inert plugin should stay inert. Only ever replaces a runtime installed from that explicitly configured distribution via `npx` — a copy installed with `npm i -g`, vendored as a project dependency, or built from a checkout is left to whoever manages it (update those the way you installed them), and it needs `npx` and `npm` on `PATH`                                                                                        |
| `gitIngest`             | `"message"`     | git depth for seeding AND staying current (same engine): `"message"` = commit messages only (one doc, re-upserted when HEAD has a commit it lacks); `"full"` = messages + per-commit full diffs (progressive, newest first); `"none"` = git off                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `harnesses.<name>`      | —               | per-harness override of any field above                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `harness`               | `opencode`      | **deepen engine only**: which session format `--conversations` is read as                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

By default a page refreshes **hourly, staggered**: `pageTriggerCron` is `"H * * * *"`, so every
page gets its own minute of the hour (see below) and a tick with nothing new to fold in is skipped
server-side. That keeps pages within an hour of the repo without paying auto-refresh's price — one
LLM synthesis per page per consolidation, on a repo that consolidates all day. Set
`pageTriggerType: "auto-refresh"` to go back to refreshing on every consolidation.

`pageTriggerType`/`pageTriggerCron` decide only **when** a page refreshes. **How** it refreshes
belongs to the server: ContextBase creates a knowledge page with a delta refresh (each pass edits the
page instead of rebuilding it) that doesn't reflect over sibling pages, and these settings merge
over those defaults rather than replacing them.

### Spreading refreshes with `H`

One `pageTriggerCron` is shared by every page in every repo you point this plugin at. So a literal
`"0 3 * * *"` does not schedule _a_ refresh at 03:00 — it schedules **all** of them at 03:00, five
pages per bank, on the same worker pool that serves retain. A session ingesting at 03:0x queues
behind the pile, and moving the hour just moves the pile.

Write a field as `H` and it is replaced, per page, by a value hashed from the bank id and the page
name. Each page gets its own slot, the same slot on every run:

| `pageTriggerCron`  | what each page gets                                    |
| ------------------ | ------------------------------------------------------ |
| `"H H * * *"`      | once a day, at its own minute and hour                 |
| `"H * * * *"`      | once an hour, at its own minute                        |
| `"H 3 * * *"`      | daily at 03:MM — spread inside the hour you chose      |
| `"H H(0-5) * * *"` | daily, spread across 00:00–05:59 only                  |
| `"0 3 * * *"`      | no `H`, no hashing — exactly what it says, all at once |

`H` is [Jenkins' syntax](https://www.jenkins.io/doc/book/pipeline/syntax/#cron-syntax) for the same
problem. It never reaches the API: the plugin resolves it to an ordinary cron expression
(`"41 17 * * *"`) when it creates the page, so the schedule you see in the control plane is a plain
one you can edit. Hashing spreads pages out, it does not partition them — two pages can still land
on the same minute, just not all of them.

**These settings apply to the pages a repo already has, too.** Every session compares each page
this plugin created — the seeded taxonomy and every captured initiative — against the config and
re-syncs the ones that differ, so a bank seeded before this default changed moves onto the hourly
schedule by itself, and a page you retriggered by hand in the control plane is put back on the
configured policy the next time an agent runs. The config
file is the source of truth for these pages: to give one a different schedule, change
`pageTriggerType`/`pageTriggerCron` (per bank, if it is only that repo) rather than editing the
page. Only the fields this plugin states are touched — a page's `mode`, its excluded siblings and
its minimum refresh interval are left exactly as they are.

### Customize Knowledge Pages — `pages`

Every repo gets the same five pages. They are a **taxonomy**, not a summary of your source: each one
is synthesized from what the bank ingested — commit history and past conversations — and each is
pinned to one knowledge tier, so a page draws only on the facts the extractor routed to it.

| Page                           | What it answers                                                                                         | Tier tag                 |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- | ------------------------ |
| `Component map`                | the main components/modules/subsystems, what each is responsible for, and how they depend on each other | `knowledge:component`    |
| `Core concepts`                | the domain abstractions and key entities — the vocabulary a developer has to know                       | `knowledge:concept`      |
| `Conventions and patterns`     | how THIS project does things: testing, error handling, naming, structure, how changes are made          | `knowledge:convention`   |
| `Key decisions and rationale`  | the significant technical decisions and the durable "why we do it this way" behind them                 | `knowledge:decision`     |
| `Initiatives and enhancements` | the major initiatives and features over time, linking out to each captured initiative's own page        | `knowledge:feature-work` |

`pages` says which of them to seed and what each one asks. Keys are the page names above, matched
ignoring case and surrounding spaces:

```jsonc
{
  "pages": {
    // don't seed this page at all
    "Component map": false,
    // seed it, but ask your question instead of the built-in one
    "Key decisions and rationale": {
      "source_query": "What did we decide about data retention, encryption and PII handling, and why? Prefer decisions that constrain what new code may do.",
    },
  },
}
```

Omit `pages` entirely — the default — and all five are seeded with their built-in queries.

**Fewer pages.** Each page costs one LLM synthesis per refresh, so a repo that only wants the
architecture ones turns the rest off:

```jsonc
{
  "pages": {
    "Initiatives and enhancements": false,
    "Conventions and patterns": false,
    "Key decisions and rationale": false,
  },
}
```

**Per repo**, like every other field — usually where this belongs, since what a page should ask is a
property of the project, not of your machine:

```jsonc
{
  "banks": {
    "coding-agent::payments-api": {
      "pages": {
        "Core concepts": {
          "source_query": "What are the payment domain's entities — orders, ledgers, settlement states — and what does each mean in OUR model?",
        },
      },
    },
  },
}
```

Four things worth knowing before you reach for it:

- **This is the only durable way to reword a page.** Every session compares each seeded page against
  the query it is configured to have and re-syncs the ones that differ, so a `source_query` edited
  through the API or the control plane is replaced the next time an agent runs. Setting it here makes
  your wording the configured one. When a re-sync does replace a query, the plugin now says which
  page in the plugin log rather than doing it silently.
- **Your query still gets the scoping clause.** The sentence that keeps a dependency's decisions off
  your project's page is appended to a custom query too — a bank holds facts about the libraries and
  services a repo merely uses, and without that clause a page will present them as yours.
- **The tier tag stays the taxonomy's.** It selects which facts the synthesis reads; rewording the
  question changes what is asked of those facts, not which ones are in scope.
- **`false` does not delete anything.** A page already seeded keeps its content and simply stops
  being re-synced — remove it in the control plane if you want it gone.

A name that matches no page above is ignored with a warning in the plugin log, so a typo fails
loudly instead of looking like it disabled something. Adding pages of your own is not what this
setting is for: the agent's `contextbase_capture_initiative` tool already creates pages, one per
initiative, each with its own query.

#### Pages of your own — `customPages`

`pages` only reworks the five above. To add a page, name it under `customPages`:

```jsonc
{
  "customPages": {
    "Security posture": {
      "source_query": "What are this project's security decisions — authn, secrets handling, PII, dependency policy — and what do they constrain in new code?",
      "tags": ["knowledge:decision"],
    },
    "Operational runbook": {
      "source_query": "How does this project get deployed, monitored and rolled back? What has broken in production, and what fixed it?",
    },
  },
}
```

`source_query` is required. `tags` is optional and picks which facts feed the page — one of the tier
tags above, or any tag you stamp on your own writes with `retainTags`. Omit it and the page draws on
everything the bank holds: a refresh matches tags with `all`, so no tags means no tag constraint,
**not** an empty page.

Your pages are seeded at the same root as the taxonomy, on the same refresh schedule, and re-synced
from the config the same way — reword one here and the live page follows on the next session. They
compose with `pages`, so trading two built-ins for one of your own is just both settings at once.

**Why it is a separate setting.** `pages` refuses a name that matches no seeded page, and that is
what makes a typo loud: if an unknown key there meant "create this page", `"Componnet map"` would
quietly create an empty second page instead of rewording the one you meant. For the same reason,
naming a seeded page under `customPages` is refused — reword it under `pages`.

A page you create yourself in the control plane is a third thing again, and the plugin never touches
it: the seed pass only visits the pages it is configured to own.

### A bank you shape yourself — `manageBankConfig`

When `manageBankConfig: true` is explicitly enabled, the plugin applies the coding settings its ingestion uses: retain strategies for the
kinds of document it writes (`git`, `gitlog`, `conversation`, `document`, `survey`), a `knowledge`
entity-label group that routes facts to the knowledge pages, and — on a bank that has no missions of
its own — the coding missions.

**It only ever adds what is missing.** A strategy you defined, an edit you made to one of the
plugin's, a reworded label group, a mission you rewrote in the control plane: each is left exactly
as it is, on every session, forever. What the bank already says wins. The cost of that promise is
that a plugin release which _rewords_ an existing strategy or label does not reach a bank that
already has it. To take the current default back, clear that override on the bank (delete the
strategy, or the whole `retain_strategies` entry, in the control plane): the next session finds the
bank silent there and seeds it again.

One field is the exception: the extraction mode of the plugin's own four strategies (`git`,
`gitlog`, `conversation`, `document`) follows `retainExtractionMode` and is put back on every session
if it drifts — the same way a seeded page's query is. Change it in `coding-agent.json`, not in the
control plane. The strategies' other fields, and your own strategies, are still left alone.

**Your own defaults — `defaultBankConfig`.** With configuration management explicitly enabled, these fields are added to the configured workspace wherever it has no override:

```json
{
  "defaultBankConfig": {
    "enable_observations": false,
    "enable_auto_consolidation": false,
    "mental_model_min_refresh_interval_seconds": 21600
  }
}
```

The keys are the bank-config API's own field names, passed straight through, so anything the
bank-config accepts can go here. They follow the same additive rule as the template: written only
where the bank is silent, so an existing bank picks them up on its next session **except** for the
fields it already sets — a value you chose in the control plane stays, even one equal to the server
default, and so does a value an earlier plugin release seeded (the template writes
`enable_observations: true` alongside the missions; clear that override on the bank to let your
default in). On a key the template also names, your default wins. The three fields the plugin
governs itself — `retain_strategies`, `entity_labels` and `retain_extraction_mode` — are refused
with a warning: the first two are merged entry by entry, the last is `retainExtractionMode`'s.

`manageBankConfig` defaults to `false`. Installation and `bank use` also disable automatic configuration, seeding and codebase surveys for the selected workspace. They never create a workspace. Create it in the control plane first.
Set `manageBankConfig: true` explicitly if you want the integration to apply coding settings and seed knowledge pages to an existing workspace. Workspace deletion and recreation are unsupported.

### Workspace behavior — `banks.<bankId>`

Optional behavior overrides are keyed by the configured workspace ID:

```jsonc
{
  "bankId": "team_workspace",
  "banks": {
    "team_workspace": { "gitIngest": "none", "retainSessions": true },
  },
}
```

These sections cannot rename or select a workspace. Endpoint, token, and `bankId` come from the shared top-level configuration (with environment fallback), even when a harness or path section supplies behavior overrides.

### Per-directory overrides — `paths.<prefix>`

Use directory overrides to customize memory behavior while sharing the default connection:

```jsonc
{
  "paths": {
    "~/work": { "retainSessions": false },
    "~/work/app": { "retainSessions": true },
  },
}
```

The longest matching prefix wins. Linked worktrees use the main checkout's entry. Bank overrides apply afterwards. Endpoint, credential, local-engine, bank-resolution and approval fields cannot be overridden here. The same connection restriction applies to `banks` and `harnesses` sections.

### Bank selection

Only the configured `bankId` is used. All repositories, worktrees, directories and agents share it.
The file’s top-level `bankId` takes precedence over the `CONTEXTBASE_BANK_ID` environment fallback.
There is no repository naming template, path mapping, default workspace, alias or automatic creation.
If no ID is configured, memory is disabled with a diagnostic explaining how to set it.

Use `npx @huaweicloud/contextbase-coding-agents@latest bank use <BANK_ID>` to change the shared selection, then restart the agent and MCP server. The command changes only the shared configuration; it does not reinstall clients or call workspace creation APIs.

### Recording where a memory came from

A shared workspace holds cross-project knowledge. Record repository provenance so each memory retains its origin. `retainTags` and `retainMetadata` stamp that provenance onto conversations,
git history and diffs, survey lifecycle documents, initiative markers, and documents saved through
`contextbase_ingest_document`:

```jsonc
{
  "bankId": "shared", // one bank for everything
  "retainTags": ["project:{gitProject}", "env:work"],
  "retainMetadata": { "repo": "{gitProject}" },
}
```

Recalls can filter by `project:<repo>`. Supported placeholders are `{gitProject}`, `{project}`, `{harness}`, `{channel}`, `{user}`, `{bankId}`, `{sessionId}` and `{timestamp}`.
`{gitProject}` is worktree-aware here too, so every linked worktree of a repo stamps one name.
`{sessionId}` resolves to `unknown` for documents that do not originate from an agent session.

The plugin's own `source:` and `harness:` tags are reserved: entries in those namespaces are ignored
with a warning, so a document's agent attribution always reflects the agent that actually wrote it.

### One set of beliefs per repo

Every document this integration writes carries provenance tags — `source:chat`, `harness:<id>`,
`knowledge:<kind>`, plus anything from `retainTags`. Those tags say **who wrote** a memory; they are
what filters recall and draws each document's agent logo, and they stay on the facts.

They are not, however, a good boundary for
observations. Consolidation's own
default (`combined`) builds one observation set per distinct tag set, so the same repository
worked on by two agents would grow two parallel sets of beliefs — one per harness — that never
merge, each blind to the other, at double the consolidation cost. Which agent happened to be typing
does not change whether a convention or a decision is true.

So the integration retains with `observationScopes: "shared"`: one global, untagged observation
scope per configured workspace. Set the field to change it:

```jsonc
{
  "observationScopes": "combined", // one observation set per distinct tag set (server default)
  "banks": {
    "coding-agent::mono": { "observationScopes": "per_tag" }, // per workspace, like any behavioral field
  },
}
```

### Splitting code from conversation — `per_source`

`shared` puts every document a repo produces into one belief set. `"per_source"` keeps that set and
adds one per origin, so "what the commits say" and "what was decided in conversation" can be asked
apart:

```jsonc
{ "observationScopes": "per_source" }
```

Each document consolidates into the global scope **plus** one named for each `source:` tag it
carries — `[[], ["source:chat"]]` for a session transcript, `[[], ["source:git"]]` for a commit
diff. Read an axis back with `tags: ["source:git"], tags_match: "exact"`, and the merged view with
`tags: [], tags_match: "exact"`.

A document carrying two `source:` tags gets a scope for each, and that is deliberate rather than
duplication. The commit-message seed is tagged `source:git` and `source:git-log`, so
`source:git-log` is fed only by the seed — what the commit _messages_ say — while `source:git` also
collects every per-commit diff under `gitIngest: "full"`. Two questions, two answers, each
deduplicated within itself by consolidation. A fact belonging to more than one axis is the point.

This cannot be expressed as a scope list. The server treats an explicit `list[list[str]]` as
unconditional — it is not filtered against the memory's own tags — so a configured
`[[], ["source:git"], ["source:chat"]]` writes every document into all three, and the `source:git`
scope fills with beliefs built from chat transcripts. Only a per-document decision separates them.

It costs one extra consolidation pass per document, and it reads only `source:`, so a volatile
provenance tag never becomes a scope. The global scope is still written first and unchanged, so the
untagged observations knowledge pages read are unaffected.

`"per_tag"` and `"all_combinations"` split further still, and an explicit `[["project:demo"], …]`
declares the scopes literally. `CONTEXTBASE_OBSERVATION_SCOPES` sets the scalar modes; a scope list is
file-only. Changing this does not rewrite observations already consolidated under the old scoping —
they stay where they were built, and new work accrues under the new setting.

## Diagnostics & logging

All logs live in `~/.contextbase/coding-agents-logs/` (owner-only). Each file rotates to `<file>.1`
at 10 MB.

**Leveled plugin log** (humans debugging): `~/.contextbase/coding-agents-logs/plugin.log` (override
`CONTEXTBASE_LOG_FILE`) — timestamped `LEVEL [scope] message` lines from every component, including
the ingestion engine. Level defaults to `info`; set `"logLevel": "debug"` in config or
`CONTEXTBASE_LOG_LEVEL=debug` for ad-hoc debugging (at `debug`, every diag event below is mirrored
here too, so one file tells the whole story).

**Structured diag events** (machines/harnesses): every reflect and page-fetch outcome is appended
as a JSON line to `~/.contextbase/coding-agents-logs/diag.jsonl` (override with
`CONTEXTBASE_DIAG_FILE`):

```json
{
  "ts": "2026-07-27T07:05:52Z",
  "harness": "claude-code",
  "event": "reflect_ok",
  "ms": 14210,
  "chars": 792,
  "query": "..."
}
```

`reflect_failed` / `pages_failed` record the error; if you're comparing memory-on vs memory-off,
check this file — a run whose reflects failed is a no-memory run. When the failure was a timeout or
a 5xx, the hook falls back to knowledge-page search and, if no page matches, to a raw recall of the
bank's memories: `reflect_fallback_pages` / `reflect_fallback_observations` record what each
step returned (`*_failed` when it errored). Seed starts are logged as
`seed_started`.

When `autoInject` names a retrieval source instead of reflect, that source records its own
outcome with the number of items it returned: `inject_pages` for `"pages"`, `inject_recall` for
`"recall"` (`inject_pages_failed` / `inject_recall_failed` when the call errored). No reflect
event is written on those turns — nothing reflected.

**Tool usage** (is the agent using ContextBase?): one JSON line per finished user turn in
`~/.contextbase/coding-agents-logs/usage.jsonl` (override `CONTEXTBASE_USAGE_FILE`) — the `contextbase_*`
tools the agent called during that turn, and whether its reply credited ContextBase memory ("From
ContextBase memory"). The credit rate counts only turns that called a retrieval tool (search, list,
read, reflect); saving a document is not expected to be credited. Recorded at the end of each turn,
whether or not `retainSessions` writes the session back. It never leaves your machine. Summarize it per agent with:

```bash
contextbase-coding-agents stats
```

### Is the memory ready yet?

`contextbase_sync_status` — the agent-facing tool, `dist/status.js` for scripts — answers exactly
that: `"synced": true` means the seeded memory is queryable. It also reports gitlog freshness, how
far per-commit deepening has got, the codebase survey's state (`surveyBaseline` is the HEAD the last
survey started from, `surveyDocs` counts the findings documents that have landed, 0–4 — a baseline
with no findings retries automatically), and the extraction operations still in flight.

### Resetting a repo's memory

Delete its bank on the server. The bank is the **only** state this integration keeps, so the next
session in that repo is a true first open — seed and survey run again from scratch. There are no
client-side files to clean up.

### Marker documents you may notice

Two document ids exist for the machinery's own bookkeeping. Both are safe to ignore and safe to
delete:

- `survey-baseline:<sha>` — reads "🛰️ researching…" while a codebase survey runs and flips to
  "✅ completed" once its findings land. It is retained under the `survey` strategy, whose marker
  rule extracts **nothing** from a status marker, and it drives the re-survey cadence
  (`surveyRefreshCommits`) and `surveyBaseline` in sync status.
- `gitlog:<repo>` — the aggregated commit-message seed document, re-upserted rather than duplicated
  when the seed runs again.

### When memory seems to be missing

Failures never break the agent: a reflect, page fetch or retain that fails degrades to an ordinary
memoryless turn and is recorded in the logs. "No memory" is therefore a log question — check the
diag file for whether `session_start` and `deepen_started` ever fired for that bank. A session that
was already running when the plugin was installed has no SessionStart behind it; its first prompt
after the install self-heals.
