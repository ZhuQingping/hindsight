/** Explicit Bank selection, plus independent Git project metadata and opt-in helpers. */
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, normalize, sep } from "node:path";
import { diag } from "./diag";
import { probeGitLayout } from "./git-layout";
import { log } from "./log";
import { RemoteConnectionError } from "./connection";

export interface BankConfig {
  bankId?: string;
  resolveWorktrees?: boolean; // default true: worktrees inherit checkout approval and behavior
  optInOnly?: boolean; // memory runs ONLY where opted in (see isOptedIn)
  optInPaths?: string[]; // directories opted in, matched as prefixes
}

/** The Git project root for provenance and path approval, or the reason it is unavailable. */
export type ProjectRoot =
  | { status: "resolved"; root: string }
  | { status: "absent" }
  | { status: "failed"; reason: string };

/** A failed Git probe cannot safely supply repository provenance. */
export class ProjectResolutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectResolutionError";
  }
}

/** Main-worktree root for a directory inside a git repo (worktree- and bare-repo-aware). */
export function resolveProjectRoot(directory: string): ProjectRoot {
  if (!directory) return { status: "absent" };
  const layout = probeGitLayout(directory);
  if (layout.status !== "resolved") return layout;
  const commonDir = layout.commonDir;
  // Clones + `git worktree add`: common-dir is `<main root>/.git`.
  if (basename(commonDir) === ".git") return { status: "resolved", root: dirname(commonDir) };

  // A bare-hub keeps its bare repository in a hidden plumbing directory (usually `.bare`), while a
  // standalone bare clone uses its directory name as the project identity.
  if (basename(commonDir).startsWith(".") && layout.bare) {
    return { status: "resolved", root: dirname(commonDir) };
  }

  // Preserve the historical name for standalone bare repositories such as `myrepo.git`.
  return { status: "resolved", root: commonDir };
}

/** Worktree-aware repo name for DOCUMENT IDS (gitlog:<name>, commit context): all worktrees of a
 *  repo must produce the SAME name, or each worktree writes its own gitlog document into the
 *  shared bank (seen in the wild: gitlog:contextbase-wt7 next to gitlog:memory-poc). */
export function projectNameOf(directory: string, sessionRoot?: string): string {
  return gitProjectName(directory, true, sessionRoot);
}

/**
 * Project roots a harness exports into its hook process. Only Claude Code is known to export one,
 * so this is deliberately a list of ONE rather than a guess at nine names — the mechanism that
 * covers every harness is the ancestor walk in `nearestExistingDir`, not this.
 *
 * It earns its place for the case the walk cannot reach: a LINKED worktree (a sibling directory,
 * not a child of the repo) that has been deleted. Walking up from it lands outside the repository
 * entirely, while this variable still names it. The session root passed by the hook runtimes covers
 * the same case harness-neutrally when a session is what is being resolved.
 */
const PROJECT_ROOT_ENV = ["CLAUDE_PROJECT_DIR"] as const;

/**
 * The nearest ancestor of `directory` that still exists, or "" if none does.
 *
 * A hook may run after its working directory was deleted. Walking up finds the surviving
 * repository for document provenance; session/exported roots cover removed sibling worktrees.
 */
function nearestExistingDir(directory: string): string {
  let current = directory;
  while (current) {
    if (existsSync(current)) return current;
    const parent = dirname(current);
    if (parent === current) return "";
    current = parent;
  }
  return "";
}

/** Basename for project metadata, or "unknown" at the filesystem root. */
function dirName(directory: string): string {
  return (directory && basename(directory)) || "unknown";
}

/** Main-worktree identity for provenance and path approval. Prefer the actual directory, then
 * the session root and exported project root when the directory has gone away. */
function mainWorktreeRoot(directory: string, sessionRoot = ""): ProjectRoot {
  const candidates = [
    nearestExistingDir(directory),
    sessionRoot,
    ...PROJECT_ROOT_ENV.map((v) => process.env[v] || ""),
  ];
  // A failure anywhere in the cascade is remembered but not returned early: a later candidate may
  // still answer, and only when NONE does does the difference between "no repository here" and
  // "could not tell" matter.
  let failure: ProjectRoot | null = null;
  for (const candidate of candidates) {
    if (!candidate) continue;
    const projectRoot = resolveProjectRoot(candidate);
    if (projectRoot.status === "resolved") return projectRoot;
    if (projectRoot.status === "failed") failure = projectRoot;
  }
  return failure ?? { status: "absent" };
}

