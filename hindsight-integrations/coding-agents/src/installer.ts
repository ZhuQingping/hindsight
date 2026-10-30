#!/usr/bin/env node
/**
 * contextbase-coding-agents install|uninstall [harness...]
 *
 * ONE setup command for every supported coding agent. With no harness arguments it detects which
 * agents exist on this machine (binary on PATH or config dir present) and wires each one's NATIVE
 * integration — hooks + MCP where the host wants them:
 *
 *   opencode     add this package to `plugin` in ~/.config/opencode/opencode.json
 *   claude-code  3 hooks in ~/.claude/settings.json + `claude mcp add` (user scope)
 *   codex        3 hooks in ~/.codex/hooks.json + [features]/[mcp_servers] in config.toml
 *   antigravity-cli PreInvocation + Stop hooks, contextbase status line + MCP
 *   devin-cli     SessionStart + UserPromptSubmit + Stop hooks in ~/.config/devin/config.json + MCP
 *   cursor-cli   sessionStart + beforeSubmitPrompt + stop hooks in ~/.cursor/hooks.json + ~/.cursor/mcp.json
 *   copilot-cli  sessionStart + userPromptTransformed + agentStop hooks in ~/.copilot/hooks/ + MCP
 *   cline-cli    native in-process plugin + MCP
 *   dcode        native Agent Plugin via `dcode plugin marketplace/install`
 *   dsh          native Cordis plugin row in $DSH_HOME/cordis.patch.yml (DeepSeek Harness)
 *
 * IDEMPOTENT: our entries are recognized by the package path in their command ("contextbase-coding-
 * agents"), replaced on re-install (so moving the package just needs `install` again) and removed
 * on `uninstall`. Everything else in the host's config files is preserved; files are created when
 * missing. Backups: the first time we touch an existing file we write `<file>.contextbase-backup`.
 */
import { execFileSync } from "node:child_process";
import {
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readSync,
  realpathSync,
  renameSync,
  statSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { homedir, tmpdir } from "node:os";
import { isatty } from "node:tty";
import { isDeepStrictEqual } from "node:util";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { applyEdits, modify } from "jsonc-parser";
import { parse as parseToml } from "smol-toml";
import { HOOK_HARNESSES, type HookHarnessName } from "./harness/hook-lifecycle";
import { importLocalHistory } from "./core/history";
import { validateRemoteEndpoint } from "./core/connection";
import { isOurMcpEntry } from "./core/util";
import { SKILL_DIRS, resolveSkillDirs, traecodeDotDirName } from "./core/skill-dirs";
import {
  enableWorkspaceMcpSetting,
  gateStateFileFor,
  ensureWorkspaceMcpEnabled,
  markWorkspaceMcpEnabled,
  registerTraecodeWorkspaceMcp,
  removeTraecodeWorkspaceMcpEntry,
  traecodeUserDataDir,
  traecodeWorkspaceStorageDir,
  traecodeUserSettingsPath,
  removeWorkspaceMcpEnabledKeys,
  workspaceMcpGateState,
} from "./core/traecode-mcp";
import { formatUsageReport, readUsage } from "./core/usage";
import { createInstallerUi, type SelectOption } from "./install-ui";

/**
 * Substring that identifies OUR entries in a host's config, so a re-install replaces them and
 * `uninstall` removes exactly what we added.
 *
 * It must appear in the package path under BOTH layouts: npm
 * (`node_modules/contextbase-coding-agents/...`) and a repo checkout
 * (a repository directory named `coding-agents`). The old value was the full package name, which the
 * repo path stopped containing when the directory dropped its `contextbase-` prefix — silently
 * breaking dedupe-on-reinstall and uninstall for anyone running from a checkout.
 */
export const MARKER = "coding-agents";

/** ZCode truncates hook stdout past this many bytes, dropping the injection whole. Its own default;
 *  written only when the user's config does not already carry one. */
const ZCODE_MAX_OUTPUT_BYTES = 32768;

/** ZCode's CLI config — hooks, MCP servers and model routing all live in this one file. */
const zcodeConfigPath = (c: InstallCtx) => join(c.home, ".zcode", "cli", "config.json");

export interface InstallCtx {
  home: string;
  pkgRoot: string; // package root (opencode plugin entry)
  dist: string; // built entry points
  /** Runs `claude mcp ...`; injectable for tests. Returns false when the CLI isn't usable. */
  claudeMcp?: (args: string[]) => boolean;
  /** Runs `qwen mcp ...`; injectable for tests. Returns false when the CLI isn't usable. */
  qwenMcp?: (args: string[]) => boolean;
  /** Runs `cline plugin ...`; injectable for tests. Returns false when the CLI isn't usable. */
  clinePlugin?: (args: string[]) => boolean;
  /** Runs native Dcode plugin commands; injectable for tests. Returns false when unusable. */
  dcodePlugin?: (args: string[]) => boolean;
  /** Reports whether `node:sqlite` works in the node that runs hooks; injectable for tests. */
  nodeSqlite?: () => boolean;
  /** Whether stdin can be prompted. Defaults to the real TTY check at the CLI entry; tests set it
   *  explicitly so the suite never blocks on a read. */
  interactive?: boolean;
  /** The raw CLI arguments after the command word — harness installers read flags off this
   *  (e.g. traecode's --enable-workspace-mcp) without each one re-parsing argv. */
  args?: readonly string[];
  log?: (m: string) => void;
  /** Styles an interactive readLineSync prompt (the CLI passes the InstallerUi rail style). */
  promptStyle?: (q: string) => string;
  /** Arrow-key picker (the CLI passes InstallerUi.select). Chosen index; null = cancelled;
   *  undefined = raw TTY unavailable, fall back to the numeric prompt. */
  selectPrompt?: (
    question: string,
    options: SelectOption[],
    defaultIndex: number
  ) => number | null | undefined;
}

function isPlainObject(value: unknown): value is Record<string, any> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/**
 * JSON.parse accepts non-object top-level values (`[]`, `null`, a number), and every caller here
 * treats the result as an object it can index and merge into — an array config would be written
 * back out as an array, quietly replacing the host's file with something it cannot load. A
 * top-level value that is not a plain object is as broken as an unparseable file, so both fall
 * back to `{}`.
 */
function readJson(path: string): Record<string, any> {
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8"));
    return isPlainObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

/**
 * Parse a JSONC file (JSON with comments), as Kilo's `kilo.jsonc` and opencode's `opencode.jsonc`
 * may be. Applied to `opencode.json` too: comments and trailing commas turn up in the wild under
 * that name as well, and the host reads it either way — so what decides the parser here is the
 * content the installer might meet, not the extension.
 *
 * Returns null — NOT {} — when the file exists but can't be parsed. readJson's {} fallback is safe
 * for a strict-JSON host (an unparseable file is a broken file), but here a config we merely failed
 * to understand must never be overwritten with just our own key: the caller aborts instead.
 */
export function parseJsonc(text: string): Record<string, any> | null {
  const stripped = text
    // Blank out comments, preserving anything inside string literals.
    .replace(/"(?:\\.|[^"\\])*"|\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, (m) => (m[0] === '"' ? m : ""))
    // Trailing commas are legal in JSONC, not in JSON.
    .replace(/,(\s*[}\]])/g, "$1");
  try {
    const v = JSON.parse(stripped);
    return v && typeof v === "object" ? (v as Record<string, any>) : null;
  } catch {
    return null;
  }
}

function writeJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  backupOnce(path);
  writeFileSync(path, JSON.stringify(value, null, 2) + "\n");
}

/** The first time we touch an existing file, keep a copy of what the user had. */
function backupOnce(path: string): void {
  if (existsSync(path) && !existsSync(`${path}.contextbase-backup`)) {
    copyFileSync(path, `${path}.contextbase-backup`);
  }
}

/**
 * Set (or, with `undefined`, delete) ONE top-level key, leaving the rest of the file's text alone.
 *
 * `writeJson` round-trips through `JSON.stringify`, which can only emit strict JSON — so writing a
 * JSONC host's config with it silently strips every comment and trailing comma the user wrote, and
 * reflows their formatting. Parsing the file was only half the problem: even a config we read
 * correctly came back stripped. `jsonc-parser` computes a minimal text edit instead, so everything
 * we did not touch survives byte for byte.
 *
 * Limited to a single key on purpose. A whole-object write is what forces a re-serialize, and both
 * callers only ever mutate `plugin`; a general "merge this object" helper could not preserve
 * anything. Comments INSIDE the edited value are still lost — the array is re-emitted — but the
 * rest of the document, which is all a user notices, is not.
 */
function writeJsonc(path: string, key: string, value: unknown): void {
  const text = existsSync(path) ? readFileSync(path, "utf8") : "";
  const edits = modify(text, [key], value, {
    formattingOptions: {
      tabSize: 2,
      insertSpaces: true,
      // Keep a CRLF file CRLF: rewriting every line ending would turn a one-line change into a
      // whole-file diff for anyone on Windows.
      eol: text.includes("\r\n") ? "\r\n" : "\n",
    },
  });
  const next = applyEdits(text, edits);
  mkdirSync(dirname(path), { recursive: true });
  backupOnce(path);
  writeFileSync(path, next.endsWith("\n") ? next : `${next}\n`);
}

/** Hook-array merge for claude/codex-style files: drop our old entries, append the new one. */
function mergeHookEvent(existing: any[] | undefined, entry: unknown): any[] {
  const kept = (existing ?? []).filter((e) => !JSON.stringify(e).includes(MARKER));
  return [...kept, entry];
}

function stripOurs(existing: any[] | undefined): any[] {
  return (existing ?? []).filter((e) => !JSON.stringify(e).includes(MARKER));
}

/** Remove the event key entirely when nothing else remains (leave the host file tidy). */
function setOrDelete(obj: Record<string, any>, key: string, arr: any[]): void {
  if (arr.length) obj[key] = arr;
  else delete obj[key];
}

const cmdHook = (dist: string, file: string, timeout: number) => ({
  hooks: [{ type: "command", command: `node "${join(dist, file)}"`, timeout }],
});

/** ZCode's registration shape: the same matcher group, but an argv rather than a command STRING —
 *  it spawns hooks without a shell, so `node "…/zcode-hook.js"` would be looked up as one
 *  executable name and never run — and a `timeoutMs` budget rather than `timeout` seconds. */
const processHook = (dist: string, file: string, timeoutMs: number) => ({
  hooks: [{ type: "process", command: "node", args: [join(dist, file)], timeoutMs }],
});

/**
 * The MCP registration for a JSON-configured host.
 *
 * Every harness launches the SAME `dist/mcp-server.js`, so the command line alone cannot say who
 * is calling. `CONTEXTBASE_MCP_HARNESS` is what the server reads to answer that; without it it falls
 * back to "claude-code", which is why a Codex `contextbase_ingest_document` landed tagged
 * `harness:claude-code` (and derived its bank as Claude Code's) on machines running both. Every
 * registration MUST name its own harness — pass it here, never rely on the fallback.
 * `extraArgs` is Cursor-only: Agents Window ignores stdio `cwd`, but interpolates
 * `${workspaceFolder}` in `args`.
 */
const mcpServerEntry = (
  dist: string,
  harness: HookHarnessName | "cline-cli",
  extraArgs: string[] = []
) => ({
  command: "node",
  args: [join(dist, "mcp-server.js"), ...extraArgs],
  env: { CONTEXTBASE_MCP_HARNESS: harness },
});

/** A shared server name is not proof of ownership: keep user-managed remote registrations. */
function preserveMcpEntry(
  c: InstallCtx,
  existing: unknown,
  harness: HookHarnessName | "cline-cli",
  extraArgs: string[] = []
): unknown {
  if (existing !== undefined && !isOurMcpEntry(existing)) {
    c.log?.(
      harness + ": preserved the existing contextbase MCP registration managed outside this plugin"
    );
    return existing;
  }
  return mcpServerEntry(c.dist, harness, extraArgs);
}

/** Install/uninstall consume the same lifecycle declaration as the runtime entrypoints. Keeping
 * event names and command files here would allow a host to run a different lifecycle than it installs. */
function mergeHarnessHooks(
  hooks: Record<string, any>,
  harness: HookHarnessName,
  dist: string
): void {
  const spec = HOOK_HARNESSES[harness];
  // A harness whose hooks live outside the two JSON shapes must never reach the generic
  // writer: the ternary below would silently take the FLAT branch and emit a JSON block
  // into a file that host never reads. tsc cannot catch that, so fail loudly here.
  if (spec.configStyle === "toml-array")
    throw new Error(`${harness} writes its own TOML hook block; mergeHarnessHooks cannot emit it`);

  const installedEvents = new Set<string>();
  for (const hook of [...Object.values(spec.install), ...(spec.additionalHooks ?? [])]) {
    // Antigravity has no SessionStart event. Its first PreInvocation performs the same seed guard,
    // so both conceptual lifecycle names intentionally resolve to one native hook entry.
    if (installedEvents.has(hook.event)) continue;
    installedEvents.add(hook.event);
    const entry =
      spec.configStyle === "nested"
        ? cmdHook(dist, hook.entry, hook.timeout!)
        : spec.configStyle === "process"
          ? processHook(dist, hook.entry, hook.timeout!)
          : {
              command: `node "${join(dist, hook.entry)}"`,
              ...(hook.timeout ? { timeout: hook.timeout } : {}),
            };
    hooks[hook.event] = mergeHookEvent(hooks[hook.event], entry);
  }
}

function stripHarnessHooks(hooks: Record<string, any>, harness: HookHarnessName): void {
  const strippedEvents = new Set<string>();
  const spec = HOOK_HARNESSES[harness];
  for (const hook of [...Object.values(spec.install), ...(spec.additionalHooks ?? [])]) {
    if (strippedEvents.has(hook.event)) continue;
    strippedEvents.add(hook.event);
    setOrDelete(hooks, hook.event, stripOurs(hooks[hook.event]));
  }
}

/** This host's skills directory, from the map core/skill-sync.ts also reads — see SKILL_DIRS for
 *  why the two sides must not keep separate copies of these paths. */
function skillsBaseFor(c: InstallCtx, harness: string): string {
  const parts = resolveSkillDirs(harness, c.home);
  if (!parts) throw new Error(`${harness} installs a skill but names no directory in SKILL_DIRS`);
  return join(c.home, ...parts);
}

/** Copy the packaged companion SKILL into a host's skills directory (idempotent overwrite).
 * The log line carries the harness prefix like every adapter message: several adapters install
 * the skill before their first own log, and an unprefixed line would render under the PREVIOUS
 * harness's group in the CLI output. */
function installSkill(c: InstallCtx, harness: string): void {
  const src = join(c.pkgRoot, "skill");
  if (!existsSync(join(src, "SKILL.md"))) return;
  const skillsBase = skillsBaseFor(c, harness);
  const dst = join(skillsBase, "contextbase-coding-agent");
  mkdirSync(skillsBase, { recursive: true });
  cpSync(src, dst, { recursive: true });
  c.log?.(`${harness}: skill installed at ${dst}`);
}

function uninstallSkill(c: InstallCtx, harness: string): void {
  rmSync(join(skillsBaseFor(c, harness), "contextbase-coding-agent"), {
    recursive: true,
    force: true,
  });
}

