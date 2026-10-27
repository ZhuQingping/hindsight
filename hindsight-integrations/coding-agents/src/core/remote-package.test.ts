import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { resolveConfig } from "./config";

describe("connection modes", () => {
  it("daemon mode derives the URL from apiPort, ignoring apiUrl", () => {
    // Resolving here (rather than at each client construction) is what lets the eight existing
    // call sites stay untouched.
    const cfg = resolveConfig({ serverMode: "daemon", apiUrl: "https://cloud.example" });
    expect(cfg.apiUrl).toBe("http://127.0.0.1:9077");
  });

  it("uses a custom daemon port", () => {
    expect(resolveConfig({ serverMode: "daemon", apiPort: 9999 }).apiUrl).toBe(
      "http://127.0.0.1:9999"
    );
  });

  it("defaults to cloud, leaving today's behaviour unchanged", () => {
    const cfg = resolveConfig({});
    expect(cfg.serverMode).toBe("cloud");
    expect(cfg.apiUrl).toBe("");
  });

  it("self-hosted keeps the configured apiUrl", () => {
    const cfg = resolveConfig({ serverMode: "self-hosted", apiUrl: "http://localhost:8888" });
    expect(cfg.apiUrl).toBe("http://localhost:8888");
  });

  // 9077, not contextbase-all's 8888: 8888 is the conventional port for a server the user runs, and
  // a daemon must never squat on it.
  it("defaults the daemon port to 9077", () => {
    expect(resolveConfig({ serverMode: "daemon" }).apiPort).toBe(9077);
  });
});

describe("every harness entrypoint checks its remote connection", () => {
  const SRC = fileURLToPath(new URL("..", import.meta.url));

  /** Client builders covered through their caller or used only for diagnostics. */
  const EXEMPT: Record<string, string> = {
    "status.ts": "diagnostic — reports what is running; starting one would falsify the report",
    "deepen.ts": "spawned after the seed validates the remote connection",
    "mcp-server.ts": "validates the remote endpoint when building each tool context",
    "core/hook.ts": "validates the endpoint through resolveHookRuntime",
    "core/host-client.ts":
      "the shared builder itself, not an entrypoint — its CALLERS are the request origins this checks",
  };

  /** A module is a request origin if it constructs a client directly OR asks the shared builder
   *  (core/host-client.ts) for one — the long-lived hosts do the latter, and reading only for
   *  `new ContextBaseClient(` would silently stop checking every one of them. */
  const buildsClient = (src: string): boolean =>
    src.includes("new ContextBaseClient(") || src.includes("resolveHostMemory(");

  function sourceFiles(dir: string, prefix = ""): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory())
        return entry.name === "e2e" ? [] : sourceFiles(join(dir, entry.name), rel);
      return entry.name.endsWith(".ts") && !entry.name.includes(".test.") ? [rel] : [];
    });
  }

  it("validates remote connections directly or through the shared runtime", () => {
    const unreached = sourceFiles(SRC).filter((rel) => {
      if (rel in EXEMPT) return false;
      const src = readFileSync(join(SRC, rel), "utf8");
      if (!buildsClient(src)) return false;
      // RuntimeCore validates the connection for persistent-plugin hosts.
      return !src.includes("ensureRemoteConnection") && !src.includes("RuntimeCore");
    });
    expect(unreached).toEqual([]);
  });

  // An exemption for a file that no longer builds a client is a stale claim about live code.
  it("keeps no exemption for a module that stopped building a client", () => {
    const stale = Object.keys(EXEMPT).filter(
      (rel) => !buildsClient(readFileSync(join(SRC, rel), "utf8"))
    );
    expect(stale).toEqual([]);
  });
});
