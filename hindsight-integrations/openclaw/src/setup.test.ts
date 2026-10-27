import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseCliArgs, runNonInteractive } from "./setup.js";
const dirs: string[] = [];
afterEach(async () => {
  for (const dir of dirs.splice(0)) await rm(dir, { recursive: true, force: true });
});
async function configPath() {
  const dir = await mkdtemp(join(tmpdir(), "contextbase-setup-"));
  dirs.push(dir);
  return join(dir, "openclaw.json");
}
describe("remote setup", () => {
  it("rejects server installation options", () => {
    expect(() => parseCliArgs(["--mode", "embedded"])).toThrow();
    expect(() => parseCliArgs(["--provider", "openai"])).toThrow();
  });
  it("requires an endpoint and authorized Bank", async () => {
    const path = await configPath();
    await expect(
      runNonInteractive({
        help: false,
        noToken: false,
        configPath: path,
        mode: "cloud",
        token: "key",
      })
    ).rejects.toThrow("API URL");
    await expect(
      runNonInteractive({
        help: false,
        noToken: false,
        configPath: path,
        mode: "cloud",
        apiUrl: "https://api.example.com",
        token: "key",
      })
    ).rejects.toThrow("bank-id");
  });
  it("preserves other plugins and writes the service, SecretRef and static Bank", async () => {
    const path = await configPath();
    await writeFile(
      path,
      JSON.stringify({ other: 42, plugins: { entries: { other: { enabled: true } } } })
    );
    await runNonInteractive(
      parseCliArgs([
        "--mode",
        "cloud",
        "--api-url",
        "https://api.example.com/prefix/",
        "--token-env",
        "CONTEXTBASE_API_TOKEN",
        "--bank-id",
        "team",
        "--config-path",
        path,
      ])
    );
    const config = JSON.parse(await readFile(path, "utf8"));
    expect(config.other).toBe(42);
    expect(config.plugins.entries.other.enabled).toBe(true);
    expect(config.plugins.entries["contextbase-openclaw"].config).toMatchObject({
      contextbaseApiUrl: "https://api.example.com/prefix",
      contextbaseApiToken: { source: "env", id: "CONTEXTBASE_API_TOKEN" },
      bankId: "team",
      dynamicBankId: false,
    });
  });
  it("keeps an existing credential and explicit conversation-access opt-out", async () => {
    const path = await configPath();
    await writeFile(
      path,
      JSON.stringify({
        plugins: {
          entries: {
            "contextbase-openclaw": {
              hooks: { allowConversationAccess: false },
              config: {
                contextbaseApiUrl: "https://api.example.com",
                contextbaseApiToken: "existing",
                bankId: "old",
              },
            },
          },
        },
      })
    );
    await runNonInteractive(
      parseCliArgs(["--mode", "cloud", "--bank-id", "new", "--config-path", path])
    );
    const entry = JSON.parse(await readFile(path, "utf8")).plugins.entries["contextbase-openclaw"];
    expect(entry.config.contextbaseApiToken).toBe("existing");
    expect(entry.config.bankId).toBe("new");
    expect(entry.hooks.allowConversationAccess).toBe(false);
  });
});
