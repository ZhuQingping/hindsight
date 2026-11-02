import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let root: string;
let cfgPath: string;

/** `CONFIG_PATH` is resolved from the environment when core/config is first imported, so each case
 *  points CONTEXTBASE_CONFIG at its own file and re-imports the module graph. */
async function loadFactory() {
  vi.resetModules();
  process.env.CONTEXTBASE_CONFIG = cfgPath;
  return import("./host-client");
}

function writeConfig(value: Record<string, unknown>): void {
  mkdirSync(join(cfgPath, ".."), { recursive: true });
  writeFileSync(cfgPath, JSON.stringify({ bankId: "fixed", ...value }));
}

const ENV = { ...process.env };

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "hs-host-"));
  cfgPath = join(root, "coding-agent.json");
});

afterEach(() => {
  process.env = { ...ENV };
  rmSync(root, { recursive: true, force: true });
});

describe("resolveHostMemory", () => {
  it("forwards every client setting the hosts used to pass by hand", async () => {
    // dsh and Prime Agent each hand-built their ClientOpts and both omitted maxParallelRetains, so
    // those two hosts silently ignored the setting. One builder is what stops that recurring.
    writeConfig({ apiUrl: "http://server", apiToken: "k", maxParallelRetains: 3 });
    const { resolveHostMemory } = await loadFactory();

    const { client } = resolveHostMemory("dsh", root);
    expect(client.apiUrl).toBe("http://server");
    expect(client.apiToken).toBe("k");
    expect(client.maxParallelRetains).toBe(3);
  });

  it("shares the configured Bank across directories and harnesses, without a repository page subject", async () => {
    writeConfig({ apiUrl: "http://server", bankId: "shared" });
    const { resolveHostMemory } = await loadFactory();
    for (const dir of [root, "/missing/repository", "/other/project"]) {
      for (const host of ["dsh", "claude-code", "codex", "opencode"]) {
        const result = resolveHostMemory(host, dir);
        expect(result.bankId).toBe("shared");
        expect(result.client.project).toBeUndefined();
      }
    }
    writeConfig({ apiUrl: "http://server", bankId: "next" });
    expect(resolveHostMemory("dsh", root).bankId).toBe("next");
  });

  it.each([
    "dsh",
    "opencode",
    "kilo",
    "opencode2",
    "cline-cli",
    "pi",
    "prime-agent",
    "claude-code",
    "codex",
  ])("%s disables memory when no Bank is configured, without requests", async (host) => {
    writeConfig({ bankId: undefined, apiUrl: "http://server" });
    const { resolveHostMemory } = await loadFactory();
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    try {
      const result = resolveHostMemory(host, root);
      expect(result.cfg.disabled).toBe(true);
      expect(result.bankId).toBe("");
      expect(fetch).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("enforces optInOnly for every host, not just the ones that remembered to pass a directory", async () => {
    // dsh called applyBankConfig WITHOUT the directory, so `optInOnly` was never enforced there:
    // an unapproved repo still got a bank and still had memories written for it.
    writeConfig({ optInOnly: true, optInPaths: ["/somewhere/else"] });
    const { resolveHostMemory } = await loadFactory();

    expect(resolveHostMemory("dsh", root).cfg.disabled).toBe(true);
  });

  it("does not derive a bank when memory is disabled — that path is a zero-overhead baseline", async () => {
    // Bank derivation shells out to git. `disabled` promises the same agent with NO memory work,
    // which is what makes it usable as an A/B baseline, so it must stop before that.
    writeConfig({ disabled: true });
    const { resolveHostMemory } = await loadFactory();

    const { cfg, bankId } = resolveHostMemory("dsh", root);
    expect(cfg.disabled).toBe(true);
    expect(bankId).toBe("");
  });

  it("re-resolves the token from the live config, so a rotation does not need a restart", async () => {
    writeConfig({ apiUrl: "http://server", apiToken: "old-key" });
    const { resolveHostMemory } = await loadFactory();
    const { client } = resolveHostMemory("dsh", root);
    expect(client.apiToken).toBe("old-key");

    // The operator rotates the credential while the host keeps running; the next 401 picks it up.
    writeConfig({ apiUrl: "http://server", apiToken: "new-key" });
    const calls: (string | null)[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        const auth = new Headers(init.headers).get("Authorization");
        calls.push(auth);
        return new Response(JSON.stringify(auth === "Bearer new-key" ? { ok: true } : {}), {
          status: auth === "Bearer new-key" ? 200 : 401,
          headers: { "Content-Type": "application/json" },
        });
      })
    );

    await client.req("GET", "http://server/thing");
    expect(calls).toEqual(["Bearer old-key", "Bearer new-key"]);
    vi.unstubAllGlobals();
  });

  it("ignores per-bank credentials and uses the default connection", async () => {
    // Banks customize memory behavior, never the shared endpoint or credential.
    const { resolveHostMemory: probe } = await loadFactory();
    writeConfig({ apiUrl: "http://server", apiToken: "global" });
    const bankId = probe("dsh", root).bankId;

    writeConfig({
      apiUrl: "http://server",
      apiToken: "global",
      banks: { [bankId]: { apiToken: "per-bank" } },
    });
    const { resolveHostMemory } = await loadFactory();
    expect(resolveHostMemory("dsh", root).client.apiToken).toBe("global");
  });

  it("keeps a token re-read from reaching the old server after the config moved the directory", async () => {
    writeConfig({ apiUrl: "http://server-a", apiToken: "key-a" });
    const { resolveHostMemory } = await loadFactory();
    const { client } = resolveHostMemory("dsh", root);

    // The directory now points at another server: its key belongs there, not on server-a.
    writeConfig({ apiUrl: "http://server-b", apiToken: "key-b" });
    const calls: (string | null)[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        calls.push(new Headers(init.headers).get("Authorization"));
        return new Response("{}", { status: 401, headers: { "Content-Type": "application/json" } });
      })
    );

    await client.req("GET", "http://server-a/thing").catch(() => {});
    expect(calls).toEqual(["Bearer key-a"]);
    vi.unstubAllGlobals();
  });
});

