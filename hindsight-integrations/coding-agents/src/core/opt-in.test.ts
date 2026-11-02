import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { configuredBankId, isOptedIn } from "./bank";
import { applyBankConfig, resolveConfig } from "./config";

/**
 * Opt-in-only: memory runs in declared projects and nowhere else. Real directories, because the
 * question is entirely about how a working directory relates to what was configured.
 */
describe("optInOnly", () => {
  let root: string;
  let approved: string;
  let other: string;

  beforeEach(() => {
    root = mkdtempSync(join(tmpdir(), "hs-optin-"));
    approved = join(root, "work", "client-x");
    other = join(root, "scratch", "throwaway");
    for (const d of [approved, other]) {
      mkdirSync(d, { recursive: true });
      execFileSync("git", ["init", "-q"], { cwd: d });
    }
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    delete process.env.CLAUDE_PROJECT_DIR;
  });

  it("allows everything when it is off — the zero-setup default is unchanged", () => {
    const cfg = resolveConfig({ bankId: "fixed" });
    expect(isOptedIn(cfg, approved)).toBe(true);
    expect(isOptedIn(cfg, other)).toBe(true);
  });

  it("approves a listed directory and the repos beneath it", () => {
    const cfg = resolveConfig({
      bankId: "fixed",
      optInOnly: true,
      optInPaths: [join(root, "work")],
    });
    expect(isOptedIn(cfg, approved)).toBe(true);
    expect(isOptedIn(cfg, join(approved, "src", "deep"))).toBe(true);
    expect(isOptedIn(cfg, other)).toBe(false);
  });

  it("carries path approval from a checkout to its linked worktree", () => {
    const worktree = join(root, "external-worktrees", "client-x");
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
      ],
      { cwd: approved }
    );
    mkdirSync(join(root, "external-worktrees"), { recursive: true });
    execFileSync("git", ["worktree", "add", "-q", "-b", "linked", worktree], { cwd: approved });

    const checkoutParent = join(realpathSync(root), "work");
    const byPath = resolveConfig({ optInOnly: true, optInPaths: [checkoutParent] });
    expect(isOptedIn(byPath, worktree)).toBe(true);

    const nested = join(worktree, "src", "deep");
    mkdirSync(nested, { recursive: true });
    expect(isOptedIn(byPath, nested)).toBe(true);
    rmSync(nested, { recursive: true });
    expect(isOptedIn(byPath, nested)).toBe(true);

    execFileSync("git", ["worktree", "remove", "--force", worktree], { cwd: approved });
    process.env.CLAUDE_PROJECT_DIR = approved;
    expect(isOptedIn(byPath, worktree)).toBe(true);
  });

  it("carries hub approval to bare-hub worktrees", () => {
    const hub = join(root, "bare-hub");
    const bare = join(hub, ".bare");
    const seed = join(root, "bare-seed");
    mkdirSync(hub, { recursive: true });
    execFileSync("git", ["init", "--bare", "-q", bare]);
    execFileSync("git", ["init", "-q", "-b", "main", seed]);
    execFileSync("git", ["-C", seed, "config", "user.email", "test@example.invalid"]);
    execFileSync("git", ["-C", seed, "config", "user.name", "Test"]);
    execFileSync("git", ["-C", seed, "commit", "--allow-empty", "-qm", "seed"]);
    execFileSync("git", ["-C", seed, "push", "-q", bare, "HEAD:refs/heads/main"]);
    writeFileSync(join(hub, ".git"), "gitdir: ./.bare\n");
    const worktree = join(root, "bare-worktree");
    execFileSync("git", ["--git-dir", bare, "worktree", "add", "-q", worktree, "main"]);

    const canonicalHub = realpathSync(hub);
    const byPath = resolveConfig({ optInOnly: true, optInPaths: [canonicalHub] });
    expect(isOptedIn(byPath, worktree)).toBe(true);
  });

  it("keeps a linked worktree denied when its checkout is outside every approved path", () => {
    const worktree = join(root, "external-worktrees", "throwaway");
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
      ],
      { cwd: other }
    );
    mkdirSync(join(root, "external-worktrees"), { recursive: true });
    execFileSync("git", ["worktree", "add", "-q", "-b", "linked", worktree], { cwd: other });

    const cfg = resolveConfig({
      bankId: "fixed",
      optInOnly: true,
      optInPaths: [join(realpathSync(root), "work")],
    });
    expect(isOptedIn(cfg, worktree)).toBe(false);
  });

  it("does not carry checkout approval to linked worktrees when resolution is disabled", () => {
    const worktree = join(root, "external-worktrees", "client-x");
    execFileSync(
      "git",
      [
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "--allow-empty",
        "-qm",
        "seed",
      ],
      { cwd: approved }
    );
    mkdirSync(join(root, "external-worktrees"), { recursive: true });
    execFileSync("git", ["worktree", "add", "-q", "-b", "linked", worktree], { cwd: approved });

    const cfg = resolveConfig({
      bankId: "fixed",
      optInOnly: true,
      optInPaths: [join(realpathSync(root), "work")],
      resolveWorktrees: false,
    });
    expect(isOptedIn(cfg, worktree)).toBe(false);
  });

  it("does not let a bare bankId approve anything", () => {
    // It names a bank, not a project, so it cannot say which work may be remembered. A privacy
    // switch fails closed.
    const cfg = resolveConfig({ optInOnly: true, bankId: "shared" });
    expect(isOptedIn(cfg, approved)).toBe(false);
  });

  it("renders an unlisted project inert through the gate every entry point already checks", () => {
    const cfg = resolveConfig({ bankId: "fixed", optInOnly: true, optInPaths: [approved] });
    const inert = applyBankConfig(cfg, configuredBankId(cfg), other);
    expect(inert.cfg.disabled).toBe(true);

    const live = applyBankConfig(cfg, configuredBankId(cfg), approved);
    expect(live.cfg.disabled).toBe(false);
    expect(live.bankId).toBe("fixed");
  });

  it("stays inert when no directory is known and the switch is on", () => {
    const cfg = resolveConfig({ bankId: "fixed", optInOnly: true, optInPaths: [approved] });
    expect(isOptedIn(cfg, "")).toBe(false);
  });

  it("ignores a banks.<id> section trying to set it — approval is decided before that runs", () => {
    const cfg = resolveConfig({
      bankId: "fixed",
      optInOnly: true,
      optInPaths: [approved],
      banks: { fixed: { optInOnly: false } as never },
    });
    expect(applyBankConfig(cfg, configuredBankId(cfg), other).cfg.disabled).toBe(true);
  });
});