function gitProjectName(directory: string, resolveWorktrees: boolean, sessionRoot = ""): string {
  if (resolveWorktrees) {
    const projectRoot = mainWorktreeRoot(directory, sessionRoot);
    if (projectRoot.status === "resolved") return basename(projectRoot.root);
    // A failed probe cannot safely fall back to the worktree name for provenance.
    if (projectRoot.status === "failed") {
      throw new ProjectResolutionError(
        `git probe failed for ${directory} (${projectRoot.reason}) — refusing to guess project metadata`
      );
    }
  }
  // Outside Git, keep project provenance stable as the agent navigates within a session.
  return dirName(sessionRoot || directory);
}

/** A configured directory, `~`-expanded and normalised, without a trailing separator. */
function configuredDir(dir: string): string {
  const expanded = dir === "~" || dir.startsWith("~/") ? join(homedir(), dir.slice(1)) : dir;
  return normalize(expanded).replace(new RegExp(`\\${sep}+$`), "");
}

/** Whether `directory` IS `configured`, or lives under it. */
function isWithin(directory: string, configured: string): boolean {
  return directory === configured || directory.startsWith(configured + sep);
}

/** Longest-prefix match of `directory` against the map's absolute paths (exact or ancestor). */
function mapLookup<T>(map: Record<string, T>, directory: string): T | undefined {
  const cwd = normalize(directory);
  let best: { len: number; value: T } | undefined;
  for (const [dir, value] of Object.entries(map)) {
    const p = configuredDir(dir);
    if (isWithin(cwd, p)) {
      if (!best || p.length > best.len) best = { len: p.length, value };
    }
  }
  return best?.value;
}

/** Literal directory first, then the main checkout for inherited approval and behavior. */
function lookupDirectories(config: BankConfig, directory: string, sessionRoot = ""): string[] {
  const directories = [normalize(directory)];
  if (config.resolveWorktrees ?? true) {
    // A failed probe leaves only literal-path approval, which cannot broaden access.
    const projectRoot = mainWorktreeRoot(directory, sessionRoot);
    const normalizedRoot = projectRoot.status === "resolved" ? normalize(projectRoot.root) : "";
    if (normalizedRoot && normalizedRoot !== directories[0]) directories.push(normalizedRoot);
  }
  return directories;
}

/** Explicit path opt-in limits where memory runs; it never selects a Bank. */
export function isOptedIn(config: BankConfig, directory: string): boolean {
  if (!config.optInOnly) return true;
  if (!directory) return false;
  const directories = lookupDirectories(config, directory);
  if (
    directories.some((candidate) =>
      (config.optInPaths ?? []).some(
        (configured) => configured && isWithin(candidate, configuredDir(configured))
      )
    )
  )
    return true;
  return false;
}

/** The `paths.<prefix>` section for a directory, if any: longest prefix, checked against the
 *  directory first and then its main Git root, so a linked
 *  worktree outside the tree still gets its checkout's section. */
export function pathSection<T>(
  config: BankConfig,
  paths: Record<string, T> | undefined,
  directory: string
): T | undefined {
  if (!directory || !paths) return undefined;
  return lookupDirectories(config, directory)
    .map((candidate) => mapLookup(paths, candidate))
    .find((section) => section !== undefined);
}

/** Return the explicitly configured Bank, never a name derived from a directory. */
export function configuredBankId(config: Pick<BankConfig, "bankId">): string {
  const bankId = typeof config.bankId === "string" ? config.bankId.trim() : "";
  if (!bankId) {
    throw new RemoteConnectionError(
      "Bank ID is required. Run contextbase-coding-agents bank use <BANK_ID> or set bankId in the configuration."
    );
  }
  return bankId;
}

/** Hooks disable memory with a diagnostic when configuration is incomplete. */
export function configuredBankIdOrSkip(
  config: Pick<BankConfig, "bankId">,
  harness = "coding"
): string | null {
  try {
    return configuredBankId(config);
  } catch (error) {
    if (!(error instanceof RemoteConnectionError)) throw error;
    log.warn(harness, error.message);
    diag(harness, "bank_unconfigured", { error: error.message });
    return null;
  }
}
