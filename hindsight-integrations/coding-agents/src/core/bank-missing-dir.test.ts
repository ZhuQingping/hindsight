import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { projectNameOf } from "./bank";

/**
 * Real git, real filesystem — deliberately NOT the mocked child_process of bank.test.ts, because
 * what is under test is how resolution behaves against paths that do and do not exist.
 *
 * Project provenance is recorded after the fact, so the directory it reports can already be gone: an ephemeral
 * worktree removed once the task finished, or a checkout moved mid-session (#3110).
 */
describe("project resolution when the working directory is gone", () => {
  let repo: string;

  beforeEach(() => {
    delete process.env.CLAUDE_PROJECT_DIR;
    repo = mkdtempSync(join(tmpdir(), "hs-gone-"));
    execFileSync("git", ["init", "-q"], { cwd: repo });
  });

  afterEach(() => {
    rmSync(repo, { recursive: true, force: true });
    delete process.env.CLAUDE_PROJECT_DIR;
  });

  it("names the repository rather than the deleted leaf directory", () => {
    // Never created: this is the state the hook actually observes once the worktree is removed.
    const gone = join(repo, ".agent", "worktrees", "agent-a33c4d63");
    expect(projectNameOf(gone)).toBe(`${basename(repo)}`);
  });

  it("keeps the historical answer while the directory still exists", () => {
    // The walk is a no-op for a live directory, so no existing bank moves.
    expect(projectNameOf(repo)).toBe(`${basename(repo)}`);
  });

  it("uses an exported project root when the walk lands outside the repository", () => {
    // A LINKED worktree is a sibling of the repo, not a child, so walking up leaves it entirely;
    // only the harness's own variable still names the project.
    process.env.CLAUDE_PROJECT_DIR = repo;
    const goneSibling = join(tmpdir(), "hs-gone-linked-worktree-never-created");
    expect(projectNameOf(goneSibling)).toBe(`${basename(repo)}`);
  });

  it("prefers a resolvable directory over the exported root", () => {
    const other = mkdtempSync(join(tmpdir(), "hs-other-"));
    execFileSync("git", ["init", "-q"], { cwd: other });
    process.env.CLAUDE_PROJECT_DIR = other;
    try {
      expect(projectNameOf(repo)).toBe(`${basename(repo)}`);
    } finally {
      rmSync(other, { recursive: true, force: true });
    }
  });

  it("never yields an empty project name", () => {
    // basename("/") is "", which produced bank ids like `coding-agent::` that name nothing.
    expect(projectNameOf("/")).toBe("unknown");
  });

  it("still yields a name for a directory that is not a repository", () => {
    const plain = mkdtempSync(join(tmpdir(), "hs-plain-"));
    try {
      expect(projectNameOf(plain)).toBe(`${basename(plain)}`);
    } finally {
      rmSync(plain, { recursive: true, force: true });
    }
  });

  it("keeps project metadata stable below a non-repository session root", () => {
    // Provenance follows the session root outside Git.
    const plain = mkdtempSync(join(tmpdir(), "hs-plain-"));
    const sub = join(plain, "analysis", "evidence");
    mkdirSync(sub, { recursive: true });
    try {
      for (const cwd of [plain, join(plain, "analysis"), sub]) {
        expect(projectNameOf(cwd, plain)).toBe(`${basename(plain)}`);
      }
    } finally {
      rmSync(plain, { recursive: true, force: true });
    }
  });

  it("still names the repository the agent is IN, not the session root", () => {
    // The session root is a rescue for what git cannot name, never an override: a session started
    // in a plain directory that then works inside a repo still gets that repo's project metadata.
    const plain = mkdtempSync(join(tmpdir(), "hs-plain-"));
    try {
      expect(projectNameOf(repo, plain)).toBe(`${basename(repo)}`);
    } finally {
      rmSync(plain, { recursive: true, force: true });
    }
  });

  it("names the session's repository in metadata when the agent steps outside it", () => {
    // Harness-neutral counterpart of the CLAUDE_PROJECT_DIR rescue above: a `cd /tmp` to run
    // something must not rename the bank after the directory it landed in.
    const outside = mkdtempSync(join(tmpdir(), "hs-outside-"));
    try {
      expect(projectNameOf(outside, repo)).toBe(`${basename(repo)}`);
    } finally {
      rmSync(outside, { recursive: true, force: true });
    }
  });
});
