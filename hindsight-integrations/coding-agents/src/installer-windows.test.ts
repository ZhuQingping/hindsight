import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { execFileSync } from "node:child_process";
import { defaultClaudeMcp } from "./installer";

vi.mock("node:child_process", () => ({ execFileSync: vi.fn(), spawn: vi.fn(), execSync: vi.fn() }));
const platform = Object.getOwnPropertyDescriptor(process, "platform")!;
const homes: string[] = [];
afterEach(() => {
  Object.defineProperty(process, "platform", platform);
  vi.resetAllMocks();
  for (const home of homes.splice(0)) rmSync(home, { recursive: true, force: true });
});

describe("Windows Claude MCP registration", () => {
  it.each(["cli.js", "cli-wrapper.cjs"])(
    "launches npm %s through Node without a shell",
    (launcher) => {
      Object.defineProperty(process, "platform", { value: "win32", configurable: true });
      const home = mkdtempSync(join(tmpdir(), "claude npm & "));
      homes.push(home);
      const entry = join(home, "node_modules", "@anthropic-ai", "claude-code", launcher);
      mkdirSync(dirname(entry), { recursive: true });
      writeFileSync(entry, "");
      vi.mocked(execFileSync).mockReturnValueOnce(join(home, "claude.cmd") + "\r\n");
      const args = [
        "mcp",
        "add",
        "contextbase",
        "--",
        "node",
        "C:\\User name & team\\mcp-server.js",
      ];
      expect(defaultClaudeMcp(args)).toBe(true);
      expect(execFileSync).toHaveBeenNthCalledWith(1, "where.exe", ["claude"], {
        encoding: "utf8",
      });
      expect(execFileSync).toHaveBeenNthCalledWith(2, process.execPath, [entry, ...args], {
        stdio: "pipe",
      });
    }
  );
  it("uses the native executable when installed", () => {
    Object.defineProperty(process, "platform", { value: "win32", configurable: true });
    vi.mocked(execFileSync).mockReturnValueOnce("C:\\bin\\claude.exe\r\n");
    expect(defaultClaudeMcp(["mcp", "list"])).toBe(true);
    expect(execFileSync).toHaveBeenLastCalledWith("C:\\bin\\claude.exe", ["mcp", "list"], {
      stdio: "pipe",
    });
  });
  it("reports command failure", () => {
    vi.mocked(execFileSync).mockImplementation(() => {
      throw new Error("unavailable");
    });
    const log = vi.fn();
    expect(defaultClaudeMcp(["mcp", "list"], log)).toBe(false);
    expect(log).toHaveBeenCalledWith(expect.stringContaining("unavailable"));
  });
});
