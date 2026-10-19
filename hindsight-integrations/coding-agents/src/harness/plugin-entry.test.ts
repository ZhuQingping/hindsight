import { describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { PluginInput } from "@opencode-ai/plugin";
import { log } from "../core/log";
import { createPluginEntry, resolveProjectDirectory } from "./plugin-entry";

// A bad memory configuration must not launch any subprocess, including a local engine.
const localProcesses = vi.hoisted(() => ({
  spawn: vi.fn(),
  spawnSync: vi.fn(),
  exec: vi.fn(),
  execSync: vi.fn(),
  execFile: vi.fn(),
  execFileSync: vi.fn(),
}));
vi.mock("node:child_process", async (importOriginal) => ({
  ...(await importOriginal<typeof import("node:child_process")>()),
  ...localProcesses,
}));

describe("persistent plugin initialization", () => {
  it("keeps the host usable when background seeding has no endpoint", async () => {
    vi.stubEnv("CONTEXTBASE_API_URL", "");
    vi.stubEnv("CONTEXTBASE_SERVER_MODE", "cloud");
    vi.stubEnv("CONTEXTBASE_BANK_ID", "configuration-regression");
    vi.stubEnv("CONTEXTBASE_DISABLED", "false");
    vi.stubEnv("CONTEXTBASE_OPT_IN_ONLY", "false");
    vi.stubEnv("CONTEXTBASE_DISABLE_HOOKS", "");
    const warning = vi.spyOn(log, "warn");
    try {
      // Only the host fields this entrypoint reads; use the real runtime, not a seed mock.
      const hooks = await createPluginEntry("opencode")({
        directory: "/repos/configuration-regression",
        worktree: "/repos/configuration-regression",
      } as PluginInput);
      // Flush fire-and-forget initialization. Vitest also fails on unhandled rejections here.
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(hooks.tool?.contextbase_reflect).toBeDefined();
      expect(hooks["chat.message"]).toBeTypeOf("function");
      expect(warning).toHaveBeenCalledWith(
        "opencode",
        expect.stringContaining("CONTEXTBASE_API_URL")
      );
    } finally {
      warning.mockRestore();
      vi.unstubAllEnvs();
    }
  });
});

describe("resolveProjectDirectory", () => {
  it("prefers a meaningful worktree", () => {
    expect(
      resolveProjectDirectory({
        worktree: "/Users/me/project",
        directory: "/Users/me/workspace",
      })
    ).toBe("/Users/me/project");
  });

  it("falls back from the POSIX root to the workspace directory", () => {
    expect(resolveProjectDirectory({ worktree: "/", directory: "/Users/me/workspace" })).toBe(
      "/Users/me/workspace"
    );
  });

  it.each(["C:\\", "C:/"])(
    "falls back from the Windows root %s to the workspace directory",
    (worktree) => {
      expect(resolveProjectDirectory({ worktree, directory: "C:\\Users\\me\\workspace" })).toBe(
        "C:\\Users\\me\\workspace"
      );
    }
  );

  it("falls back when worktree is empty", () => {
    expect(resolveProjectDirectory({ worktree: "", directory: "/Users/me/workspace" })).toBe(
      "/Users/me/workspace"
    );
  });
});

describe("invalid remote settings at the real plugin boundary", () => {
  it.each([
    { apiUrl: "file:///tmp/api" },
    { apiUrl: "definitely-not-a-url" },
    { apiUrl: "http://configured.example", serverMode: "daemon" },
  ])("keeps the host inert for %j without requests or engine startup", async (configuration) => {
    const dir = mkdtempSync(join(tmpdir(), "contextbase-invalid-plugin-"));
    const path = join(dir, "config.json");
    writeFileSync(path, JSON.stringify(configuration));
    vi.stubEnv("CONTEXTBASE_CONFIG", path);
    vi.stubEnv("CONTEXTBASE_BANK_ID", "invalid-remote-config");
    for (const process of Object.values(localProcesses)) process.mockClear();
    vi.stubEnv("CONTEXTBASE_DISABLED", "false");
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    vi.resetModules();
    const { log: runtimeLog } = await import("../core/log");
    const warning = vi.spyOn(runtimeLog, "warn");
    try {
      const { createPluginEntry: entry } = await import("./plugin-entry");
      const hooks = await entry("opencode")({ directory: dir, worktree: dir } as PluginInput);
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(hooks).toEqual({});
      expect(fetch).not.toHaveBeenCalled();
      for (const process of Object.values(localProcesses)) expect(process).not.toHaveBeenCalled();
      expect(warning).toHaveBeenCalledWith(
        "opencode",
        expect.stringContaining("Memory integration disabled")
      );
    } finally {
      warning.mockRestore();
      vi.unstubAllEnvs();
      vi.unstubAllGlobals();
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
