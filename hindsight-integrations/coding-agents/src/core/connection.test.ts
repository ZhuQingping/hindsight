import { createServer } from "node:http";
import type { AddressInfo } from "node:net";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ensureRemoteConnection, validateRemoteEndpoint } from "./connection";
import { applyBankConfig, loadConfig, resolveConfig } from "./config";
import { ContextBaseClient } from "./contextbase";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { version } from "../../package.json";

afterEach(() => vi.unstubAllEnvs());

describe("remote connection contract", () => {
  it("requires an endpoint and refuses local engine mode", async () => {
    await expect(ensureRemoteConnection(resolveConfig({}))).rejects.toThrow("API Endpoint");
    await expect(ensureRemoteConnection(resolveConfig({ serverMode: "daemon" }))).rejects.toThrow(
      "Local engines"
    );
  });

  it.each([
    "",
    "file:///tmp/api",
    "https://u:p@tenant.example",
    "https://tenant.example?key=secret",
    "https://tenant.example#x",
  ])("rejects unsafe endpoint %s", (url) => {
    expect(() => validateRemoteEndpoint(url)).toThrow();
  });

  it("keeps one connection across harness, path and bank overrides", () => {
    const root = mkdtempSync(join(tmpdir(), "contextbase-connection-"));
    try {
      const path = join(root, "config.json");
      const other = { apiUrl: "https://other.example", apiToken: "other-key" };
      writeFileSync(
        path,
        JSON.stringify({
          apiUrl: "https://default.example/",
          apiToken: "default-key",
          harnesses: { codex: other },
          paths: { [root]: other },
          banks: { b: other },
        })
      );
      const cfg = applyBankConfig(loadConfig({ path, harness: "codex" }), "b", root).cfg;
      expect(cfg.apiUrl).toBe("https://default.example");
      expect(cfg.apiToken).toBe("default-key");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("sends each configured connection and bearer token to its own HTTP endpoint", async () => {
    const seen: string[][] = [[], []];
    const userAgents: (string | undefined)[] = [];
    const servers = seen.map((requests) =>
      createServer((req, res) => {
        requests.push(`${req.url} ${req.headers.authorization}`);
        userAgents.push(req.headers["user-agent"]);
        res.writeHead(req.headers.authorization === "Bearer rejected" ? 401 : 200, {
          "Content-Type": "application/json",
        });
        res.end("{}");
      })
    );
    try {
      for (const server of servers)
        await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
      const urls = servers.map((s) => `http://127.0.0.1:${(s.address() as AddressInfo).port}`);
      for (const [i, apiUrl] of urls.entries()) {
        const client = new ContextBaseClient({ apiUrl, apiToken: `key-${i}`, bank: "b" });
        await client.req("GET", client.bankUrl());
      }
      const denied = new ContextBaseClient({ apiUrl: urls[0], apiToken: "rejected", bank: "b" });
      await expect(denied.req("GET", denied.bankUrl())).rejects.toThrow("401");
      expect(seen).toEqual([
        ["/v1/default/banks/b Bearer key-0", "/v1/default/banks/b Bearer rejected"],
        ["/v1/default/banks/b Bearer key-1"],
      ]);
      expect(userAgents).toEqual(Array(3).fill(`contextbase-coding-agents/${version}`));
    } finally {
      await Promise.all(
        servers.map((server) => new Promise<void>((resolve) => server.close(() => resolve())))
      );
    }
  });
});
