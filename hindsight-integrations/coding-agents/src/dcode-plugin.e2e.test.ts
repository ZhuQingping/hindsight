import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const packageRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const dcodeAvailable = spawnSync("dcode", ["--version"], { stdio: "ignore" }).status === 0;
const runDcodeSmoke = process.env.AGENTSTRATUM_DCODE_E2E === "1" && dcodeAvailable;

describe.runIf(runDcodeSmoke)("native Dcode marketplace install", () => {
  it("installs the staged local marketplace in an isolated HOME", () => {
    const isolatedHome = mkdtempSync(join("/tmp", "agentstratum-dcode-e2e-"));
    const env = {
      ...process.env,
      HOME: isolatedHome,
      DEEPAGENTS_HOME: join(isolatedHome, ".deepagents"),
      DEEPAGENTS_CODE_PLUGIN_CACHE_DIR: join(isolatedHome, ".deepagents", "plugins"),
    };
    try {
      execFileSync(process.execPath, [join(packageRoot, "dist/installer.js"), "install", "dcode"], {
        cwd: packageRoot,
        env,
        stdio: "pipe",
      });
      const marketplacePath = join(
        isolatedHome,
        ".agentstratum",
        ".agents",
        "plugins",
        "marketplace.json"
      );
      expect(JSON.parse(readFileSync(marketplacePath, "utf8")).plugins).toContainEqual({
        name: "agentstratum-coding-agents",
        source: { source: "local", path: "./coding-agents" },
      });
      expect(existsSync(join(isolatedHome, ".agentstratum", "coding-agents", "plugin.json"))).toBe(
        true
      );
      expect(execFileSync("dcode", ["plugin", "list"], { env, encoding: "utf8" })).toContain(
        "enabled agentstratum-coding-agents@agentstratum-coding-agents"
      );
    } finally {
      execFileSync(
        process.execPath,
        [join(packageRoot, "dist/installer.js"), "uninstall", "dcode"],
        {
          cwd: packageRoot,
          env,
          stdio: "ignore",
        }
      );
      rmSync(isolatedHome, { recursive: true, force: true });
    }
  });
});

describe.runIf(!runDcodeSmoke)("native Dcode marketplace install", () => {
  it.skip("set AGENTSTRATUM_DCODE_E2E=1 with dcode installed to run the isolated CLI smoke test");
});
