import { describe, it, expect } from "vitest";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageDir = resolve(__dirname, "..");
const manifest = JSON.parse(readFileSync(resolve(packageDir, "package.json"), "utf-8"));
const packScript = readFileSync(resolve(packageDir, "scripts", "pack-manifest.mjs"), "utf-8");

/** The field names `pack-manifest.mjs` strips, read from the script itself. */
function strippedFields(): Set<string> {
  const list = packScript.match(/const DEV_ONLY_FIELDS = \[([^\]]*)\]/);
  if (!list) throw new Error("Could not locate DEV_ONLY_FIELDS in pack-manifest.mjs");
  return new Set([...list[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]));
}

// OpenClaw installs a plugin by running a full `npm install` inside the
// extracted package directory, so anything left in the published manifest is
// resolved on the user's machine. Shipping devDependencies broke every install
// on npm 10 once vitest 5 was published ("Cannot read properties of null
// (reading 'edgesOut')"). These assertions are the cheap guard; the real
// end-to-end proof is the `smoke-openclaw-install` CI job.
describe("published manifest", () => {
  it("wires the prepack/postpack pair that strips dev-only fields", () => {
    expect(manifest.scripts.prepack).toBe("node scripts/pack-manifest.mjs strip");
    expect(manifest.scripts.postpack).toBe("node scripts/pack-manifest.mjs restore");
  });

  it("strips every dev-only field the package actually declares", () => {
    // A new dev-only top-level field added to package.json without being added
    // to DEV_ONLY_FIELDS would ship to users and be installed by OpenClaw.
    const devOnlyPresent = ["devDependencies", "overrides"].filter((f) => f in manifest);
    const stripped = strippedFields();
    const unstripped = devOnlyPresent.filter((f) => !stripped.has(f));
    expect(unstripped, "dev-only package.json fields that would ship to users").toEqual([]);
  });

  it("keeps the runtime dependencies the plugin needs at runtime", () => {
    // The counterpart risk: stripping too much. These three are imported by
    // dist/ and must survive into the published manifest.
    const stripped = strippedFields();
    expect(stripped.has("dependencies")).toBe(false);
    expect(Object.keys(manifest.dependencies).sort()).toEqual([
      "@clack/prompts",
      "contextbase-client",
    ]);
  });
});

describe.skipIf(process.platform === "win32")("smoke-test archive cleanup", () => {
  it.each([false, true])("preserves caller archives with temporary build=%s", (ownBuild) => {
    const work = mkdtempSync(resolve(tmpdir(), "contextbase-smoke-cleanup-"));
    try {
      const tarball = resolve(work, "contextbase-openclaw-1.0.0.tgz");
      writeFileSync(tarball, "caller archive");
      const packDir = ownBuild ? resolve(work, "temporary build") : "";
      if (packDir) mkdirSync(packDir);
      const script = readFileSync(resolve(packageDir, "scripts/smoke-test.sh"), "utf8");
      const cleanup = script.match(/^cleanup\(\) \{[\s\S]*?^\}/m)?.[0];
      if (!cleanup) throw new Error("Could not locate smoke-test cleanup");
      execFileSync("bash", ["-c", `openclaw() { :; }; log() { :; }; ${cleanup}\ncleanup`], {
        env: {
          ...process.env,
          PLUGIN_DIR: work,
          TARBALL: tarball,
          PACK_DIR: packDir,
          EXT_DIR: resolve(work, "extension"),
          CONFIG_BACKUP: "",
          EXT_BACKUP: "",
        },
      });
      expect(readFileSync(tarball, "utf8")).toBe("caller archive");
      if (packDir) expect(existsSync(packDir)).toBe(false);
    } finally {
      rmSync(work, { recursive: true, force: true });
    }
  });
});