// ── per-harness adapters ────────────────────────────────────────────────────────

export interface HarnessInstaller {
  name: string;
  detect(ctx: InstallCtx): boolean;
  /**
   * Blocking environment check, run before anything is written. Returns the reason when this
   * machine cannot support the harness, so a doomed setup fails at install time instead of
   * reporting success and then never retaining anything.
   */
  preflight?(ctx: InstallCtx): string | undefined;
  install(ctx: InstallCtx): void | boolean;
  uninstall(ctx: InstallCtx): void | boolean;
}

function onPath(bin: string): boolean {
  try {
    execFileSync(process.platform === "win32" ? "where.exe" : "which", [bin], { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

function runClinePlugin(args: string[]): boolean {
  try {
    execFileSync("cline", args, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

/**
 * opencode reads its global config from EITHER `opencode.json` or `opencode.jsonc` under
 * `~/.config/opencode`; both names are documented. So the installer must edit the one that is
 * already there: hardcoding `opencode.json` meant a user whose config is `opencode.jsonc` got a
 * SECOND config file created next to their real one — their settings in the file they wrote, our
 * plugin entry in a file they never made.
 *
 * `.jsonc` is probed first because that is the name that carries comments, and a machine holding
 * both is far likelier to have the commented one as the real config.
 */
export const OPENCODE_CONFIG_CANDIDATES = ["opencode.jsonc", "opencode.json"];

function opencodeConfigPath(c: InstallCtx): string {
  const dir = join(c.home, ".config", "opencode");
  const existing = OPENCODE_CONFIG_CANDIDATES.map((f) => join(dir, f)).find((p) => existsSync(p));
  return existing ?? join(dir, "opencode.json");
}

function runDcodePlugin(args: string[]): boolean {
  try {
    execFileSync("dcode", args, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

/**
 * Register/unregister the package root in `~/.config/opencode`'s `plugin` array. Shared verbatim by
 * `opencode` and `opencode2`: the two CLIs read the SAME config file, and v1 REJECTS the whole file
 * on v2's `plugins` key ("Configuration is invalid … Unrecognized key: plugins"), so a v2-specific
 * entry is not an option. One entry serves both because they resolve a plugin directory
 * differently — v1 follows package.json `main` (dist/index.js), v2 loads `<dir>/index.js` — and v2
 * migrates the legacy `plugin` key to `plugins` for itself. See src/opencode2.ts.
 *
 * Consequences worth knowing: installing either harness wires the other one too (the MARKER filter
 * keeps that idempotent), and uninstalling either removes the shared entry.
 */
function registerOpencodePlugin(c: InstallCtx, name: string): void {
  const path = opencodeConfigPath(c);
  let cfg: Record<string, any> = {};
  if (existsSync(path)) {
    const parsed = parseJsonc(readFileSync(path, "utf8"));
    if (!parsed) {
      c.log?.(`${name}: SKIPPED — could not parse ${path}; add the plugin entry manually`);
      return;
    }
    cfg = parsed;
  }
  const plugins: unknown[] = Array.isArray(cfg.plugin) ? cfg.plugin : [];
  // writeJsonc, not writeJson: this config routinely carries comments, and re-serializing the
  // parsed object would strip every one of them even though the read succeeded.
  writeJsonc(path, "plugin", [...plugins.filter((p) => !String(p).includes(MARKER)), c.pkgRoot]);
  c.log?.(`${name}: plugin registered in ${path}`);
}

function unregisterOpencodePlugin(c: InstallCtx, name: string): void {
  const path = opencodeConfigPath(c);
  if (!existsSync(path)) return;
  const cfg = parseJsonc(readFileSync(path, "utf8"));
  if (!cfg || !Array.isArray(cfg.plugin)) return;
  const kept = cfg.plugin.filter((p: unknown) => !String(p).includes(MARKER));
  writeJsonc(path, "plugin", kept.length ? kept : undefined);
  c.log?.(`${name}: plugin entry removed`);
}

const opencode: HarnessInstaller = {
  name: "opencode",
  detect: (c) => onPath("opencode") || existsSync(join(c.home, ".config", "opencode")),
  install: (c) => registerOpencodePlugin(c, "opencode"),
  uninstall: (c) => unregisterOpencodePlugin(c, "opencode"),
};

/**
 * opencode v2: the `opencode2` alias published by npm `@opencode/cli`. The stable package also
 * publishes `opencode`, so a normal global install conflicts with v1's bin; the distinct alias lets
 * installations that expose both commands target the v2 harness explicitly.
 *
 * Detection is the binary only, deliberately NOT `~/.config/opencode`: that directory is v1's too,
 * so keying on it would make `install` (which wires every detected agent) claim opencode2 on every
 * v1-only machine.
 */
const opencode2: HarnessInstaller = {
  name: "opencode2",
  detect: () => onPath("opencode2"),
  install: (c) => registerOpencodePlugin(c, "opencode2"),
  uninstall: (c) => unregisterOpencodePlugin(c, "opencode2"),
};

/**
 * The pi-family extension hosts: pi and its fork Prime Agent (PrimeIntellect). Both load a
 * persistent extension by absolute path from the `extensions` array of their own `settings.json`,
 * calling that file's default export at session start — they differ only in the config directory
 * (`~/.pi/agent` vs `~/.prime/agent`), the executable name, and which dist bundle reports which
 * harness. The entry path runs through the package root, which contains MARKER, so uninstall's
 * MARKER filter removes exactly what install added and leaves every other extension alone.
 *
 * These installs are the ONLY supported route for either host, and the package deliberately carries
 * no `pi` key. Both hosts read that same `pkg.pi.extensions` when this package is installed as a
 * distributed pi package, so it can only ever name one bundle — and the host it did not name would
 * load the other's, reporting the wrong harness, taking that harness's config section and stamping
 * it on every document it retained. It used to name Prime Agent's, which is exactly how pi
 * mis-attributed before it had an entry of its own. A key that is right for at most one of two
 * hosts is worse than none, so there is none; installer.test.ts holds that line.
 *
 * The skills directory (SKILL_DIRS) is per-host rather than shared: both read `~/.agents/skills`
 * too, but that is the root Codex and dsh install into, and uninstallSkill removes by a fixed
 * directory name — so putting ours there would make uninstalling one host delete the other hosts'
 * copy. Each writes its OWN skills directory instead.
 */
function piFamilyInstaller(harness: string, configDir: string[]): HarnessInstaller {
  const settings = (c: InstallCtx) => join(c.home, ...configDir, "settings.json");
  return {
    name: harness,
    // Both hosts name their executable exactly as we name the harness, so the harness id doubles
    // as the PATH probe here — unlike, say, antigravity-cli, whose binary is `agy`.
    detect: (c) => onPath(harness) || existsSync(join(c.home, ...configDir)),
    install(c) {
      const path = settings(c);
      const cfg = readJson(path);
      const entry = join(c.pkgRoot, "dist", `${harness}.js`);
      const exts: string[] = Array.isArray(cfg.extensions) ? cfg.extensions : [];
      cfg.extensions = [...exts.filter((p) => !String(p).includes(MARKER)), entry];
      writeJson(path, cfg);
      installSkill(c, harness);
      c.log?.(`${harness}: extension registered in ${path}`);
    },
    uninstall(c) {
      // Before the settings guard on purpose: a hand-deleted settings.json must not strand the skill.
      uninstallSkill(c, harness);
      const path = settings(c);
      if (!existsSync(path)) return;
      const cfg = readJson(path);
      if (Array.isArray(cfg.extensions)) {
        cfg.extensions = cfg.extensions.filter((p: string) => !String(p).includes(MARKER));
        if (!cfg.extensions.length) delete cfg.extensions;
        writeJson(path, cfg);
      }
      c.log?.(`${harness}: extension entry + skill removed`);
    },
  };
}

const pi = piFamilyInstaller("pi", [".pi", "agent"]);
const primeAgent = piFamilyInstaller("prime-agent", [".prime", "agent"]);

/**
 * Kilo Code CLI — an opencode fork, so registration is opencode's: append our entry to the config's
 * `plugin` array. Two Kilo-specific wrinkles:
 *
 *  - The config may be `kilo.jsonc` OR `kilo.json` (Kilo also honours legacy `opencode.json`). We
 *    edit whichever already exists and only create `kilo.json` when none does — writing a second
 *    file would leave the user with two configs and no obvious winner.
 *  - JSONC allows comments, which JSON.parse rejects. Falling back to `{}` there would overwrite a
 *    real config with just our plugin key, so an unparseable file aborts the install instead.
 *
 * We register `dist/kilo.js` explicitly rather than the package root: the root resolves via
 * package.json main to dist/index.js, which reports the harness as "opencode".
 *
 * The entry MUST be a `file://` URL. Unlike opencode — which accepts a bare filesystem path — Kilo
 * treats a bare absolute path as an npm module specifier, fails to resolve it, and SILENTLY skips
 * the plugin: the session starts normally with no memory and no error anywhere. Verified against
 * Kilo 7.4.17: the same entry loads as `file://…` and is ignored as `/…`.
 */
export const KILO_CONFIG_CANDIDATES = ["kilo.jsonc", "kilo.json", "opencode.json"];

function kiloConfigPath(c: InstallCtx): string {
  const dir = join(c.home, ".config", "kilo");
  const existing = KILO_CONFIG_CANDIDATES.map((f) => join(dir, f)).find((p) => existsSync(p));
  return existing ?? join(dir, "kilo.json");
}

const kilo: HarnessInstaller = {
  name: "kilo",
  detect: (c) => onPath("kilo") || existsSync(join(c.home, ".config", "kilo")),
  install(c) {
    const path = kiloConfigPath(c);
    let cfg: Record<string, any> = {};
    if (existsSync(path)) {
      const parsed = parseJsonc(readFileSync(path, "utf8"));
      if (!parsed) {
        c.log?.(`kilo: SKIPPED — could not parse ${path}; add the plugin entry manually`);
        return;
      }
      cfg = parsed;
    }
    const entry = pathToFileURL(join(c.dist, "kilo.js")).href;
    const plugins: unknown[] = Array.isArray(cfg.plugin) ? cfg.plugin : [];
    // writeJsonc for the same reason the read uses parseJsonc: kilo.jsonc is a commented file, and
    // re-serializing the parsed object would strip what we just took care to read.
    writeJsonc(path, "plugin", [...plugins.filter((p) => !String(p).includes(MARKER)), entry]);
    c.log?.(`kilo: plugin registered in ${path}`);
  },
  uninstall(c) {
    const path = kiloConfigPath(c);
    if (!existsSync(path)) return;
    const cfg = parseJsonc(readFileSync(path, "utf8"));
    if (!cfg || !Array.isArray(cfg.plugin)) return;
    const kept = cfg.plugin.filter((p: unknown) => !String(p).includes(MARKER));
    writeJsonc(path, "plugin", kept.length ? kept : undefined);
    c.log?.("kilo: plugin entry removed");
  },
};

/** User-scoped Claude MCP lives at the top level of .claude.json, not project entries. */
function jsonMcpRegistration(path: string): { readable: boolean; entry: unknown } {
  try {
    const config: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (!config || typeof config !== "object" || Array.isArray(config))
      return { readable: false, entry: undefined };
    const servers = (config as Record<string, unknown>).mcpServers;
    if (servers === undefined) return { readable: true, entry: undefined };
    if (!servers || typeof servers !== "object" || Array.isArray(servers))
      return { readable: false, entry: undefined };
    return { readable: true, entry: (servers as Record<string, unknown>).contextbase };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT")
      return { readable: true, entry: undefined };
    return { readable: false, entry: undefined };
  }
}

function claudeMcpRegistration(c: InstallCtx): { readable: boolean; entry: unknown } {
  return jsonMcpRegistration(join(process.env.CLAUDE_CONFIG_DIR || c.home, ".claude.json"));
}

function codexMcpRegistration(toml: string): { readable: boolean; entry: unknown } {
  try {
    const servers = parseToml(toml).mcp_servers;
    if (servers === undefined) return { readable: true, entry: undefined };
    if (!servers || typeof servers !== "object" || Array.isArray(servers))
      return { readable: false, entry: undefined };
    return { readable: true, entry: (servers as Record<string, unknown>).contextbase };
  } catch {
    return { readable: false, entry: undefined };
  }
}

const claudeCode: HarnessInstaller = {
  name: "claude-code",
  detect: (c) => onPath("claude") || existsSync(join(c.home, ".claude")),
  install(c) {
    const path = join(c.home, ".claude", "settings.json");
    let settings: Record<string, any> = {};
    if (existsSync(path)) {
      try {
        settings = JSON.parse(readFileSync(path, "utf8"));
        if (
          !isPlainObject(settings) ||
          (settings.hooks !== undefined && !isPlainObject(settings.hooks))
        )
          throw new Error("expected a settings object with an optional hooks object");
      } catch (error) {
        c.log?.(`claude-code: could not read settings; existing file preserved: ${String(error)}`);
        return false;
      }
    }
    settings.hooks = settings.hooks ?? {};
    mergeHarnessHooks(settings.hooks, "claude-code", c.dist);
    writeJson(path, settings);
    c.log?.(`claude-code: hooks merged into ${path}`);
    // Companion SKILL: every skills-capable host gets it (claude/antigravity/cursor native dirs;
    // codex via the ~/.agents/skills standard).
    installSkill(c, "claude-code");
    const mcp = c.claudeMcp ?? ((args: string[]) => defaultClaudeMcp(args, c.log));
    const existing = claudeMcpRegistration(c);
    if (!existing.readable || (existing.entry !== undefined && !isOurMcpEntry(existing.entry))) {
      c.log?.(
        "claude-code: preserved the existing contextbase MCP registration managed outside this plugin (or unreadable); register plugin tools under a distinct name if needed"
      );
      return false;
    }
    // Update only our entry atomically: removing it through the CLI first loses a working
    // registration when the subsequent add fails. Preserve custom env and other host settings.
    if (existing.entry !== undefined) {
      const configPath = join(process.env.CLAUDE_CONFIG_DIR || c.home, ".claude.json");
      const text = readFileSync(configPath, "utf8");
      const config = JSON.parse(text);
      const old = config.mcpServers.contextbase;
      if (!isOurMcpEntry(old)) return false;
      const next = {
        ...old,
        args: [resolve(c.dist, "mcp-server.js"), ...old.args.slice(1)],
        env: { ...old.env, CONTEXTBASE_MCP_HARNESS: "claude-code" },
      };
      const updated = applyEdits(text, modify(text, ["mcpServers", "contextbase"], next, {}));
      const temporary = `${configPath}.contextbase-${process.pid}.tmp`;
      let staged = false;
      try {
        backupOnce(configPath);
        writeFileSync(temporary, updated, { mode: 0o600, flag: "wx" });
        staged = true;
        // Do not overwrite settings changed by another process while preparing the update.
        if (readFileSync(configPath, "utf8") !== text)
          throw new Error("Claude config changed during installation; retry after closing Claude");
        renameSync(temporary, configPath);
      } catch (error) {
        c.log?.(
          `claude-code: could not update MCP registration; original retained: ${String(error)}`
        );
        return false;
      } finally {
        if (staged) rmSync(temporary, { force: true });
      }
      c.log?.(
        "claude-code: owned MCP registration updated; other settings and environment preserved"
      );
      return;
    }
    if (
      mcp([
        "mcp",
        "add",
        "--scope",
        "user",
        "--env",
        "CONTEXTBASE_MCP_HARNESS=claude-code",
        "--transport",
        "stdio",
        "contextbase",
        "--",
        "node",
        join(c.dist, "mcp-server.js"),
      ])
    ) {
      c.log?.("claude-code: MCP server registered (claude mcp add, user scope)");
    } else {
      c.log?.(
        `claude-code: could not run \`claude mcp add\` — register the tools manually:\n` +
          `  claude mcp add --scope user --env CONTEXTBASE_MCP_HARNESS=claude-code --transport stdio contextbase -- node "${join(c.dist, "mcp-server.js")}"`
      );
      return false;
    }
  },
  uninstall(c) {
    const path = join(c.home, ".claude", "settings.json");
    if (existsSync(path)) {
      const settings = readJson(path);
      if (settings.hooks) {
        stripHarnessHooks(settings.hooks, "claude-code");
        if (!Object.keys(settings.hooks).length) delete settings.hooks;
        writeJson(path, settings);
      }
    }
    const mcp = c.claudeMcp ?? ((args: string[]) => defaultClaudeMcp(args, c.log));
    const existing = claudeMcpRegistration(c);
    if (existing.readable && isOurMcpEntry(existing.entry)) {
      mcp(["mcp", "remove", "--scope", "user", "contextbase"]);
    } else if (!existing.readable || existing.entry !== undefined) {
      c.log?.(
        "claude-code: preserved the existing contextbase MCP registration managed outside this plugin (or unreadable)"
      );
    }
    uninstallSkill(c, "claude-code");
    c.log?.("claude-code: owned hooks and skill removed; external MCP registrations preserved");
  },
};

export function defaultClaudeMcp(args: string[], log?: (message: string) => void): boolean {
  try {
    if (process.platform === "win32") {
      const candidates = execFileSync("where.exe", ["claude"], { encoding: "utf8" })
        .trim()
        .split(/\r?\n/);
      const executable = candidates.find((file) => /\.exe$/i.test(file));
      if (executable) execFileSync(executable, args, { stdio: "pipe" });
      else {
        // npm's .cmd shim cannot be passed to execFile. Run its JS entry with Node,
        // keeping project paths and arguments out of cmd.exe's shell expansion.
        const entry = candidates
          .flatMap((file) => {
            const root = join(dirname(file), "node_modules", "@anthropic-ai", "claude-code");
            // Current npm releases wrap a native binary; older releases shipped cli.js.
            return [join(root, "cli-wrapper.cjs"), join(root, "cli.js")];
          })
          .find((file) => existsSync(file));
        if (!entry) throw new Error("Claude executable or npm launcher was not found on PATH");
        execFileSync(process.execPath, [entry, ...args], { stdio: "pipe" });
      }
    } else execFileSync("claude", args, { stdio: "pipe" });
    return true;
  } catch (error) {
    const failure = error as {
      stderr?: Buffer | string;
      code?: string;
      status?: number;
      message?: string;
    };
    const detail = failure.stderr?.toString().trim() || failure.message || "unknown error";
    log?.(`claude-code: CLI failed (${failure.code ?? failure.status ?? "error"}): ${detail}`);
    return false;
  }
}

/**
 * Text range for a script-ownership-verified `[mcp_servers.contextbase]` table: the header through to the
 * next table header or EOF. Shared by install — which REPLACES the block — and uninstall.
 */
const CODEX_MCP_BLOCK_RE =
  /^\[mcp_servers\.(?:contextbase|"contextbase"|'contextbase')(?:\.[^\]]+)?\][^\n]*\n(?:(?!\[)[^\n]*\n?)*/gm;

/** Inline `env`, so CODEX_MCP_BLOCK_RE never has to straddle a `[mcp_servers.contextbase.env]` table. */
const codexMcpBlock = (dist: string) =>
  `[mcp_servers.contextbase]\ncommand = "node"\nargs = [${JSON.stringify(join(dist, "mcp-server.js"))}]\n` +
  `env = { CONTEXTBASE_MCP_HARNESS = "codex" }`;

/** Edit only the features table; validate the result before touching the user's file. */
function enableCodexHooks(toml: string): string {
  const parsed = parseToml(toml);
  const features: unknown = parsed.features;
  if (isPlainObject(features) && features.hooks === true) return toml;
  const header = /^[ \t]*\[(?:features|"features"|'features')\][^\n]*(?:\n|$)/m;
  const match = header.exec(toml);
  let next: string;
  if (match) {
    const start = match.index + match[0].length;
    const rest = toml.slice(start);
    const end = rest.search(/^[ \t]*\[/m);
    const body = end < 0 ? rest : rest.slice(0, end);
    const key = /^([ \t]*(?:hooks|"hooks"|'hooks')[ \t]*=[ \t]*)(?:true|false)([^\n]*)$/m;
    const updated = key.test(body) ? body.replace(key, "$1true$2") : `hooks = true\n${body}`;
    next = toml.slice(0, start).replace(/\n?$/, "\n") + updated + (end < 0 ? "" : rest.slice(end));
  } else {
    next = `${toml.replace(/\n*$/, "\n\n")}[features]\nhooks = true\n`;
  }
  const expected = {
    ...parsed,
    features: { ...(isPlainObject(parsed.features) ? parsed.features : {}), hooks: true },
  };
  // Unusual TOML forms (inline/dotted tables or multiline strings) must never be
  // silently rewritten incorrectly. Leave them intact and report a failed install.
  if (
    !isDeepStrictEqual(
      JSON.parse(JSON.stringify(parseToml(next))),
      JSON.parse(JSON.stringify(expected))
    )
  ) {
    throw new Error("could not safely enable [features].hooks; set hooks = true and retry");
  }
  return next;
}

const codex: HarnessInstaller = {
  name: "codex",
  detect: (c) => onPath("codex") || existsSync(join(c.home, ".codex")),
  install(c) {
    const hooksPath = join(c.home, ".codex", "hooks.json");
    const cfg = readJson(hooksPath);
    cfg.hooks = cfg.hooks ?? {};
    mergeHarnessHooks(cfg.hooks, "codex", c.dist);
    writeJson(hooksPath, cfg);
    c.log?.(`codex: hooks merged into ${hooksPath}`);

    // config.toml: append-only for anything that is not ours (TOML round-tripping is not worth the
    // risk). Our OWN mcp block is stripped and rewritten instead of skipped when present: appending
    // only when absent made this install-once-only, so the harness-less registration that
    // attributed every Codex write to claude-code could never be repaired by re-running install.
    const tomlPath = join(c.home, ".codex", "config.toml");
    const existing = existsSync(tomlPath) ? readFileSync(tomlPath, "utf8") : "";
    const registration = codexMcpRegistration(existing);
    if (!registration.readable) {
      c.log?.("codex: could not inspect config.toml; MCP configuration preserved");
      installSkill(c, "codex");
      return false;
    }
    const owned = isOurMcpEntry(registration.entry);
    const foreign = registration.entry !== undefined && !owned;
    let toml = owned ? existing.replace(CODEX_MCP_BLOCK_RE, "") : existing;
    if (owned && toml === existing) {
      c.log?.(
        "codex: could not isolate the owned MCP table; configuration preserved, update it manually"
      );
      installSkill(c, "codex");
      return false;
    }
    if (foreign)
      c.log?.(
        "codex: preserved the existing contextbase MCP registration managed outside this plugin"
      );
    const additions: string[] = [];
    try {
      toml = enableCodexHooks(toml);
    } catch (error) {
      c.log?.(`codex: ${(error as Error).message}; config.toml preserved`);
      return false;
    }
    if (!foreign) additions.push(codexMcpBlock(c.dist));
    const next = additions.length
      ? `${toml.replace(/\n*$/, "\n\n")}${additions.join("\n\n")}\n`
      : toml;
    if (next !== existing) {
      if (existsSync(tomlPath) && !existsSync(`${tomlPath}.contextbase-backup`)) {
        copyFileSync(tomlPath, `${tomlPath}.contextbase-backup`);
      }
      mkdirSync(dirname(tomlPath), { recursive: true });
      writeFileSync(tomlPath, next);
      c.log?.(`codex: wrote ${additions.length} section(s) to ${tomlPath}`);
    }
    installSkill(c, "codex"); // agentskills-standard shared dir
    if (foreign) return false;
  },
  uninstall(c) {
    const hooksPath = join(c.home, ".codex", "hooks.json");
    if (existsSync(hooksPath)) {
      const cfg = readJson(hooksPath);
      if (cfg.hooks) {
        stripHarnessHooks(cfg.hooks, "codex");
        writeJson(hooksPath, cfg);
      }
    }
    uninstallSkill(c, "codex");
    const tomlPath = join(c.home, ".codex", "config.toml");
    if (existsSync(tomlPath)) {
      const toml = readFileSync(tomlPath, "utf8");
      const registration = codexMcpRegistration(toml);
      if (registration.readable && isOurMcpEntry(registration.entry)) {
        const cleaned = toml.replace(CODEX_MCP_BLOCK_RE, "");
        if (cleaned !== toml) writeFileSync(tomlPath, cleaned);
        else c.log?.("codex: could not isolate the owned MCP table; configuration preserved");
      } else if (!registration.readable || registration.entry !== undefined) {
        c.log?.(
          "codex: preserved the existing contextbase MCP registration managed outside this plugin (or unreadable)"
        );
      }
    }
    c.log?.(
      "codex: hooks + MCP section + skill removed ([features] hooks flag left as-is — other hooks may use it)"
    );
  },
};

const antigravity: HarnessInstaller = {
  name: "antigravity-cli",
  // `agy` is the supported Antigravity CLI executable.  Do not infer support from the
  // legacy Gemini CLI's ~/.gemini state: both clients may leave files there, but only agy
  // can consume this integration.
  detect: (c) => onPath("agy"),
  install(c) {
    const hooksPath = join(c.home, ".gemini", "config", "hooks.json");
    const hooks = readJson(hooksPath);
    // Antigravity's hooks.json is a map of named customizations, not a direct event map. Keep
    // contextbase in its own namespace so it cannot collide with other global hook bundles.
    // Drop any namespace we wrote under a PREVIOUS marker value. This file is keyed BY the marker,
    // so unlike every other host — where entries are matched by substring — a changed marker
    // orphans the old namespace instead of replacing it, leaving both registered and every hook
    // firing twice. Match on our own name rather than an exact string so past and future renames
    // are both cleaned up.
    for (const key of Object.keys(hooks)) {
      if (key !== MARKER && key.includes(MARKER)) delete hooks[key];
    }
    hooks[MARKER] = hooks[MARKER] ?? {};
    mergeHarnessHooks(hooks[MARKER], "antigravity-cli", c.dist);
    // Clean up the short-lived root-level shape written by the first Antigravity adapter release.
    // stripOurs only removes commands bearing our marker, preserving a user's own root hooks.
    for (const event of ["PreInvocation", "Stop"]) {
      setOrDelete(hooks, event, stripOurs(hooks[event]));
    }
    writeJson(hooksPath, hooks);
    const mcpPath = join(c.home, ".gemini", "config", "mcp_config.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "antigravity-cli"),
    };
    writeJson(mcpPath, mcp);
    const settingsPath = join(c.home, ".gemini", "antigravity-cli", "settings.json");
    const settings = readJson(settingsPath);
    // A custom status-line command owns the whole rendered line. Do not overwrite a user's
    // formatter; contextbase can only add its native indicator when no formatter is already set.
    if (!settings.statusLine) {
      settings.statusLine = {
        type: "command",
        command: `node "${join(c.dist, "antigravity-statusline.js")}"`,
      };
      writeJson(settingsPath, settings);
      c.log?.(`antigravity-cli: contextbase status line enabled in ${settingsPath}`);
    } else if (JSON.stringify(settings.statusLine).includes(MARKER)) {
      settings.statusLine = {
        type: "command",
        command: `node "${join(c.dist, "antigravity-statusline.js")}"`,
      };
      writeJson(settingsPath, settings);
    } else {
      c.log?.(
        "antigravity-cli: existing custom status line preserved (contextbase indicator not added)"
      );
    }
    c.log?.(`antigravity-cli: hooks merged into ${hooksPath}, MCP into ${mcpPath}`);
    installSkill(c, "antigravity-cli");
  },
  uninstall(c) {
    const hooksPath = join(c.home, ".gemini", "config", "hooks.json");
    if (existsSync(hooksPath)) {
      const hooks = readJson(hooksPath);
      if (hooks[MARKER]) {
        stripHarnessHooks(hooks[MARKER], "antigravity-cli");
        if (!Object.keys(hooks[MARKER]).length) delete hooks[MARKER];
      }
      // Also remove any root-level entries from the first adapter release.
      for (const event of ["PreInvocation", "Stop"]) {
        setOrDelete(hooks, event, stripOurs(hooks[event]));
      }
      writeJson(hooksPath, hooks);
    }
    const mcpPath = join(c.home, ".gemini", "config", "mcp_config.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    const settingsPath = join(c.home, ".gemini", "antigravity-cli", "settings.json");
    if (existsSync(settingsPath)) {
      const settings = readJson(settingsPath);
      if (JSON.stringify(settings.statusLine ?? {}).includes(MARKER)) {
        delete settings.statusLine;
        writeJson(settingsPath, settings);
      }
    }
    uninstallSkill(c, "antigravity-cli");
    c.log?.("antigravity-cli: hooks + MCP entry + status line + skill removed");
  },
};

/**
 * Probe the `node` on PATH — not this process — because that is the interpreter the installed hook
 * command (`node "<dist>/devin-stop-hook.js"`) will actually run under. An installer started through
 * npx, a version manager or a wrapper script is easily a different build than the one the agent
 * later uses. `-e` runs as CommonJS regardless of the surrounding package type, so `require` here
 * is safe.
 */
function pathNodeHasSqlite(): boolean {
  try {
    execFileSync("node", ["-e", "require('node:sqlite')"], { stdio: "pipe", timeout: 10_000 });
    return true;
  } catch {
    return false;
  }
}

function pathNodeVersion(): string {
  try {
    return execFileSync("node", ["-v"], { encoding: "utf8", stdio: "pipe" }).trim();
  } catch {
    return "not found";
  }
}

// ── runtime staging ─────────────────────────────────────────────────────────────

/**
 * Where the runtime is copied to, and therefore what every hook command points at.
 *
 * Under ~/.contextbase, which this package already owns (the config file lives there), and named
 * `coding-agents` on purpose: MARKER matching is what lets a re-install replace our entries and
 * `uninstall` remove them, and it looks for exactly that substring in the command path.
 */
export function runtimeDir(home: string): string {
  return join(home, ".contextbase", "coding-agents");
}

/** Names the directory `stageRuntime` copied from — read by core/auto-update.ts. */
export const ORIGIN_FILE = ".install-origin.json";

/**
 * Copy the runtime out of wherever this was executed from and into a stable location, then point
 * the wiring at the copy.
 *
 * Both fields matter: `dist` is baked into every hook command and MCP registration, and `pkgRoot`
 * is what opencode and Kilo load as a plugin directory. Repointing them here means no per-harness
 * installer needs to know staging happened.
 *
 * Copying is skipped when there is nothing to copy — running from a checkout whose dist has not
 * been built, and in tests — so the wiring falls back to the source path rather than a directory
 * that does not exist. It is also skipped when already running from the staged copy, which is what
 * makes re-running `install` cheap.
 */
function stageRuntime(c: InstallCtx): InstallCtx {
  const target = runtimeDir(c.home);
  // Compared through realpath: re-running the STAGED installer must not reach the copy below, which
  // deletes the very dist it is executing from. A symlinked or differently-spelled path to the same
  // directory would slip past a string compare.
  const same = (a: string, b: string): boolean => {
    try {
      return realpathSync(a) === realpathSync(b);
    } catch {
      return a === b;
    }
  };
  if (same(c.pkgRoot, target)) return c;
  if (!existsSync(join(c.dist, "installer.js"))) return c;
  try {
    // Replaced wholesale rather than merged: a stale entry point left behind by an older version
    // would still be reachable from a host config that references it by name.
    rmSync(join(target, "dist"), { recursive: true, force: true });
    mkdirSync(target, { recursive: true });
    cpSync(c.dist, join(target, "dist"), { recursive: true });
    const skill = join(c.pkgRoot, "skill");
    if (existsSync(skill)) cpSync(skill, join(target, "skill"), { recursive: true });
    const pkgJson = join(c.pkgRoot, "package.json");
    if (existsSync(pkgJson)) copyFileSync(pkgJson, join(target, "package.json"));
    // The Dcode Agent Plugin surface (its manifest and the hooks that manifest points at) plus the
    // root index.js opencode2 loads a plugin directory from — see src/opencode2.ts. Without that
    // file here, the staged copy is a v1-only plugin and opencode2 logs "configured plugin
    // directory has no index entrypoint".
    // (All are listed in package.json#files, so they exist in a published install too.)
    for (const resource of ["plugin.json", "hooks", "index.js", "LICENSE"]) {
      const source = join(c.pkgRoot, resource);
      if (existsSync(source)) cpSync(source, join(target, resource), { recursive: true });
    }
    // Record WHERE this copy came from, LAST — the marker means "a complete copy landed here".
    // core/auto-update.ts will only replace a runtime it can prove was downloaded by npx: a copy
    // staged from a global `npm i -g`, a project dependency or a local checkout belongs to whoever
    // manages that source, and silently overwriting it would either fight their package manager
    // (leaving `npm ls -g` reporting a version that is no longer what runs) or destroy a
    // developer's locally-built dist.
    writeFileSync(
      join(target, ORIGIN_FILE),
      JSON.stringify({ source: c.pkgRoot, stagedAt: new Date().toISOString() })
    );
    c.log?.(`runtime staged at ${target}`);
    return { ...c, pkgRoot: target, dist: join(target, "dist") };
  } catch (error) {
    // A failed copy must not wire hooks at a half-written directory.
    c.log?.(`could not stage the runtime at ${target}: ${String(error)}`);
    return c;
  }
}

// ── remote service setup ───────────────────────────

export type ServerMode = "cloud" | "self-hosted";

const SERVER_MODES: ServerMode[] = ["cloud", "self-hosted"];

/** Value of `--name value` or `--name=value`. */
export function flagValue(args: string[], name: string): string | undefined {
  const inline = args.find((a) => a.startsWith(`--${name}=`));
  if (inline) return inline.slice(name.length + 3);
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : undefined;
}

/** Args that are VALUES of a preceding flag, so they aren't mistaken for harness names. */
export function flagValueArgs(args: string[], names: string[]): Set<string> {
  const taken = new Set<string>();
  for (const name of names) {
    const i = args.indexOf(`--${name}`);
    if (i >= 0 && args[i + 1] && !args[i + 1].startsWith("--")) taken.add(args[i + 1]);
  }
  return taken;
}

const CONFIG_RELATIVE = [".contextbase", "coding-agent.json"];
/** The runtime resolves its config as CONTEXTBASE_CONFIG || ~/.contextbase/coding-agent.json
 *  (core/config.ts CONFIG_PATH); every installer read/write must honor the same override. */
const contextbaseConfigPath = (c: InstallCtx): string =>
  process.env.CONTEXTBASE_CONFIG || join(c.home, ...CONFIG_RELATIVE);

/**
 * Read one line from stdin synchronously.
 *
 * `run()` is synchronous and called that way from both the CLI entry and the test suite, so an
 * async readline would mean making the whole installer async. readSync on the TTY blocks until
 * Enter, which is exactly the semantics wanted here.
 */
function readLineSync(c: InstallCtx, prompt: string): string {
  process.stdout.write((c.promptStyle ?? ((s: string) => s))(prompt));
  const buf = Buffer.alloc(1024);
  // Touching process.stdin ANYWHERE flips a TTY fd 0 to non-blocking (its getter initializes the
  // TTY stream), after which readSync throws EAGAIN instead of waiting for Enter. The old
  // blanket catch treated that as "no stdin" — so the picker printed its menu and every answer
  // silently became the default. The CLI entry now probes the TTY with tty.isatty (no stream
  // init), and EAGAIN here waits for input rather than fabricating an empty answer.
  for (;;) {
    try {
      const n = readSync(0, buf, 0, buf.length, null);
      return buf.subarray(0, n).toString("utf8");
    } catch (e) {
      if ((e as NodeJS.ErrnoException).code !== "EAGAIN") {
        return ""; // genuinely no readable stdin — treated as the default
      }
      // Sleep 50ms without spinning; Atomics.wait is allowed on Node's main thread.
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50);
    }
  }
}

/** Persist the single remote connection before changing any host registration. */
function configureServer(c: InstallCtx, args: string[]): boolean {
  const explicit = flagValue(args, "server");
  if (explicit && !SERVER_MODES.includes(explicit as ServerMode)) {
    c.log?.(
      "Only remote services are supported; use --api-url <API Endpoint>. Local engines are not distributed."
    );
    return false;
  }
  const configPath = contextbaseConfigPath(c);
  let existing: Record<string, any> = {};
  try {
    if (existsSync(configPath)) existing = JSON.parse(readFileSync(configPath, "utf8"));
    if (!isPlainObject(existing)) throw new Error("expected a JSON object");
  } catch {
    c.log?.(`server: invalid config at ${configPath}; fix it before installing`);
    return false;
  }
  const bankId = flagValue(args, "bank-id");
  const projectPath = flagValue(args, "project-path");
  if (
    (projectPath !== undefined && bankId === undefined) ||
    (bankId !== undefined && !bankId.trim())
  ) {
    c.log?.("server: --project-path requires a non-empty --bank-id");
    return false;
  }
  let project: string | undefined;
  if (bankId !== undefined) {
    try {
      project = realpathSync(resolve(projectPath ?? process.cwd()));
      if (!statSync(project).isDirectory()) throw new Error("not a directory");
    } catch {
      c.log?.("server: --project-path must name an existing project directory");
      return false;
    }
  }
  if (!explicit && existing.serverMode === "daemon") {
    c.log?.(
      "Local engine mode is not supported. Configure --server cloud --api-url <API Endpoint>."
    );
    return false;
  }
  const url =
    flagValue(args, "api-url") ??
    existing.apiUrl ??
    process.env.CONTEXTBASE_API_URL ??
    (c.interactive ? readLineSync(c, "API Endpoint from your console (required): ").trim() : "");
  let apiUrl: string;
  try {
    apiUrl = validateRemoteEndpoint(typeof url === "string" ? url : "");
  } catch (error) {
    c.log?.(`server: ${(error as Error).message}`);
    return false;
  }
  // Never carry a stored credential to a different endpoint without explicit configuration.
  const sameEndpoint =
    typeof existing.apiUrl === "string" && existing.apiUrl.replace(/\/+$/, "") === apiUrl;
  const token =
    flagValue(args, "api-token") ??
    (sameEndpoint ? existing.apiToken : undefined) ??
    process.env.CONTEXTBASE_API_TOKEN ??
    process.env.CONTEXTBASE_API_KEY;
  const next: Record<string, unknown> = { ...existing, serverMode: explicit ?? "cloud", apiUrl };
  delete next.apiToken;
  if (typeof token === "string" && token.trim()) next.apiToken = token.trim();
  // Credentials may be supplied later through the user's secret manager; never prompt with echo.
  if (!next.apiToken)
    c.log?.("server: configure apiToken or CONTEXTBASE_API_TOKEN before authenticated requests.");
  if (bankId !== undefined && project) {
    next.mapPathToBank = { ...existing.mapPathToBank, [project]: bankId.trim() };
    // Bank binding must not change the user's global opt-in policy.
    c.log?.(`server: optInOnly=${next.optInOnly ?? false} (unchanged)`);
    // The service owns this pre-provisioned bank. Ordinary customer keys can retain
    // and recall but cannot import bank configuration or create knowledge pages.
    const bankSettings = {
      ...existing.banks?.[bankId.trim()],
      manageBankConfig: false,
      autoSeed: false,
      codebaseSurvey: false,
    };
    // An old bank alias must not redirect an explicitly selected Workspace.
    delete bankSettings.bank;
    next.banks = { ...existing.banks, [bankId.trim()]: bankSettings };
    c.log?.(`server: project ${project} bound to bank ${bankId.trim()} (service-managed)`);
    c.log?.(
      "server: user-wide installation and API credentials; Bank routing is per project, existing project mappings preserved"
    );
  }
  writeJson(configPath, next);
  c.log?.(`server: remote connection (${configPath})`);
  return true;
}

const devin: HarnessInstaller = {
  name: "devin-cli",
  detect: (c) => onPath("devin") || existsSync(join(c.home, ".config", "devin")),
  // Devin is the ONLY harness whose hooks never hand over a transcript: they carry a session id and
  // nothing else, so retain can only work by reading the CLI's own sessions.db. That makes SQLite
  // support a hard prerequisite here — and one worth checking now, because the alternative is an
  // install that looks perfectly healthy and stores nothing, forever (#3125).
  preflight(c) {
    if ((c.nodeSqlite ?? pathNodeHasSqlite)()) return undefined;
    return (
      `\`node:sqlite\` is unavailable in the \`node\` on PATH (${pathNodeVersion()}).\n` +
      `   Devin keeps its conversations in ~/.local/share/devin/cli/sessions.db and its hooks pass\n` +
      `   only a session id, so without SQLite nothing could ever be retained.\n` +
      `   Upgrade to Node 22.5 or newer (24 LTS recommended) and re-run this command.`
    );
  },
  install(c) {
    const configPath = join(c.home, ".config", "devin", "config.json");
    const config = readJson(configPath);
    config.hooks = config.hooks ?? {};
    mergeHarnessHooks(config.hooks, "devin-cli", c.dist);
    writeJson(configPath, config);
    const mcpPath = join(c.home, ".config", "devin", "mcp_config.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "devin-cli"),
    };
    writeJson(mcpPath, mcp);
    c.log?.(`devin-cli: hooks merged into ${configPath}, MCP into ${mcpPath}`);
  },
  uninstall(c) {
    const configPath = join(c.home, ".config", "devin", "config.json");
    if (existsSync(configPath)) {
      const config = readJson(configPath);
      if (config.hooks) {
        stripHarnessHooks(config.hooks, "devin-cli");
        if (!Object.keys(config.hooks).length) delete config.hooks;
        writeJson(configPath, config);
      }
    }
    const mcpPath = join(c.home, ".config", "devin", "mcp_config.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    c.log?.("devin-cli: hooks + MCP entry removed");
  },
};

const cursor: HarnessInstaller = {
  name: "cursor-cli",
  detect: (c) => onPath("cursor-agent") || existsSync(join(c.home, ".cursor")),
  install(c) {
    const hooksPath = join(c.home, ".cursor", "hooks.json");
    const cfg = readJson(hooksPath);
    // Cursor's hooks.json schema requires a top-level `version`. Without it the
    // Customize > Hooks view silently drops every entry (the hooks still run).
    // The Python cursor-cli installer already setdefault's this; this adapter
    // used to write only `hooks` and so produced a file the UI would not list.
    cfg.version ??= 1;
    cfg.hooks = cfg.hooks ?? {};
    mergeHarnessHooks(cfg.hooks, "cursor-cli", c.dist);
    writeJson(hooksPath, cfg);
    const mcpPath = join(c.home, ".cursor", "mcp.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "cursor-cli", [
        "${workspaceFolder}",
      ]),
    };
    writeJson(mcpPath, mcp);
    c.log?.(`cursor-cli: hooks merged into ${hooksPath}, MCP into ${mcpPath}`);
    installSkill(c, "cursor-cli");
  },
  uninstall(c) {
    const hooksPath = join(c.home, ".cursor", "hooks.json");
    if (existsSync(hooksPath)) {
      const cfg = readJson(hooksPath);
      if (cfg.hooks) {
        stripHarnessHooks(cfg.hooks, "cursor-cli");
        if (!Object.keys(cfg.hooks).length) delete cfg.hooks;
        writeJson(hooksPath, cfg);
      }
    }
    const mcpPath = join(c.home, ".cursor", "mcp.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    uninstallSkill(c, "cursor-cli");
    c.log?.("cursor-cli: hooks + MCP entry + skill removed");
  },
};

const copilot: HarnessInstaller = {
  name: "copilot-cli",
  detect: (c) => onPath("copilot") || existsSync(join(c.home, ".copilot")),
  install(c) {
    const hooksPath = join(c.home, ".copilot", "hooks", "contextbase-coding-agents.json");
    const hooks: Record<string, any> = {};
    mergeHarnessHooks(hooks, "copilot-cli", c.dist);
    writeJson(hooksPath, { version: 1, hooks });

    const mcpPath = join(c.home, ".copilot", "mcp-config.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "copilot-cli"),
    };
    writeJson(mcpPath, mcp);
    installSkill(c, "copilot-cli");
    c.log?.(`copilot-cli: hooks installed at ${hooksPath}, MCP into ${mcpPath}`);
  },
  uninstall(c) {
    rmSync(join(c.home, ".copilot", "hooks", "contextbase-coding-agents.json"), {
      force: true,
    });
    const mcpPath = join(c.home, ".copilot", "mcp-config.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    uninstallSkill(c, "copilot-cli");
    c.log?.("copilot-cli: hooks + MCP entry + skill removed");
  },
};

const GROK_MARKER_START = "# CONTEXTBASE_CODING_AGENTS_GROK_START";
const GROK_MARKER_END = "# CONTEXTBASE_CODING_AGENTS_GROK_END";
/** Our sentinel-delimited block; shared by install (replace) and uninstall (strip). */
const GROK_BLOCK_RE = new RegExp(`\\n?${GROK_MARKER_START}[\\s\\S]*?${GROK_MARKER_END}\\n?`, "g");

/** Hook scripts only this package writes; their basenames identify our entries in a foreign TOML. */
const GROK_HOOK_SCRIPT_RE = /(grok-(?:sessionstart-|stop-)?hook\.js|contextbase-coding-agents)/;

/** The slice of Grok's config.toml this installer touches. */
interface GrokToml {
  mcp_servers?: Record<string, unknown>;
  hooks?: Record<string, { hooks?: { command?: unknown }[] }[]>;
}

/** Parse config.toml, or null when it is malformed — including the duplicate-key state this repairs. */
function parseGrokToml(text: string): GrokToml | null {
  try {
    return parseToml(text) as GrokToml;
  } catch {
    return null;
  }
}

/**
 * Does the config still declare contextbase entries outside our markers?
 *
 * Decided from the PARSED document, so a `[mcp_servers.contextbase]` written in any legal TOML
 * spelling (dotted key, inline table, `[mcp_servers]` with a `contextbase` sub-table) is recognized —
 * not just the exact text an old release happened to emit. Only the `[table]` form is removed
 * automatically; any other spelling survives the strip and the install's final parse refuses to
 * write, telling the user to remove it. Falls back to a textual probe only when the file no longer
 * parses, which is precisely the broken state we are repairing.
 */
function hasUnmarkedGrokEntries(text: string): boolean {
  const cfg = parseGrokToml(text);
  if (!cfg)
    return (
      /\[\s*mcp_servers\s*\.\s*contextbase\s*[.\]]/.test(text) || GROK_HOOK_SCRIPT_RE.test(text)
    );
  if (cfg.mcp_servers && "contextbase" in cfg.mcp_servers) return true;
  return Object.values(cfg.hooks ?? {}).some((entries) =>
    (entries ?? []).some((entry) =>
      (entry?.hooks ?? []).some(
        (h) => typeof h?.command === "string" && GROK_HOOK_SCRIPT_RE.test(h.command)
      )
    )
  );
}

/**
 * Remove contextbase's Grok tables that are NOT wrapped in our markers.
 *
 * Configs written before the markers existed (or hand-edited so the markers were lost) keep a
 * `[mcp_servers.contextbase]` table and `[[hooks.*]]` entries pointing at our scripts. TOML forbids
 * redefining a table, so appending a fresh marked block on top of those makes the whole file
 * unparsable — Grok then reports "No MCP servers configured" and silently disables every server.
 *
 * The edit is textual on purpose: re-serializing the parsed document would drop the comments,
 * ordering and formatting of a config the user maintains by hand. The caller validates the result
 * with the parser before writing it.
 */
function stripUnmarkedGrokEntries(toml: string): string {
  const lines = toml.split("\n");
  // Split into table sections: a header line plus everything up to the next header.
  const sections: { header: string; lines: string[] }[] = [{ header: "", lines: [] }];
  for (const line of lines) {
    if (/^\s*\[/.test(line)) sections.push({ header: line.trim(), lines: [line] });
    else sections[sections.length - 1].lines.push(line);
  }

  const isOurs = (s: { header: string; lines: string[] }) =>
    s.lines.some((l) => /^\s*(command|args)\s*=/.test(l) && GROK_HOOK_SCRIPT_RE.test(l));
  const hasKeys = (s: { header: string; lines: string[] }) =>
    s.lines.slice(1).some((l) => /^\s*[^#\s]/.test(l));

  const drop = sections.map((s) => {
    if (/^\[mcp_servers\.contextbase(\.|\])/.test(s.header)) return true;
    if (/^\[\[hooks\..+\.hooks\]\]$/.test(s.header)) return isOurs(s);
    return false;
  });
  // A bare `[[hooks.X]]` parent carries no keys of its own; drop it once all its children are gone.
  for (let i = 0; i < sections.length; i++) {
    if (!/^\[\[hooks\.[^.\]]+\]\]$/.test(sections[i].header) || hasKeys(sections[i])) continue;
    let j = i + 1;
    let sawChild = false;
    while (j < sections.length && /^\[\[hooks\..+\.hooks\]\]$/.test(sections[j].header)) {
      if (!drop[j]) break;
      sawChild = true;
      j++;
    }
    const childrenAllDropped =
      sawChild && (j >= sections.length || !/^\[\[hooks\..+\.hooks\]\]$/.test(sections[j].header));
    if (childrenAllDropped) drop[i] = true;
  }

  if (!drop.some(Boolean)) return toml;
  return sections
    .filter((_, i) => !drop[i])
    .map((s) => s.lines.join("\n"))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n");
}

/**
 * Grok Build reads hooks from `~/.grok/hooks/*.json` (Claude's nested matcher-group shape) and
 * from `[[hooks.<Event>]]` tables in config.toml. Both load, but Grok's config validator does not
 * know the `hooks` key, so every `grok inspect` flags a config.toml hook block as an
 * "unrecognized config key". The hooks directory is the documented global location and draws no
 * warning, so the hooks live in a file this package owns; config.toml keeps only the MCP server.
 */
const grokHooksPath = (c: InstallCtx) => join(c.home, ".grok", "hooks", "contextbase.json");

const grok: HarnessInstaller = {
  name: "grok-build",
  detect: (c) => onPath("grok") || existsSync(join(c.home, ".grok")),
  install(c) {
    const path = join(c.home, ".grok", "config.toml");
    const existing = existsSync(path) ? readFileSync(path, "utf8") : "";
    // REPLACE any previous block rather than skipping when one exists. Skipping made this
    // install-once-only: after the package moved, a re-install silently left the old (now dead)
    // paths in place, which is exactly the case `install` is meant to repair. Replacing also
    // drops the hook tables older releases kept in this block.
    const stripped = existing.replace(GROK_BLOCK_RE, "\n");
    // Entries an older release wrote WITHOUT the markers must go too: TOML forbids redefining a
    // table, so appending on top of them leaves a file Grok cannot parse — it then reports "No MCP
    // servers configured" and every MCP server, ours included, silently stops working.
    const withoutOurs = hasUnmarkedGrokEntries(stripped)
      ? stripUnmarkedGrokEntries(stripped)
      : stripped;
    const tomlString = (value: string) => JSON.stringify(value);
    const block =
      `\n${GROK_MARKER_START}\n` +
      `[mcp_servers.contextbase]\ncommand = \"node\"\nargs = [${tomlString(join(c.dist, "mcp-server.js"))}]\n` +
      `env = { CONTEXTBASE_MCP_HARNESS = \"grok-build\" }\n${GROK_MARKER_END}\n`;
    const next = `${withoutOurs.replace(/\n*$/, "\n")}${block}`;
    // Never hand Grok a config it cannot parse: one bad table takes down every MCP server it has.
    if (parseGrokToml(next) === null) {
      c.log?.(
        `grok-build: refusing to write ${path} — the result would not be valid TOML. ` +
          `Remove the contextbase hooks and [mcp_servers.contextbase] from it by hand, then re-run install.`
      );
      return false;
    }
    if (existsSync(path) && !existsSync(`${path}.contextbase-backup`))
      copyFileSync(path, `${path}.contextbase-backup`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, next);

    const hooksPath = grokHooksPath(c);
    const file = readJson(hooksPath);
    const hooks = isPlainObject(file.hooks) ? file.hooks : {};
    mergeHarnessHooks(hooks, "grok-build", c.dist);
    writeJson(hooksPath, { ...file, hooks });
    installSkill(c, "grok-build");
    c.log?.(`grok-build: hooks installed in ${hooksPath}, MCP in ${path}`);
  },
  uninstall(c) {
    const path = join(c.home, ".grok", "config.toml");
    if (existsSync(path)) {
      const existing = readFileSync(path, "utf8");
      const stripped = existing.replace(GROK_BLOCK_RE, "\n");
      const cleaned = hasUnmarkedGrokEntries(stripped)
        ? stripUnmarkedGrokEntries(stripped)
        : stripped;
      // Write when the removal leaves valid TOML — or when the file was already invalid, since
      // dropping our entries cannot make that worse and is usually what repairs it.
      const safe = parseGrokToml(cleaned) !== null || parseGrokToml(existing) === null;
      if (cleaned !== existing && safe) writeFileSync(path, cleaned);
    }
    const hooksPath = grokHooksPath(c);
    if (existsSync(hooksPath)) {
      const file = readJson(hooksPath);
      if (isPlainObject(file.hooks)) {
        stripHarnessHooks(file.hooks, "grok-build");
        if (!Object.keys(file.hooks).length) delete file.hooks;
      }
      if (Object.keys(file).length) writeJson(hooksPath, file);
      else rmSync(hooksPath);
    }
    uninstallSkill(c, "grok-build");
    c.log?.("grok-build: native hooks + MCP + skill removed");
  },
};

const KIMI_MARKER_START = "# CONTEXTBASE_CODING_AGENTS_KIMI_START";
const KIMI_MARKER_END = "# CONTEXTBASE_CODING_AGENTS_KIMI_END";
const KIMI_BLOCK_RE = new RegExp(`\\n?${KIMI_MARKER_START}[\\s\\S]*?${KIMI_MARKER_END}\\n?`);

/**
 * Kimi Code home — `$KIMI_CODE_HOME`, else `~/.kimi-code`, the CLI's own resolution order. The
 * transcript reader resolves sessions the same way (core/transcript-kimi.ts); installing anywhere
 * else would write hooks into a config.toml the CLI never loads.
 */
function kimiHome(c: InstallCtx): string {
  return process.env.KIMI_CODE_HOME || join(c.home, ".kimi-code");
}

const kimi: HarnessInstaller = {
  name: "kimi-code",
  detect: (c) => onPath("kimi") || existsSync(kimiHome(c)),
  install(c) {
    const path = join(kimiHome(c), "config.toml");
    const existing = existsSync(path) ? readFileSync(path, "utf8") : "";
    // Replace a previous block rather than skipping when one exists, so a re-install repairs
    // paths that moved with the package (the grok-build precedent).
    const withoutOurs = existing.replace(KIMI_BLOCK_RE, "\n");
    // Kimi validates every [[hooks]] entry against a STRICT 4-key schema
    // (event / matcher / command / timeout). One unknown key does not drop that entry — it
    // drops EVERY hook in the file, at warning severity only. So emit those keys and nothing
    // else, and take the values from the lifecycle spec so the installed hooks can never
    // diverge from the ones the runtime entrypoints implement.
    const spec = HOOK_HARNESSES["kimi-code"];
    const entries = Object.values(spec.install)
      .map(
        (h) =>
          `[[hooks]]\nevent = ${JSON.stringify(h.event)}\n` +
          `command = ${JSON.stringify(`node "${join(c.dist, h.entry)}"`)}\n` +
          `timeout = ${h.timeout}\n`
      )
      .join("\n");
    const block = `\n${KIMI_MARKER_START}\n${entries}${KIMI_MARKER_END}\n`;
    if (existsSync(path) && !existsSync(`${path}.contextbase-backup`))
      copyFileSync(path, `${path}.contextbase-backup`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `${withoutOurs.replace(/\n*$/, "\n")}${block}`);
    // Kimi keeps MCP registration in its own mcp.json, not config.toml. Register the packaged
    // stdio server: it reads the endpoint and token from ~/.contextbase/coding-agent.json, so the
    // entry needs no bearerTokenEnvVar. An http entry would need CONTEXTBASE_API_KEY exported into
    // Kimi's environment, and silently 401s when it is not.
    const mcpPath = join(kimiHome(c), "mcp.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "kimi-code"),
    };
    writeJson(mcpPath, mcp);
    installSkill(c, "kimi-code");
    c.log?.(`kimi-code: native hooks installed in ${path}, MCP in ${mcpPath}`);
  },
  uninstall(c) {
    const path = join(kimiHome(c), "config.toml");
    if (existsSync(path)) {
      const existing = readFileSync(path, "utf8");
      const cleaned = existing.replace(KIMI_BLOCK_RE, "\n");
      if (cleaned !== existing) writeFileSync(path, cleaned);
    }
    const mcpPath = join(kimiHome(c), "mcp.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    uninstallSkill(c, "kimi-code");
    c.log?.("kimi-code: native hooks + MCP + skill removed");
  },
};

const CLINE_HOOK_MARKER = "CONTEXTBASE_CODING_AGENTS_CLINE";
const CLINE_OLD_HOOK_EVENTS = ["TaskStart", "UserPromptSubmit", "TaskComplete"];
const CLINE_PLUGIN_NAME = "contextbase-coding-agents";

/** Remove only wrappers from the short-lived file-hook implementation. Cline file hooks cannot
 * mutate a prompt; keeping them would falsely imply that old installs still inject memory. */
function removeLegacyClineHooks(c: InstallCtx): void {
  const hooksDir = join(c.home, "Documents", "Cline", "Hooks");
  for (const event of CLINE_OLD_HOOK_EVENTS) {
    const path = join(hooksDir, event);
    if (existsSync(path) && readFileSync(path, "utf8").includes(CLINE_HOOK_MARKER)) {
      rmSync(path, { force: true });
    }
  }
}

const cline: HarnessInstaller = {
  name: "cline-cli",
  detect: (c) => onPath("cline") || existsSync(join(c.home, ".cline")),
  install(c) {
    removeLegacyClineHooks(c);
    const installed = (c.clinePlugin ?? runClinePlugin)([
      "plugin",
      "install",
      "--force",
      c.pkgRoot,
    ]);
    const mcpPath = join(c.home, ".cline", "data", "settings", "cline_mcp_settings.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = {
      ...(mcp.mcpServers ?? {}),
      contextbase: preserveMcpEntry(c, mcp.mcpServers?.contextbase, "cline-cli"),
    };
    writeJson(mcpPath, mcp);
    installSkill(c, "cline-cli");
    c.log?.(
      installed
        ? "cline-cli: native plugin + MCP + skill installed"
        : `cline-cli: MCP + skill installed; run: cline plugin install --force "${c.pkgRoot}"`
    );
  },
  uninstall(c) {
    removeLegacyClineHooks(c);
    // Cline's uninstall command receives an installed plugin name, not the original local source
    // path. The package name is stable across global npm updates, unlike the package directory.
    (c.clinePlugin ?? runClinePlugin)(["plugin", "uninstall", CLINE_PLUGIN_NAME]);
    const mcpPath = join(c.home, ".cline", "data", "settings", "cline_mcp_settings.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        writeJson(mcpPath, mcp);
      }
    }
    uninstallSkill(c, "cline-cli");
    c.log?.("cline-cli: native plugin + MCP + skill removed");
  },
};

/** Dcode's plugin manager owns its cache and enablement state. Keep this installer as a thin
 * native CLI invocation: the package's bundled marketplace points back at the staged package,
 * while Dcode performs the copy, validation, enablement, and foreign-state preservation. */
const DCODE_MARKETPLACE = "contextbase-coding-agents";
const DCODE_PLUGIN_ID = "contextbase-coding-agents@contextbase-coding-agents";
const DCODE_MARKETPLACE_RELATIVE_PATH = join(".agents", "plugins", "marketplace.json");
const DCODE_FALLBACK_MARKETPLACE = "contextbase-coding-agents-marketplace.json";

/**
 * Prepare a local marketplace without taking ownership of a foreign manifest at the conventional
 * path. A custom JSON file still has the same ~/.contextbase root, so ./coding-agents remains valid,
 * while Dcode records it as its own marketplace and the foreign top-level name is untouched.
 */
function prepareDcodeMarketplace(c: InstallCtx): string | false {
  const root = join(c.home, ".contextbase");
  const conventionalPath = join(root, DCODE_MARKETPLACE_RELATIVE_PATH);
  let path = conventionalPath;
  let registrationSource = root;
  let marketplace: Record<string, any> = { plugins: [] };
  if (existsSync(conventionalPath)) {
    try {
      const parsed = JSON.parse(readFileSync(conventionalPath, "utf8"));
      if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.plugins)) {
        path = join(root, DCODE_FALLBACK_MARKETPLACE);
      } else if (
        typeof (parsed as Record<string, unknown>).name === "string" &&
        parsed.name !== DCODE_MARKETPLACE
      ) {
        // Do not mutate the identity of a marketplace that another Dcode plugin may already use.
        path = join(root, DCODE_FALLBACK_MARKETPLACE);
      } else {
        marketplace = parsed;
      }
    } catch {
      path = join(root, DCODE_FALLBACK_MARKETPLACE);
    }
  }
  if (path !== conventionalPath && existsSync(path)) {
    try {
      const parsed = JSON.parse(readFileSync(path, "utf8"));
      if (
        !parsed ||
        typeof parsed !== "object" ||
        !Array.isArray(parsed.plugins) ||
        parsed.name !== DCODE_MARKETPLACE
      ) {
        c.log?.(`dcode: refusing to replace malformed marketplace file ${path}`);
        return false;
      }
      marketplace = parsed;
    } catch {
      c.log?.(`dcode: refusing to replace unreadable marketplace file ${path}`);
      return false;
    }
  }
  if (path !== conventionalPath) registrationSource = path;
  const foreign = marketplace.plugins.filter(
    (entry: unknown) =>
      !entry ||
      typeof entry !== "object" ||
      (entry as Record<string, unknown>).name !== "contextbase-coding-agents"
  );
  marketplace.name = DCODE_MARKETPLACE;
  marketplace.plugins = [
    ...foreign,
    {
      name: "contextbase-coding-agents",
      source: { source: "local", path: "./coding-agents" },
    },
  ];
  writeJson(path, marketplace);
  return registrationSource;
}

const dcode: HarnessInstaller = {
  name: "dcode",
  detect: (c) => onPath("dcode") || existsSync(join(c.home, ".deepagents")),
  preflight: (c) =>
    c.dcodePlugin || onPath("dcode") ? undefined : "the `dcode` CLI is not on PATH",
  install(c) {
    const plugin = c.dcodePlugin ?? runDcodePlugin;
    const marketplacePath = prepareDcodeMarketplace(c);
    const installed =
      marketplacePath !== false &&
      plugin(["plugin", "marketplace", "add", marketplacePath]) &&
      plugin(["plugin", "install", DCODE_PLUGIN_ID]);
    if (installed) {
      c.log?.(`dcode: native Agent Plugin installed (${DCODE_PLUGIN_ID})`);
    } else {
      const source = marketplacePath === false ? join(c.home, ".contextbase") : marketplacePath;
      c.log?.(
        `dcode: could not install the native plugin — run \
` + `  dcode plugin marketplace add "${source}" && dcode plugin install ${DCODE_PLUGIN_ID}`
      );
    }
    return installed;
  },
  uninstall(c) {
    const plugin = c.dcodePlugin ?? runDcodePlugin;
    const removed = plugin(["plugin", "uninstall", DCODE_PLUGIN_ID]);
    // Also retire the marketplace WE registered. `plugin uninstall` alone leaves it listed by
    // `dcode plugin marketplace list` and the plugin itself listed as `disabled` — our own
    // leftovers in Dcode's state, not foreign state we are obliged to preserve. Only ours is
    // named DCODE_MARKETPLACE, so a foreign marketplace at the conventional path is untouched.
    const marketplaceRemoved = plugin(["plugin", "marketplace", "remove", DCODE_MARKETPLACE]);
    if (removed) {
      c.log?.("dcode: native Agent Plugin removed (foreign ~/.deepagents state preserved)");
      if (!marketplaceRemoved) {
        c.log?.(
          `dcode: the ${DCODE_MARKETPLACE} marketplace is still registered — remove it with \`dcode plugin marketplace remove ${DCODE_MARKETPLACE}\``
        );
      }
    } else {
      c.log?.(`dcode: could not run native uninstall for ${DCODE_PLUGIN_ID}`);
    }
    return removed;
  },
};

const DSH_MARKER_START = "# CONTEXTBASE_CODING_AGENTS_DSH_START";
const DSH_MARKER_END = "# CONTEXTBASE_CODING_AGENTS_DSH_END";
const DSH_BLOCK_RE = new RegExp(`\\n?${DSH_MARKER_START}[\\s\\S]*?${DSH_MARKER_END}\\n?`);

/**
 * What `uninstall` leaves behind when our block was the only thing in the file. dsh reads this file
 * as a top-level YAML array and fails BOOT on anything else, so an emptied file still has to parse;
 * a missing file would be fine too (`loadOptionalPatches` reads ENOENT as "no patches").
 */
const DSH_EMPTY_LIST = "[]";

/**
 * The user's own patches: our marker block removed, and the empty-list placeholder normalized away.
 *
 * Both halves matter. `DSH_BLOCK_RE` strips our row so a re-install repairs a stale path instead of
 * stacking a second block. And `DSH_EMPTY_LIST` is NOT user content — `"[]"` is a non-empty string,
 * so treating it as content made the install that follows an uninstall write `[]` *followed by* our
 * block: two top-level YAML documents, which dsh refuses to parse, so it then failed BOOT for EVERY
 * profile on the machine, not merely for this plugin. Normalizing here also repairs a home layer
 * that an earlier version already corrupted.
 */
function dshUserPatches(existing: string): string {
  const others = existing.replace(DSH_BLOCK_RE, "\n").trim();
  return others === DSH_EMPTY_LIST ? "" : others;
}

/** DeepSeek Harness home — `$DSH_HOME`, else `~/.dsh` (its own `home-paths` resolution order). */
function dshHome(c: InstallCtx): string {
  return process.env.DSH_HOME || join(c.home, ".dsh");
}

/**
 * DeepSeek Harness — a native Cordis plugin, wired through the HOME-level patch layer
 * (`$DSH_HOME/cordis.patch.yml`), which every profile composes after its bundles.
 *
 * The alternative is `dsh plugin --profile <name> add @huaweicloud/contextbase-coding-agents`, which
 * pnpm-installs the package into ONE profile and picks up the `dsh.bundle.patch` this package
 * ships. That is the right route for a published install and is what the docs recommend, but it
 * needs pnpm, a network, and a repeat per profile — so the installer takes the path that always
 * works: patch the home layer to load the dist entry that is already on this machine.
 *
 * The row's `name` MUST be a `file://` URL. Cordis resolves it as an ES module specifier, and a
 * bare absolute path is not one — the same trap Kilo has, where it fails to resolve and the plugin
 * is silently skipped.
 */
const dsh: HarnessInstaller = {
  name: "dsh",
  detect: (c) => onPath("dsh") || existsSync(dshHome(c)),
  install(c) {
    const path = join(dshHome(c), "cordis.patch.yml");
    const existing = existsSync(path) ? readFileSync(path, "utf8") : "";
    // REPLACE any previous block rather than skipping: a re-install after the package moved must
    // repair the now-dead path, which is exactly what `install` is for.
    const others = dshUserPatches(existing);
    const entry = pathToFileURL(join(c.dist, "dsh.js")).href;
    const block =
      `${DSH_MARKER_START}\n` +
      `- insert:\n` +
      `    - id: contextbase\n` +
      `      name: ${JSON.stringify(entry)}\n` +
      `${DSH_MARKER_END}\n`;
    if (existsSync(path) && !existsSync(`${path}.contextbase-backup`))
      copyFileSync(path, `${path}.contextbase-backup`);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, others ? `${others}\n\n${block}` : block);
    // dsh's skill provider scans the shared agentskills root, the same one Codex reads.
    installSkill(c, "dsh");
    // A running `dsh web` hot-loads the new patch entry, so its open sessions gain the contextbase_*
    // tools mid-conversation — a tool-set change that invalidates the provider prompt cache (#4317).
    c.log?.(
      `dsh: plugin registered in ${path} (applies to every dsh profile; start new sessions — ones already open would gain the tools mid-conversation)`
    );
  },
  uninstall(c) {
    const path = join(dshHome(c), "cordis.patch.yml");
    if (existsSync(path)) {
      const existing = readFileSync(path, "utf8");
      const others = existing.replace(DSH_BLOCK_RE, "\n").trim();
      // `DSH_EMPTY_LIST`, not an empty file: dsh requires this file to parse to a top-level ARRAY
      // and fails BOOT on anything else, so removing the last block must leave an empty list
      // behind. `install` knows that placeholder is not user content — see `dshUserPatches`.
      if (others !== existing.trim())
        writeFileSync(path, others ? `${others}\n` : `${DSH_EMPTY_LIST}\n`);
    }
    uninstallSkill(c, "dsh");
    c.log?.("dsh: plugin entry + skill removed");
  },
};

const qwen: HarnessInstaller = {
  name: "qwen-code",
  detect: (c) => onPath("qwen") || existsSync(join(c.home, ".qwen")),
  install(c) {
    const path = join(c.home, ".qwen", "settings.json");
    const existing = jsonMcpRegistration(path);
    if (!existing.readable) {
      c.log?.(
        "qwen-code: unreadable MCP configuration preserved; fix settings.json before installing"
      );
      return false;
    }
    const settings = readJson(path);
    settings.hooks = settings.hooks ?? {};
    // Qwen's settings.json hook shape is Claude Code's, so the shared nested writer applies —
    // the ONLY difference is the unit of `timeout`, which HOOK_HARNESSES already carries in ms.
    mergeHarnessHooks(settings.hooks, "qwen-code", c.dist);
    writeJson(path, settings);
    c.log?.(`qwen-code: hooks merged into ${path}`);
    installSkill(c, "qwen-code");
    const mcp = c.qwenMcp ?? defaultQwenMcp;
    if (existing.entry !== undefined && !isOurMcpEntry(existing.entry)) {
      c.log?.(
        "qwen-code: preserved the existing contextbase MCP registration managed outside this plugin"
      );
      return;
    }
    // Inspect and remove in the same user scope; a project entry belongs to its administrator.
    if (existing.entry !== undefined) mcp(["mcp", "remove", "-s", "user", "contextbase"]);
    if (
      mcp([
        "mcp",
        "add",
        "-s",
        "user",
        "-e",
        "CONTEXTBASE_MCP_HARNESS=qwen-code",
        "contextbase",
        "node",
        join(c.dist, "mcp-server.js"),
      ])
    ) {
      c.log?.("qwen-code: MCP server registered (qwen mcp add, user scope)");
    } else {
      c.log?.(
        `qwen-code: could not run \`qwen mcp add\` — register the tools manually:\n` +
          `  qwen mcp add -s user -e CONTEXTBASE_MCP_HARNESS=qwen-code contextbase node "${join(c.dist, "mcp-server.js")}"`
      );
    }
  },
  uninstall(c) {
    const path = join(c.home, ".qwen", "settings.json");
    const existing = jsonMcpRegistration(path);
    if (!existing.readable) {
      c.log?.("qwen-code: unreadable MCP configuration preserved");
      return false;
    }
    if (existsSync(path)) {
      const settings = readJson(path);
      if (settings.hooks) {
        stripHarnessHooks(settings.hooks, "qwen-code");
        if (!Object.keys(settings.hooks).length) delete settings.hooks;
        writeJson(path, settings);
      }
    }
    const mcp = c.qwenMcp ?? defaultQwenMcp;
    if (isOurMcpEntry(existing.entry)) mcp(["mcp", "remove", "-s", "user", "contextbase"]);
    uninstallSkill(c, "qwen-code");
    c.log?.("qwen-code: hooks + MCP registration + skill removed");
  },
};

function defaultQwenMcp(args: string[]): boolean {
  try {
    execFileSync("qwen", args, { stdio: "pipe" });
    return true;
  } catch {
    return false;
  }
}

/**
 * Factory Droid wires everything through plain JSON files under `~/.factory/`, so the installer
 * needs no Droid CLI round-trip:
 *
 * - `hooks.json` - user-level hook registrations. Droid reads the EVENT MAP at the TOP LEVEL of
 *   this file (unlike Claude Code, which nests it under a `hooks` key inside settings.json), so
 *   `mergeHarnessHooks` is applied to the root object, not to a `hooks` property. The matcher-group
 *   entries themselves are Claude-shaped, which is exactly what the "nested" configStyle emits.
 * - `mcp.json` - `mcpServers.contextbase` runs the same stdio `dist/mcp-server.js` as every other
 *   host, tagged with `CONTEXTBASE_MCP_HARNESS=factory-droid`. A same-named foreign server blocks
 *   install instead of being overwritten. Droid reloads this file on change.
 * - `skills/` - the companion skill, same copy/uninstall dance as the other hosts.
 */
const factoryDroid: HarnessInstaller = {
  name: "factory-droid",
  detect: (c) => onPath("droid") || existsSync(join(c.home, ".factory")),
  preflight(c) {
    const mcpPath = join(c.home, ".factory", "mcp.json");
    const existing = readJson(mcpPath).mcpServers?.contextbase;
    if (existing && !isOurMcpEntry(existing)) {
      return (
        `${mcpPath} already contains a user-managed MCP server named "contextbase". ` +
        "Rename or remove that entry, then re-run install."
      );
    }
  },
  install(c) {
    const hooksPath = join(c.home, ".factory", "hooks.json");
    const hooks = readJson(hooksPath);
    if (!existsSync(hooksPath)) {
      // A standalone hooks.json takes precedence over settings.json. Copy fallback declarations
      // before creating it, otherwise installing contextbase silently disables every existing hook.
      const fallback = readJson(join(c.home, ".factory", "settings.json")).hooks;
      if (fallback && typeof fallback === "object" && !Array.isArray(fallback)) {
        Object.assign(hooks, fallback);
      }
    }
    mergeHarnessHooks(hooks as Record<string, any>, "factory-droid", c.dist);
    writeJson(hooksPath, hooks);
    c.log?.(`factory-droid: hooks merged into ${hooksPath}`);
    installSkill(c, "factory-droid");

    const mcpPath = join(c.home, ".factory", "mcp.json");
    const mcp = readJson(mcpPath);
    mcp.mcpServers = mcp.mcpServers ?? {};
    mcp.mcpServers.contextbase = preserveMcpEntry(c, mcp.mcpServers.contextbase, "factory-droid");
    writeJson(mcpPath, mcp);
    c.log?.(`factory-droid: MCP server registered in ${mcpPath}`);
  },
  uninstall(c) {
    const hooksPath = join(c.home, ".factory", "hooks.json");
    if (existsSync(hooksPath)) {
      const hooks = readJson(hooksPath);
      stripHarnessHooks(hooks as Record<string, any>, "factory-droid");
      if (Object.keys(hooks).length) writeJson(hooksPath, hooks);
      else rmSync(hooksPath);
    }
    const mcpPath = join(c.home, ".factory", "mcp.json");
    if (existsSync(mcpPath)) {
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        if (Object.keys(mcp.mcpServers).length) writeJson(mcpPath, mcp);
        else rmSync(mcpPath);
      }
    }
    uninstallSkill(c, "factory-droid");
    c.log?.("factory-droid: hooks + MCP registration + skill removed");
  },
};

/**
 * ZCode (Z.ai's GLM coding agent) keeps its own CLI config at `~/.zcode/cli/config.json` and reads
 * hooks from a `hooks` block there — deliberately NOT `~/.claude/settings.json`, even though ZCode
 * embeds the Claude Code agent runtime and speaks its hook protocol. Writing the user's real Claude
 * Code config would wire a second agent nobody asked for.
 *
 * Three things make this block different from the other JSON hosts:
 *
 * - `hooks.enabled` ships FALSE. Registering the events without flipping it installs a lifecycle
 *   that never fires, which looks like a healthy install and remembers nothing.
 * - `hooks.maxOutputBytes` caps what a hook may print; anything larger is DROPPED, taking the whole
 *   injection with it. Seeded only when absent — a user who has tuned it owns it.
 * - the registrations live under `hooks.events`, in the "process" argv shape (see processHook).
 *
 * MCP and the companion skill land in the same config/home, so ZCode gets the full surface:
 *
 * - `mcp.servers.contextbase` runs the same stdio `dist/mcp-server.js` as every other host, tagged
 *   `CONTEXTBASE_MCP_HARNESS=zcode`. ZCode's schema is `{type, command, args?, cwd?, env?}` and its
 *   loader infers `type: "stdio"` from a `command`, so the shared `mcpServerEntry` drops straight
 *   in. A same-named foreign server blocks install instead of being overwritten.
 * - `~/.zcode/skills` — ZCode's own user-level skill root (see SKILL_DIRS for why not the shared
 *   `~/.agents/skills` it also scans).
 *
 * Both ride `features.mcp` / `features.skill`, which default to true; the installer leaves those
 * alone rather than forcing them, because a user who turned one off meant it.
 */
const zcode: HarnessInstaller = {
  name: "zcode",
  detect: (c) => onPath("zcode") || existsSync(join(c.home, ".zcode")),
  preflight(c) {
    const configPath = zcodeConfigPath(c);
    const existing = readJson(configPath).mcp?.servers?.contextbase;
    if (existing && !isOurMcpEntry(existing)) {
      return (
        `${configPath} already contains a user-managed MCP server named "contextbase". ` +
        "Rename or remove that entry, then re-run install."
      );
    }
  },
  install(c) {
    const configPath = zcodeConfigPath(c);
    const config = readJson(configPath);
    const hooks = (config.hooks = config.hooks ?? {});
    hooks.enabled = true;
    hooks.maxOutputBytes = hooks.maxOutputBytes ?? ZCODE_MAX_OUTPUT_BYTES;
    hooks.events = hooks.events ?? {};
    mergeHarnessHooks(hooks.events, "zcode", c.dist);
    config.mcp = config.mcp ?? {};
    config.mcp.servers = config.mcp.servers ?? {};
    config.mcp.servers.contextbase = mcpServerEntry(c.dist, "zcode");
    writeJson(configPath, config);
    c.log?.(`zcode: hooks + MCP server merged into ${configPath}`);
    installSkill(c, "zcode");
  },
  uninstall(c) {
    const configPath = zcodeConfigPath(c);
    if (existsSync(configPath)) {
      const config = readJson(configPath);
      if (isOurMcpEntry(config.mcp?.servers?.contextbase)) {
        delete config.mcp.servers.contextbase;
        if (!Object.keys(config.mcp.servers).length) delete config.mcp;
      }
      const hooks = config.hooks;
      if (hooks?.events) {
        stripHarnessHooks(hooks.events, "zcode");
        // Nothing of ours left to run: remove the whole block so ZCode's hook system goes back to
        // off, its shipped default. When FOREIGN hooks remain the switch is now theirs, so the
        // block — `enabled` included — stays exactly as it is.
        if (!Object.keys(hooks.events).length) delete config.hooks;
      }
      writeJson(configPath, config);
    }
    uninstallSkill(c, "zcode");
    c.log?.(`zcode: hooks + MCP registration + skill removed`);
  },
};

/**
 * TRAE splits its config across two roots: a dot-dir holding hooks.json/sandbox.json (and the
 * skills root), and the app's Electron userData dir holding per-window storage (`User/
 * workspaceStorage`; a `~/.trae-cn/mcp.json` is never read). Both roots are edition-branded: the
 * CN build uses `~/.trae-cn` / "Trae CN", the international build `~/.trae` / "Trae", so every
 * path resolves by probing for the brand dir that actually exists and falling back to the CN
 * names (see traecodeDotDirName / traecodeUserDataDir).
 */
const traecodeMcpPath = (c: InstallCtx): string =>
  join(traecodeUserDataDir(c.home), "User", "mcp.json");

/** Remove OUR stale user-level MCP entry from `<userData>/User/mcp.json` (see the harness docs
 *  for why it must not exist), leaving foreign entries and the rest of the document alone, and
 *  deleting the file when nothing but our entry was in it. Returns whether anything was removed.
 *  Never throws. */
function removeTraecodeUserMcpEntry(c: InstallCtx): boolean {
  try {
    const mcpPath = traecodeMcpPath(c);
    if (!existsSync(mcpPath)) return false;
    const mcp = readJson(mcpPath);
    if (!isOurMcpEntry(mcp.mcpServers?.contextbase)) return false;
    delete mcp.mcpServers.contextbase;
    if (Object.keys(mcp.mcpServers).length) writeJson(mcpPath, mcp);
    else rmSync(mcpPath);
    return true;
  } catch {
    return false;
  }
}

/**
 * Trae gates workspace-level MCP files behind `trae.mcp.enableWorkspaceMcp` (global, default
 * false) — without it the per-repo `.trae/mcp.json` this install relies on is never read and
 * contextbase's MCP tools stay hidden. Flipping a global setting is the user's call, so it is
 * asked HERE, on the installer's TTY: `install` is idempotent and re-run often, and the gate
 * state makes the prompt self-silencing once answered. Non-interactive runs (CI, scripts, the
 * test suite) print the manual step and touch nothing — a global setting must never flip
 * without a human; `--enable-workspace-mcp` is that human, up front.
 */
function ensureTraecodeWorkspaceMcpGate(c: InstallCtx): void {
  const settingsPath = traecodeUserSettingsPath(c.home);
  if (workspaceMcpGateState(settingsPath) === "on") return;
  const ask =
    "\n" +
    "  Trae ignores per-repo MCP configs until workspace MCP is enabled, which keeps\n" +
    "  contextbase's MCP tools hidden. Enable it globally now? (one-time setting)\n";
  const skipNote =
    '  Skipped. Enable later in Trae settings (search "enableWorkspaceMcp") or re-run with\n' +
    "  --enable-workspace-mcp.";
  if (!(c.args ?? []).includes("--enable-workspace-mcp")) {
    if (c.interactive !== true) {
      c.log?.(`${ask}  ${skipNote}`);
      return;
    }
    const answer = readLineSync(c, `${ask}  Enable workspace MCP? [Y/n]: `).trim().toLowerCase();
    if (answer === "n" || answer === "no") {
      c.log?.(skipNote);
      return;
    }
  }
  if (enableWorkspaceMcpSetting(settingsPath)) {
    // The hooks run from the staged runtime (c.dist), not from this installer's own copy of the
    // package, so the witness goes where THEY look for it.
    markWorkspaceMcpEnabled({ stateFile: gateStateFileFor(c.dist) });
    c.log?.(
      `traecode: workspace MCP enabled in ${settingsPath} — restart Trae windows to pick it up`
    );
  } else {
    c.log?.(
      `traecode: could not update ${settingsPath} (comments or unreadable JSON) — set\n` +
        `  "trae.mcp.enableWorkspaceMcp": true in Trae settings instead.`
    );
  }
}

/**
 * TraeCode (TRAE CN's agent) keeps plain JSON files under `~/.trae-cn/`, so like Factory Droid the
 * installer needs no CLI round-trip:
 *
 * - `hooks.json` - user-level hook registrations. TraeCode speaks Claude Code's hook protocol and
 *   nests the event map under a top-level `hooks` key (Claude's settings.json shape), NOT at the
 *   top level the way Droid's hooks.json is read. The host also writes and expects a top-level
 *   `version` field, so the installer seeds it at 1 when absent and leaves it alone otherwise.
 * - `skills/` - the companion skill, in TraeCode's own user-level root (see SKILL_DIRS).
 * - `sandbox.json` - `filesystem.readWrite` rules for `~/.contextbase` (logs, config — without them
 *   the hooks fail silently, verified on a live install) and for Trae's per-window storage DBs
 *   (`<userData>/User/workspaceStorage`), which the SessionStart hook seeds with the workspace's
 *   MCP enable switch (core/traecode-mcp.ts).
 *
 * Deliberately NOT touched: the user-level MCP file (`<userData>/User/mcp.json`). Trae launches
 * user-level servers with the ELECTRON process's cwd (home), so a contextbase entry there is wrong
 * in every configuration — with `optInOnly` it self-disables (zero tools), without it the tools
 * resolve the HOME bank instead of the repo's. The only correct registration is per-repo
 * `<repo>/.trae/mcp.json`, which install pre-seeds and the SessionStart hook tops up
 * (core/traecode-mcp.ts); install migrates a stale user-level entry left by earlier versions
 * away (ours only — a foreign `contextbase` entry is the user's own server and is never touched).
 *
 * TraeCode keeps sessions in an encrypted local DB or the cloud — there is no transcript file — so
 * the journal-based lifecycle (see HOOK_HARNESSES.traecode) is the whole write-back path.
 */
const traecode: HarnessInstaller = {
  name: "traecode",
  detect: (c) => existsSync(join(c.home, traecodeDotDirName(c.home))) || onPath("trae"),
  install(c) {
    const hooksPath = join(c.home, traecodeDotDirName(c.home), "hooks.json");
    const doc = readJson(hooksPath);
    doc.version = doc.version ?? 1;
    const hooks = (doc.hooks = doc.hooks ?? {});
    mergeHarnessHooks(hooks, "traecode", c.dist);
    writeJson(hooksPath, doc);
    c.log?.(`traecode: hooks merged into ${hooksPath}`);
    installSkill(c, "traecode");

    // Migration: installs before 2026-09 registered the MCP server at the user level, where
    // Trae's home-directory cwd breaks it (see the harness docs). The per-repo `.trae/mcp.json`
    // the installer and SessionStart hook maintain is the only registration — drop the stale entry.
    if (removeTraecodeUserMcpEntry(c)) {
      c.log?.(
        `traecode: stale user-level MCP entry removed from ${traecodeMcpPath(c)} — per-repo\n` +
          "  .trae/mcp.json files register the server instead"
      );
    }

    // TraeCode runs every hook inside its sandbox; the profile is generated per session from the
    // defaults plus the user's `~/.trae-cn/sandbox.json` rules. The defaults cover network and the
    // journal's tmpdir but NOT `~/.contextbase` (logs, config), so without this rule the hooks fail
    // silently (exit 0, zero effect) and the only workaround would be running hooks unsandboxed.
    // The per-window storage DBs get the same treatment: the SessionStart hook seeds the
    // workspace's MCP enable switch there (core/traecode-mcp.ts).
    const sandboxPath = join(c.home, traecodeDotDirName(c.home), "sandbox.json");
    const sandbox = readJson(sandboxPath);
    const fsRules = (sandbox.filesystem = sandbox.filesystem ?? {});
    const readWrite = (fsRules.readWrite = fsRules.readWrite ?? []);
    const needed = [join(c.home, ".contextbase"), traecodeWorkspaceStorageDir(c.home)];
    let sandboxChanged = false;
    for (const dir of needed) {
      if (!readWrite.includes(dir)) {
        readWrite.push(dir);
        sandboxChanged = true;
      }
    }
    if (sandboxChanged) {
      writeJson(sandboxPath, sandbox);
      c.log?.(`traecode: sandbox readWrite rules added (${needed.join(", ")})`);
    }

    // Pre-seed what the SessionStart hook would otherwise write per session: the per-repo MCP
    // registration and the workspace enable switch for every repo in mapPathToBank. Trae's hook
    // sandbox denies file creation in the workspace and (observed live 2026-09-21) drops
    // sandbox.json rules targeting Trae's own storage, so on stock installs both hook writes
    // fail — the installer runs unsandboxed and lands them. Because the hook checks before
    // writing, a pre-seeded repo turns every later session into a read-only no-op.
    const config = readJson(contextbaseConfigPath(c));
    const repos = Object.keys(config.mapPathToBank ?? {}).sort();
    if (repos.length) {
      const written: string[] = [];
      const current: string[] = [];
      const skipped: string[] = [];
      let seeded = 0;
      for (const repo of repos) {
        // A map entry whose directory is gone must not grow a phantom `.trae` tree via mkdir -p.
        if (!existsSync(repo)) {
          skipped.push(repo);
          continue;
        }
        const outcome = registerTraecodeWorkspaceMcp(repo, { home: c.home, dist: c.dist });
        if (outcome === "registered") written.push(repo);
        else if (outcome === "current") current.push(repo);
        else skipped.push(repo);
        if (ensureWorkspaceMcpEnabled(repo, { home: c.home }) !== "failed") seeded++;
      }
      c.log?.(
        `traecode: per-repo MCP registration — ${written.length} written, ${current.length} ` +
          `already current, ${skipped.length} skipped across ${repos.length} opted-in repo(s); ` +
          `enable switch on for ${seeded}`
      );
      if (written.length) c.log?.(`  registered: ${written.join(", ")}`);
      if (skipped.length) {
        c.log?.(
          `  skipped (missing repo, no dist build, or a foreign contextbase entry): ` +
            skipped.join(", ")
        );
      }
      // A freshly seeded switch takes effect in the NEXT window (Trae holds the running one's
      // table in memory); if a repo was opened before this install, one panel flip covers it.
      if (written.length) {
        c.log?.(
          "  new registrations appear in the next Trae window — if a repo's server still shows\n" +
            "  disabled in the MCP panel, flip it on once there"
        );
      }
    }

    ensureTraecodeWorkspaceMcpGate(c);
  },
  uninstall(c) {
    const hooksPath = join(c.home, traecodeDotDirName(c.home), "hooks.json");
    if (existsSync(hooksPath)) {
      const doc = readJson(hooksPath);
      if (doc.hooks) {
        stripHarnessHooks(doc.hooks, "traecode");
        if (!Object.keys(doc.hooks).length) delete doc.hooks;
      }
      // A file holding nothing but `version` carries no information TraeCode needs: remove it
      // rather than leave a husk. Foreign hooks keep the file (and the field) alive.
      if (Object.keys(doc).length > 1) writeJson(hooksPath, doc);
      else rmSync(hooksPath);
    }
    if (removeTraecodeUserMcpEntry(c)) {
      c.log?.(`traecode: MCP entry removed from ${traecodeMcpPath(c)}`);
    }
    // The per-repo registrations the installer (or the hook) wrote: drop our entry from every
    // opted-in repo's .trae/mcp.json, deleting the file when nothing remains in it. Foreign
    // servers and foreign "contextbase" entries are never touched — same ownership check as the
    // hook's. Missing repos skip silently; the storage sweep below still catches their switches.
    const config = readJson(contextbaseConfigPath(c));
    const repoEntries = Object.keys(config.mapPathToBank ?? {}).sort();
    const cleaned = repoEntries.filter((repo) =>
      removeTraecodeWorkspaceMcpEntry(repo, { home: c.home })
    );
    if (cleaned.length) {
      c.log?.(`traecode: per-repo MCP registration removed from:\n  ${cleaned.join("\n  ")}`);
    }
    const sandboxPath = join(c.home, traecodeDotDirName(c.home), "sandbox.json");
    if (existsSync(sandboxPath)) {
      const sandbox = readJson(sandboxPath);
      const readWrite = sandbox.filesystem?.readWrite;
      if (Array.isArray(readWrite)) {
        const ours = [join(c.home, ".contextbase"), traecodeWorkspaceStorageDir(c.home)];
        const filtered = readWrite.filter((p: string) => !ours.includes(p));
        if (filtered.length !== readWrite.length) {
          sandbox.filesystem.readWrite = filtered;
          writeJson(sandboxPath, sandbox);
        }
      }
    }
    // The per-workspace enable switches the installer/hook seeded — an uninstall leaves no storage behind.
    removeWorkspaceMcpEnabledKeys(c.home);
    uninstallSkill(c, "traecode");
    c.log?.(`traecode: hooks + MCP registration + skill removed`);
  },
};

/**
 * WorkBuddy and CodeBuddy Code run the same `@genie/agent-cli` engine, one home folder apart
 * (`~/.workbuddy` vs `~/.codebuddy`). Both read the nested Claude-shaped hooks block from
 * `<home>/settings.json`, so `mergeHarnessHooks` writes it unchanged, and both take the MCP server
 * from a plain FILE (no external CLI involved). The companion skill lands in each host's own root
 * (see SKILL_DIRS).
 *
 * `mcpPaths` is the host's MCP file lookup, highest priority first: the installer writes the FIRST
 * one that exists (or the first one when none do), and uninstall sweeps them all — an entry
 * installed before a higher-priority file appeared would otherwise survive as a dormant duplicate.
 */
const genieInstaller = (
  name: "workbuddy" | "codebuddy",
  homeDir: string,
  mcpPaths: (home: string) => string[]
): HarnessInstaller => ({
  name,
  detect: (c) => existsSync(join(c.home, homeDir)),
  install(c) {
    const settingsPath = join(c.home, homeDir, "settings.json");
    const settings = readJson(settingsPath);
    settings.hooks = settings.hooks ?? {};
    mergeHarnessHooks(settings.hooks, name, c.dist);
    writeJson(settingsPath, settings);
    c.log?.(`${name}: hooks merged into ${settingsPath}`);

    const paths = mcpPaths(c.home);
    const mcpPath = paths.find((p) => existsSync(p)) ?? paths[0];
    const mcp = readJson(mcpPath);
    mcp.mcpServers = mcp.mcpServers ?? {};
    mcp.mcpServers.contextbase = preserveMcpEntry(c, mcp.mcpServers.contextbase, name);
    writeJson(mcpPath, mcp);
    c.log?.(`${name}: MCP server registered in ${mcpPath}`);

    installSkill(c, name);
  },
  uninstall(c) {
    const settingsPath = join(c.home, homeDir, "settings.json");
    if (existsSync(settingsPath)) {
      const settings = readJson(settingsPath);
      if (settings.hooks) {
        stripHarnessHooks(settings.hooks, name);
        if (!Object.keys(settings.hooks).length) delete settings.hooks;
        writeJson(settingsPath, settings);
      }
    }
    for (const mcpPath of mcpPaths(c.home)) {
      if (!existsSync(mcpPath)) continue;
      const mcp = readJson(mcpPath);
      if (isOurMcpEntry(mcp.mcpServers?.contextbase)) {
        delete mcp.mcpServers.contextbase;
        if (!Object.keys(mcp.mcpServers).length) delete mcp.mcpServers;
        writeJson(mcpPath, mcp);
      }
    }
    uninstallSkill(c, name);
    c.log?.(`${name}: hooks + MCP registration + skill removed`);
  },
});

/** WorkBuddy (Tencent's AI workbench): one MCP file, `~/.workbuddy/mcp.json`. */
const workbuddy = genieInstaller("workbuddy", ".workbuddy", (home) => [
  join(home, ".workbuddy", "mcp.json"),
]);

/**
 * CodeBuddy resolves its user-scope MCP file by priority — ~/.codebuddy/.mcp.json (recommended),
 * then ~/.codebuddy/mcp.json (deprecated), then ~/.codebuddy.json (legacy) — reading and writing
 * the FIRST one that exists (codebuddy.ai/docs/cli/mcp). Writing the recommended path
 * unconditionally would shadow a user whose servers live in the deprecated file.
 */
const codebuddy = genieInstaller("codebuddy", ".codebuddy", (home) => [
  join(home, ".codebuddy", ".mcp.json"),
  join(home, ".codebuddy", "mcp.json"),
  join(home, ".codebuddy.json"),
]);

export const INSTALLERS: HarnessInstaller[] = [
  opencode,
  opencode2,
  kilo,
  pi,
  primeAgent,
  claudeCode,
  codex,
  antigravity,
  devin,
  cursor,
  copilot,
  grok,
  qwen,
  kimi,
  cline,
  dcode,
  dsh,
  factoryDroid,
  zcode,
  traecode,
  workbuddy,
  codebuddy,
];

// The public executable was renamed from Gemini CLI to Antigravity's `agy`. Keep the
// integration's stable internal name for bank identity and hook compatibility, while accepting
// the executable name users naturally type at the installer prompt.
const HARNESS_ALIASES: Record<string, string> = { agy: "antigravity-cli" };

// ── CLI ─────────────────────────────────────────────────────────────────────────

/**
 * Backfill this repo's past sessions for one harness, by handing them to the same deepen engine a
 * session start uses. Deepen dedups by document id, so re-running is safe.
 *
 * Scoped to the current directory: history is per-repo, and a machine can hold thousands of
 * sessions across unrelated projects that nobody wants extracted.
 */
function importConversations(harness: string, ctx: InstallCtx): void {
  const repo = process.cwd();
  const found = importLocalHistory(harness, repo);
  if (!found.supported) {
    ctx.log?.(`${harness}: --import-conversations skipped — ${found.reason}`);
    return;
  }
  if (found.unattributed) {
    // Never silently: a session we cannot attribute is one the user might expect to see imported.
    ctx.log?.(
      `${harness}: skipped ${found.unattributed} session(s) that do not record which directory ` +
        `they ran in — importing them could file another repo's conversation into this bank`
    );
  }
  if (!found.sessions.length) {
    ctx.log?.(`${harness}: no past sessions found on disk for ${repo}`);
    return;
  }
  const turns = found.sessions.reduce((n, s) => n + s.turns.length, 0);
  const file = join(mkdtempSync(join(tmpdir(), "contextbase-import-")), "conversations.json");
  writeFileSync(file, JSON.stringify(found.sessions));
  ctx.log?.(
    `${harness}: importing ${found.sessions.length} past sessions (${turns} turns) from ${repo} — ` +
      `this runs extraction and may take a while`
  );
  try {
    execFileSync("node", [join(ctx.dist, "deepen.js"), "--repo", repo, "--conversations", file], {
      stdio: "inherit",
    });
  } catch {
    // The wiring is already in place; a failed backfill must not make `install` look failed.
    ctx.log?.(`${harness}: conversation import did not finish — re-run it any time with:`);
    ctx.log?.(`  node "${join(ctx.dist, "deepen.js")}" --repo "${repo}" --conversations "${file}"`);
  }
}

export function run(argv: string[], ctxIn: InstallCtx): number {
  let ctx = ctxIn;
  const [command, ...rawArgs] = argv;
  ctx = { ...ctx, args: rawArgs };
  for (const name of ["server", "api-url", "api-token", "bank-id", "project-path"]) {
    const index = rawArgs.indexOf(`--${name}`);
    if (index >= 0 && (!rawArgs[index + 1] || rawArgs[index + 1].startsWith("--"))) {
      ctx.log?.(`--${name} requires a value`);
      return 1;
    }
  }
  // `--import-conversations` backfills this repo's PAST sessions for the harness being installed —
  // the migration path off the older per-agent plugins, whose banks the server cannot merge into
  // this one. Opt-in: it re-extracts history and therefore costs tokens.
  const importHistory = rawArgs.includes("--import-conversations");
  // A flag's VALUE (`--server daemon`) is a bare word too — excluding it keeps "daemon" from being
  // read as a harness name and rejected.
  const valueFlags = new Set([
    "--server",
    "--api-url",
    "--api-token",
    "--bank-id",
    "--project-path",
  ]);
  const names = rawArgs.filter(
    (a, index) => !a.startsWith("--") && !(index > 0 && valueFlags.has(rawArgs[index - 1]))
  );
  // Read-only: summarizes the local usage log (core/usage.ts) and touches nothing else.
  if (command === "stats") {
    ctx.log?.(formatUsageReport(readUsage()));
    return 0;
  }
  // Everything we write into a host's config is an ABSOLUTE path into this package. Run straight
  // from an npx cache those paths die on the first eviction and every hook stops SILENTLY, which is
  // why installing from a cache used to be refused outright. Copying the runtime somewhere stable
  // first removes the problem instead of pushing it onto the user: `npx` now works, and nobody has
  // to keep a global install of a tool whose only job is to set other tools up.
  if (command === "install" || command === "update") ctx = stageRuntime(ctx);
  // `update` is `install`'s staging half and nothing else: it replaces the runtime every wired
  // agent already points at (~/.contextbase/coding-agents/dist, a path that is stable across
  // versions) and writes to NO host config. That separation is what makes it safe to run
  // unattended from `core/auto-update.ts` — an `install` would need a harness list, and choosing
  // one on the user's behalf would rewire agents they never asked us to touch.
  //
  // The cost of not rewiring: a version that introduces a NEW hook entry point is staged but not
  // referenced, so that one feature waits for a manual `install`. Every existing entry point picks
  // the new code up on its next spawn.
  if (command === "update") {
    ctx.log?.(
      ctx.pkgRoot === ctxIn.pkgRoot
        ? "runtime already up to date — nothing staged"
        : "runtime updated — every wired agent picks it up on its next session"
    );
    return 0;
  }
  if (command !== "install" && command !== "uninstall") {
    ctx.log?.(
      `usage: contextbase-coding-agents <install|uninstall> <all|harness...>\n` +
        `       contextbase-coding-agents update\n` +
        `       contextbase-coding-agents stats\n` +
        `       [--server cloud|self-hosted] [--api-url <url>] [--api-token <token>]\n` +
        `       [--bank-id <id>] [--project-path <directory>]\n` +
        `       [--import-conversations] [--enable-workspace-mcp]\n` +
        `  all      every agent detected on this machine\n` +
        `  harness  ${INSTALLERS.map((i) => i.name).join(", ")} (agy aliases antigravity-cli)\n` +
        `  update   re-stage the runtime only, leaving every host config untouched\n` +
        `  agents/CI: without a TTY nothing ever prompts — pass --server (and --api-url/--api-token) to choose`
    );
    return command ? 1 : 0;
  }
  let targets: HarnessInstaller[];
  // `all` is spelled out rather than implied by a bare command: this rewrites the config of EVERY
  // detected agent — hooks, MCP registration and the companion skill — which is too much of a
  // machine to change by accident from `install` alone.
  if (names.includes("all")) {
    targets = INSTALLERS.filter((i) => i.detect(ctx));
    if (!targets.length) {
      ctx.log?.("no supported coding agents detected — name one explicitly to wire it anyway");
      return 1;
    }
    ctx.log?.(`detected: ${targets.map((t) => t.name).join(", ")}`);
  } else if (names.length) {
    targets = [];
    for (const n of names) {
      const hit = INSTALLERS.find((i) => i.name === (HARNESS_ALIASES[n] ?? n));
      if (!hit) {
        ctx.log?.(
          `unknown harness "${n}" — expected "all" or one of: ${INSTALLERS.map((i) => i.name).join(", ")} (agy aliases antigravity-cli)`
        );
        return 1;
      }
      targets.push(hit);
    }
  } else {
    ctx.log?.(
      `${command}: name a harness, or "all" for every agent detected on this machine.\n` +
        `  contextbase-coding-agents ${command} claude-code\n` +
        `  contextbase-coding-agents ${command} all\n` +
        `harnesses: ${INSTALLERS.map((i) => i.name).join(", ")} (agy aliases antigravity-cli)`
    );
    return 1;
  }
  // Preflight runs before server or host config is written. It only blocks the harness that failed:
  // on `install all` the other agents are still worth wiring. The non-zero exit keeps the failure
  // visible to whatever script invoked this.
  const blocked = new Set<string>();
  if (command === "install") {
    for (const t of targets) {
      const problem = t.preflight?.(ctx);
      if (!problem) continue;
      ctx.log?.(`\n❌ ${t.name}: ${problem}`);
      blocked.add(t.name);
    }
  }
  const runnable = targets.filter((t) => !blocked.has(t.name));
  // Resolve the server only when at least one harness can be installed, and before wiring any of
  // them so the first session already has a config to read.
  if (command === "install" && runnable.length > 0 && !configureServer(ctx, rawArgs)) return 1;

  const failed: string[] = [];
  for (const t of runnable) {
    if (t[command](ctx) === false) failed.push(t.name);
  }
  if (command === "install" && importHistory) {
    for (const t of runnable) importConversations(t.name, ctx);
  }
  if (blocked.size || failed.length) {
    const notInstalled = [...blocked, ...failed];
    ctx.log?.(`\n❌ not installed: ${notInstalled.join(", ")} — see the messages above.`);
    return 1;
  }
  // No completion message here: the CLI entry's InstallerUi outro reports success (and where the
  // settings live), so run() stays a silent-on-success engine for programmatic use.
  return 0;
}

/* c8 ignore start */
// npm exposes `bin` entries through a symlink. Node leaves argv[1] at that symlink path, so a
// direct URL comparison incorrectly makes the installed CLI a silent no-op. Resolve it first;
// source/dev invocations still work through the installer.js suffix fallback.
const mainPath = process.argv[1]
  ? (() => {
      try {
        return realpathSync(process.argv[1]);
      } catch {
        return process.argv[1];
      }
    })()
  : undefined;
const isMain = mainPath && import.meta.url === pathToFileURL(mainPath).href;
if (isMain || mainPath?.endsWith("installer.js")) {
  const dist = dirname(fileURLToPath(import.meta.url));
  const pkgRoot = dirname(dist);
  let version: string | undefined;
  try {
    version = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8")).version;
  } catch {
    version = undefined; // cosmetic only — a header without a version beats a crashed installer
  }
  const ui = createInstallerUi({
    home: homedir(),
    command: process.argv[2],
    version,
    harnessNames: INSTALLERS.map((i) => i.name),
    // configureServer's messages render as their own "server" group, but don't count as an agent.
    auxNames: ["server"],
    configPath: process.env.CONTEXTBASE_CONFIG || undefined,
  });
  ui.intro();
  const code = run(process.argv.slice(2), {
    home: homedir(),
    pkgRoot,
    dist,
    // Only a real terminal gets prompted; piped/CI installs take the documented default.
    // tty.isatty, NOT process.stdin.isTTY: the process.stdin getter initializes the stdin TTY
    // stream, which puts fd 0 in non-blocking mode and breaks readLineSync (see there).
    interactive: Boolean(isatty(0) && isatty(1)),
    log: ui.log,
    promptStyle: ui.prompt,
    selectPrompt: ui.select,
  });
  ui.outro(code);
  process.exit(code);
}
/* c8 ignore stop */
