import { describe, expect, it, vi } from "vitest";
import type { PluginInput } from "@opencode-ai/plugin";
import { log } from "../core/log";
import { createPluginEntry, resolveProjectDirectory } from "./plugin-entry";

describe("persistent plugin initialization", () => {
  it("keeps the host usable when background seeding has no endpoint", async () => {
    vi.stubEnv("AGENTSTRATUM_API_URL", "");
    vi.stubEnv("AGENTSTRATUM_SERVER_MODE", "cloud");
    vi.stubEnv("AGENTSTRATUM_BANK_ID", "configuration-regression");
    vi.stubEnv("AGENTSTRATUM_DISABLED", "false");
    vi.stubEnv("AGENTSTRATUM_OPT_IN_ONLY", "false");
    vi.stubEnv("AGENTSTRATUM_DISABLE_HOOKS", "");
    const warning = vi.spyOn(log, "warn");
    try {
      // Only the host fields this entrypoint reads; use the real runtime, not a seed mock.
      const hooks = await createPluginEntry("opencode")({
        directory: "/repos/configuration-regression",
        worktree: "/repos/configuration-regression",
      } as PluginInput);
      // Flush fire-and-forget initialization. Vitest also fails on unhandled rejections here.
      await new Promise<void>((resolve) => setImmediate(resolve));
      expect(hooks.tool?.agentstratum_reflect).toBeDefined();
      expect(hooks["chat.message"]).toBeTypeOf("function");
      expect(warning).toHaveBeenCalledWith(
        "opencode",
        expect.stringContaining("AGENTSTRATUM_API_URL")
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