/**
 * The #3600 shape: a capability wired per-host is a capability the next host forgets. Three
 * settings had already gone missing that way (maxParallelRetains twice, optInOnly once, the live
 * credential everywhere), so the rule is structural — a long-lived host does not build its own
 * client, and a module that does has to say why.
 */
describe("long-lived hosts build their client through the shared factory", () => {
  const SRC = fileURLToPath(new URL("..", import.meta.url));

  /** Modules that construct a client directly, and why that is correct for them. */
  const DIRECT: Record<string, string> = {
    "core/host-client.ts": "the shared factory itself",
    "core/hook.ts": "one-shot hook process — re-reads config on every invocation",
    "core/retain-hook.ts": "one-shot hook process, same",
    "core/session-start.ts": "one-shot hook process, same",
    "status.ts": "one-shot CLI resolving config from --config/--harness, not from a workspace",
    "deepen.ts": "one-shot CLI, same",
  };

  function sourceFiles(dir: string, prefix = ""): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
      if (entry.isDirectory())
        return entry.name === "e2e" ? [] : sourceFiles(join(dir, entry.name), rel);
      return entry.name.endsWith(".ts") && !entry.name.includes(".test.") ? [rel] : [];
    });
  }

  it("has no module constructing a client outside the factory without a stated reason", () => {
    const unexplained = sourceFiles(SRC).filter(
      (rel) =>
        !(rel in DIRECT) && readFileSync(join(SRC, rel), "utf8").includes("new ContextBaseClient(")
    );
    expect(unexplained).toEqual([]);
  });

  it("keeps no entry for a module that stopped constructing one", () => {
    const stale = Object.keys(DIRECT).filter(
      (rel) => !readFileSync(join(SRC, rel), "utf8").includes("new ContextBaseClient(")
    );
    expect(stale).toEqual([]);
  });
});

describe("persistent host configuration failures share the disabled boundary", () => {
  it.each(["opencode", "kilo", "opencode2", "cline-cli", "dsh", "pi", "prime-agent"])(
    "%s does not derive a bank or send requests with invalid persisted settings",
    async (harness) => {
      writeConfig({ apiUrl: "file:///tmp/api", disabled: false });
      const { resolveHostMemory } = await loadFactory();
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      try {
        const resolved = resolveHostMemory(harness, root);
        expect(resolved.cfg.disabled).toBe(true);
        expect(resolved.bankId).toBe("");
        expect(fetch).not.toHaveBeenCalled();
      } finally {
        vi.unstubAllGlobals();
      }
    }
  );
});

describe("persistent adapters keep the shared configuration boundary", () => {
  const src = fileURLToPath(new URL("..", import.meta.url));
  // Plugin entries also serve Kilo/Prime Agent via the persistent harness registry.
  it.each([
    "harness/plugin-entry.ts",
    "harness/opencode2.ts",
    "harness/pi-extension.ts",
    "cline.ts",
    "dsh.ts",
    "mcp-server.ts",
  ])("%s uses the fail-open factory instead of the throwing raw loader", (file) => {
    const source = readFileSync(join(src, file), "utf8");
    expect(source).toContain("resolveHostMemory(");
    expect(source).not.toMatch(/\bloadConfig\s*\(/);
  });
});
