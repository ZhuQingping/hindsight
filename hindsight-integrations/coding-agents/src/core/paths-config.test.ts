import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { deriveBankId } from "./bank";
import { applyBankConfig, resolveConfig } from "./config";

/** `paths.<prefix>`: entries customize behavior while sharing one connection. */
describe("paths.<prefix> overrides", () => {
  let root: string;
  let clientRepo: string;
  let otherRepo: string;

  beforeEach(() => {
    root = realpathSync(mkdtempSync(join(tmpdir(), "hs-paths-")));
    clientRepo = join(root, "work", "client-x");
    otherRepo = join(root, "oss", "tool");
    for (const d of [clientRepo, otherRepo]) {
      mkdirSync(d, { recursive: true });
      execFileSync("git", ["init", "-q"], { cwd: d });
    }
  });

  afterEach(() => rmSync(root, { recursive: true, force: true }));

  const resolve = (raw: Parameters<typeof resolveConfig>[0], directory: string) => {
    const cfg = resolveConfig(raw);
    return applyBankConfig(cfg, deriveBankId(cfg, directory, "codex"), directory);
  };

  it("applies the entry covering the directory and leaves every other directory alone", () => {
    const raw = {
      apiUrl: "http://server",
      apiToken: "default-key",
      paths: { [join(root, "work")]: { retainSessions: false } },
    };
    const client = resolve(raw, join(clientRepo, "src"));
    expect(client.cfg.retainSessions).toBe(false);
    expect(client.cfg.apiToken).toBe("default-key");
    expect(client.bankId).toBe("coding-agent::client-x");
    expect(resolve(raw, otherRepo).cfg.apiToken).toBe("default-key");
  });

  it("ignores directory endpoint, credential and daemon overrides", () => {
    const raw = {
      apiUrl: "https://service.example",
      apiToken: "global-key",
      paths: {
        [join(root, "work")]: {
          apiUrl: "https://other.example",
          apiToken: "other-key",
          serverMode: "daemon" as const,
        },
      },
    };
    const cfg = resolve(raw, clientRepo).cfg;
    expect(cfg.apiUrl).toBe("https://service.example");
    expect(cfg.apiToken).toBe("global-key");
    expect(cfg.serverMode).toBe("cloud");
  });

  it("picks the longest matching prefix", () => {
    const raw = {
      apiToken: "default-key",
      paths: {
        [join(root, "work")]: { retainSessions: false },
        [clientRepo]: { retainSessions: true },
      },
    };
    expect(resolve(raw, clientRepo).cfg.retainSessions).toBe(true);
  });

  it("lets a banks.<id> section override the path entry", () => {
    const raw = {
      apiToken: "default-key",
      paths: { [join(root, "work")]: { apiToken: "work-key", retainSessions: false } },
      banks: { "coding-agent::client-x": { apiToken: "bank-key" } },
    };
    const { cfg } = resolve(raw, clientRepo);
    expect(cfg.apiToken).toBe("default-key");
    expect(cfg.retainSessions).toBe(false);
  });

  it("cannot change bank resolution or approval", () => {
    const raw = {
      optInOnly: true,
      optInPaths: [join(root, "work")],
      paths: {
        [join(root, "work")]: {
          bankId: "hijack",
          bank: "hijack",
          optInPaths: [root],
          apiToken: "k",
        },
        [join(root, "oss")]: { optInOnly: false, apiToken: "k" },
      },
    };
    const client = resolve(raw, clientRepo);
    expect(client.bankId).toBe("coding-agent::client-x");
    expect(client.cfg.apiToken).toBeUndefined();
    expect(resolve(raw, otherRepo).cfg.disabled).toBe(true);
  });

  it("applies nothing without a directory", () => {
    const cfg = resolveConfig({ apiToken: "default-key", paths: { [root]: { apiToken: "k" } } });
    expect(applyBankConfig(cfg, "coding-agent::client-x").cfg.apiToken).toBe("default-key");
  });

  it("gives a linked worktree outside the tree its checkout's entry", () => {
    const worktree = join(root, "external-worktrees", "client-x");
    execFileSync("git", ["commit", "-q", "--allow-empty", "-m", "init"], {
      cwd: clientRepo,
      env: {
        ...process.env,
        GIT_AUTHOR_NAME: "t",
        GIT_AUTHOR_EMAIL: "t@t",
        GIT_COMMITTER_NAME: "t",
        GIT_COMMITTER_EMAIL: "t@t",
      },
    });
    mkdirSync(join(root, "external-worktrees"), { recursive: true });
    execFileSync("git", ["worktree", "add", "-q", "-b", "linked", worktree], { cwd: clientRepo });
    const raw = {
      apiToken: "default-key",
      paths: { [join(root, "work")]: { retainSessions: false } },
    };
    expect(resolve(raw, worktree).cfg.retainSessions).toBe(false);
  });
});
