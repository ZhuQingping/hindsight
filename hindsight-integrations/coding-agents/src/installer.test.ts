import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
  existsSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";
import { INSTALLERS, MARKER, parseJsonc, run, type InstallCtx } from "./installer";
import { TRAECODE_WORKSPACE_ENABLED_KEY } from "./core/traecode-mcp";
import { SKILL_DIRS } from "./core/skill-dirs";
import { parse as parseToml } from "smol-toml";
import { HOOK_HARNESSES } from "./harness/hook-lifecycle";
import { applyBankConfig, loadConfig } from "./core/config";
import { configuredBankId } from "./core/bank";

/** The uninstall sweep and the hook seed both shell out to the system sqlite3 — absent on some
 *  runners, so the DB-backed tests gate on a probe instead of assuming. */
const hasSqlite3 = (() => {
  try {
    execFileSync("sqlite3", ["--version"], { stdio: ["ignore", "pipe", "pipe"] });
    return true;
  } catch {
    return false;
  }
})();

// Every test gets a FRESH temp dir as ctx.home (never the real $HOME) and a stubbed
// claudeMcp so the real `claude` CLI is never executed. run() is always called with
// explicit harness names so detect() (which probes PATH) never runs.

const homes: string[] = [];

// TraeCode resolves its user-level MCP file by Electron's OS conventions, which consult APPDATA
// (win32) and XDG_CONFIG_HOME (linux). Left set, the install writes OUTSIDE the temp ctx.home —
// the CI runner's XDG_CONFIG_HOME is exactly how the family sweep at "MCP registrations name the
// calling harness" lost the file and failed on linux while every traecode-specific test (which
// pinned the env locally) passed. Pin the whole file instead: no per-harness describe should have
// to remember this, the same lesson as SKILL_DIRS — the list everyone forgets lives once.
let savedEnv: Record<string, string | undefined>;
beforeAll(() => {
  savedEnv = {
    APPDATA: process.env.APPDATA,
    XDG_CONFIG_HOME: process.env.XDG_CONFIG_HOME,
    CLAUDE_CONFIG_DIR: process.env.CLAUDE_CONFIG_DIR,
  };
  delete process.env.CLAUDE_CONFIG_DIR;
  delete process.env.APPDATA;
  delete process.env.XDG_CONFIG_HOME;
});
afterAll(() => {
  for (const [k, v] of Object.entries(savedEnv)) {
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
});

function makeCtx(): InstallCtx & {
  claudeMcp: ReturnType<typeof vi.fn>;
  qwenMcp: ReturnType<typeof vi.fn>;
  clinePlugin: ReturnType<typeof vi.fn>;
  dcodePlugin: ReturnType<typeof vi.fn>;
  nodeSqlite: ReturnType<typeof vi.fn>;
} {
  const home = mkdtempSync(join(tmpdir(), "contextbase-installer-test-"));
  homes.push(home);
  const pkgRoot = join("/opt", MARKER); // contains the marker, like the real package path
  return {
    home,
    pkgRoot,
    dist: join(pkgRoot, "dist"),
    claudeMcp: vi.fn((args: string[]) => {
      // Model the real CLI's user-scope storage and refusal to overwrite names.
      const path = join(home, ".claude.json");
      const config = existsSync(path) ? readJson(path) : {};
      config.mcpServers ??= {};
      if (args[1] === "add") {
        if (config.mcpServers.contextbase) return false;
        const separator = args.indexOf("--");
        config.mcpServers.contextbase = {
          command: args[separator + 1],
          args: args.slice(separator + 2),
          env: { CONTEXTBASE_MCP_HARNESS: "claude-code" },
        };
      } else if (args[1] === "remove") {
        delete config.mcpServers.contextbase;
      }
      writeJsonAt(path, config);
      return true;
    }),
    // qwen-code registers through the `qwen` CLI, exactly as claude-code does through `claude`.
    // Stub it for the same reason: the suite must never execute a real host CLI.
    qwenMcp: vi.fn((args: string[]) => {
      const path = join(home, ".qwen", "settings.json");
      const config = existsSync(path) ? readJson(path) : {};
      config.mcpServers ??= {};
      if (args[1] === "add") {
        if (config.mcpServers.contextbase) return false;
        const name = args.indexOf("contextbase");
        config.mcpServers.contextbase = {
          command: args[name + 1],
          args: args.slice(name + 2),
          env: { CONTEXTBASE_MCP_HARNESS: "qwen-code" },
        };
      } else if (args[1] === "remove") {
        if (!args.includes("user"))
          throw new Error("MCP removal must explicitly select user scope");
        delete config.mcpServers.contextbase;
      }
      writeJsonAt(path, config);
      return true;
    }),
    clinePlugin: vi.fn(() => true),
    dcodePlugin: vi.fn(() => true),
    // Stubbed like the CLI seams above, so the suite never depends on the Node running it.
    nodeSqlite: vi.fn(() => true),
  };
}

function readJson(path: string): Record<string, any> {
  return JSON.parse(readFileSync(path, "utf8"));
}

function writeJsonAt(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2) + "\n");
}

// configureServer honors CONTEXTBASE_CONFIG — a developer shell exporting it must not leak the
// suite's --server writes into their real config file ("" is falsy → the per-test home is used).
//
// DSH_HOME leaks the same way, and more sharply: `dshHome()` is `process.env.DSH_HOME ||
// join(c.home, ".dsh")`, so the roster tests that install the dsh entrypoint into a temp `ctx.home`
// write the DEVELOPER'S own home patch whenever their shell exports it — and the row they leave
// behind points at a temp dir this suite then deletes, i.e. a dsh that no longer boots. Unset for
// the whole FILE, not just the dsh block: the loops that leak live outside that block, and the
// reader in core/history.ts honors DSH_HOME too.
beforeEach(() => {
  vi.stubEnv("CONTEXTBASE_CONFIG", "");
  vi.stubEnv("CONTEXTBASE_BANK_ID", "fixture-bank");
  vi.stubEnv("CONTEXTBASE_API_URL", "https://service.example");
  vi.stubEnv("CONTEXTBASE_API_TOKEN", "fixture-token");
  vi.stubEnv("CONTEXTBASE_API_KEY", "");
  vi.stubEnv("DSH_HOME", "");
  delete process.env.DSH_HOME;
});

afterEach(() => {
  vi.unstubAllEnvs();
  while (homes.length) rmSync(homes.pop()!, { recursive: true, force: true });
  vi.clearAllMocks();
});

// The env guards above are load-bearing rather than hygiene, and dropping one is silent on CI: the
// leak they prevent only shows up on a machine whose shell exports the variable. This is what
// notices.
describe("env isolation", () => {
  it("unsets DSH_HOME, so no test can write a real dsh home patch", () => {
    expect(process.env.DSH_HOME).toBeUndefined();
  });
});

describe("claude-code installer", () => {
  const settingsPath = (ctx: InstallCtx) => join(ctx.home, ".claude", "settings.json");

  it("install writes the 3 hook events with our dist commands and timeouts 30/30/60", () => {
    const ctx = makeCtx();
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    const settings = readJson(settingsPath(ctx));
    const hooks = settings.hooks;
    expect(Object.keys(hooks).sort()).toEqual(["SessionStart", "Stop", "UserPromptSubmit"]);
    const inner = (ev: string) => hooks[ev][0].hooks[0];
    expect(inner("SessionStart").command).toContain(join(ctx.dist, "claude-sessionstart-hook.js"));
    expect(inner("UserPromptSubmit").command).toContain(join(ctx.dist, "claude-hook.js"));
    expect(inner("Stop").command).toContain(join(ctx.dist, "claude-stop-hook.js"));
    expect(inner("SessionStart").timeout).toBe(30);
    expect(inner("UserPromptSubmit").timeout).toBe(30);
    expect(inner("Stop").timeout).toBe(60);
    for (const ev of ["SessionStart", "UserPromptSubmit", "Stop"]) {
      expect(inner(ev).type).toBe("command");
    }
  });

  it("preserves pre-existing foreign hook entries and appends ours", () => {
    const ctx = makeCtx();
    const foreign = { hooks: [{ type: "command", command: "echo other-tool", timeout: 5 }] };
    writeJsonAt(settingsPath(ctx), { hooks: { SessionStart: [foreign] } });
    run(["install", "claude-code"], ctx);
    const events = readJson(settingsPath(ctx)).hooks.SessionStart;
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual(foreign);
    expect(JSON.stringify(events[1])).toContain(MARKER);
  });

  it("re-install is idempotent — exactly ONE of our entries per event", () => {
    const ctx = makeCtx();
    run(["install", "claude-code"], ctx);
    run(["install", "claude-code"], ctx);
    const hooks = readJson(settingsPath(ctx)).hooks;
    for (const ev of ["SessionStart", "UserPromptSubmit", "Stop"]) {
      const ours = hooks[ev].filter((e: unknown) => JSON.stringify(e).includes(MARKER));
      expect(ours).toHaveLength(1);
      expect(hooks[ev]).toHaveLength(1);
    }
  });

  it("updates only its owned registration, preserving custom env, other servers and project settings", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".claude.json");
    const original = {
      mcpServers: {
        other: { type: "http", url: "https://example.com/mcp" },
        contextbase: {
          command: "node",
          args: ["/old/contextbase-coding-agents/dist/mcp-server.js"],
          env: { CUSTOM_ENV: "keep", CONTEXTBASE_MCP_HARNESS: "old" },
        },
      },
      projects: { project: { allowedTools: ["keep"] } },
    };
    writeJsonAt(path, original);
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    const updated = readJson(path);
    expect(updated.mcpServers.contextbase.args).toEqual([join(ctx.dist, "mcp-server.js")]);
    expect(updated.mcpServers.contextbase.env).toEqual({
      CUSTOM_ENV: "keep",
      CONTEXTBASE_MCP_HARNESS: "claude-code",
    });
    expect(updated.mcpServers.other).toEqual(original.mcpServers.other);
    expect(updated.projects).toEqual(original.projects);
    expect(readJson(`${path}.contextbase-backup`)).toEqual(original);
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    expect(readJson(path)).toEqual(updated);
  });

  it("does not replace malformed user settings", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(settingsPath(ctx)), { recursive: true });
    writeFileSync(settingsPath(ctx), "{ broken");
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(readFileSync(settingsPath(ctx), "utf8")).toBe("{ broken");
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
  });

  it("keeps the old registration if preparing its replacement fails", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".claude.json");
    writeJsonAt(path, {
      mcpServers: {
        contextbase: { command: "node", args: ["/old/coding-agents/dist/mcp-server.js"] },
      },
    });
    const original = readFileSync(path, "utf8");
    mkdirSync(`${path}.contextbase-${process.pid}.tmp`);
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(readFileSync(path, "utf8")).toBe(original);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
  });

  it("registers the MCP server via `claude mcp add` (user scope)", () => {
    const ctx = makeCtx();
    run(["install", "claude-code"], ctx);
    expect(ctx.claudeMcp).toHaveBeenCalledWith([
      "mcp",
      "add",
      "--scope",
      "user",
      // Every host launches the same mcp-server.js, so the registration has to name its harness —
      // otherwise the server falls back to claude-code and mis-attributes the other hosts' writes.
      "--env",
      "CONTEXTBASE_MCP_HARNESS=claude-code",
      "--transport",
      "stdio",
      "contextbase",
      "--",
      "node",
      join(ctx.dist, "mcp-server.js"),
    ]);
  });

  it("reports failure when Claude MCP registration is unusable and prints recovery instructions", () => {
    const ctx = makeCtx();
    ctx.claudeMcp.mockReturnValue(false);
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(logs.join("\n")).toContain("claude mcp add");
    // hooks were still written despite the MCP failure
    expect(existsSync(settingsPath(ctx))).toBe(true);
  });

  it("uninstall strips our entries, keeps foreign ones, and calls `claude mcp remove`", () => {
    const ctx = makeCtx();
    const foreign = { hooks: [{ type: "command", command: "echo other-tool", timeout: 5 }] };
    writeJsonAt(settingsPath(ctx), { hooks: { Stop: [foreign] } });
    run(["install", "claude-code"], ctx);
    run(["uninstall", "claude-code"], ctx);
    const settings = readJson(settingsPath(ctx));
    expect(settings.hooks.Stop).toEqual([foreign]);
    expect(settings.hooks.SessionStart).toBeUndefined();
    expect(settings.hooks.UserPromptSubmit).toBeUndefined();
    expect(JSON.stringify(settings)).not.toContain(MARKER);
    expect(ctx.claudeMcp).toHaveBeenCalledWith(["mcp", "remove", "--scope", "user", "contextbase"]);
  });

  it("uninstall removes the hooks object entirely when nothing else remains", () => {
    const ctx = makeCtx();
    run(["install", "claude-code"], ctx);
    run(["uninstall", "claude-code"], ctx);
    expect(readJson(settingsPath(ctx)).hooks).toBeUndefined();
  });
});

describe("kimi-code installer", () => {
  // Parsed as real TOML, so a malformed block fails here rather than in the user's CLI.
  const hookEntries = (toml: string) =>
    (parseToml(toml).hooks as Record<string, unknown>[] | undefined) ?? [];

  it("emits ONLY event/command/timeout on every entry", () => {
    // The load-bearing invariant. Kimi validates [[hooks]] against a strict 4-key schema, and an
    // unknown key does not drop that ENTRY — it drops EVERY hook in the file, at warning severity
    // only. A silent total loss of capture, so assert the key set rather than the values.
    const ctx = makeCtx();
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    const toml = readFileSync(join(ctx.home, ".kimi-code", "config.toml"), "utf8");
    const ours = toml.slice(toml.indexOf("# CONTEXTBASE_CODING_AGENTS_KIMI_START"));
    const entries = hookEntries(ours);
    expect(entries).toHaveLength(3);
    for (const e of entries) {
      expect(Object.keys(e).sort()).toEqual(["command", "event", "timeout"]);
    }
  });

  it("takes its events and timeouts from the lifecycle spec, in seconds", () => {
    // Seconds here, unlike qwen-code's identically named millisecond field. Reading them off the
    // spec means a spec change that the runtime honours cannot silently skip the installer.
    const ctx = makeCtx();
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    const toml = readFileSync(join(ctx.home, ".kimi-code", "config.toml"), "utf8");
    const ours = toml.slice(toml.indexOf("# CONTEXTBASE_CODING_AGENTS_KIMI_START"));
    const got = hookEntries(ours).map((e) => [e.event, e.timeout]);
    const want = Object.values(HOOK_HARNESSES["kimi-code"].install).map((h) => [
      h.event,
      h.timeout,
    ]);
    expect(got).toEqual(want);
    expect(got.map((g) => g[1])).toEqual([30, 30, 60]);
  });

  it("preserves a user's own hooks and does not duplicate ours on re-install", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".kimi-code", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, '[[hooks]]\nevent = "Stop"\ncommand = "their-tool"\ntimeout = 5\n');
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    const toml = readFileSync(path, "utf8");
    expect(toml).toContain("their-tool");
    expect(toml.match(/CONTEXTBASE_CODING_AGENTS_KIMI_START/g)).toHaveLength(1);
    expect(toml.match(/kimi-stop-hook\.js/g)).toHaveLength(1);
  });

  it("registers a stdio MCP server that needs no bearer-token env var", () => {
    // A hand-written http entry needs CONTEXTBASE_API_KEY exported into Kimi's environment, or it
    // 401s and the tools never appear. Ours is the packaged stdio server, which reads endpoint and
    // token from ~/.contextbase/coding-agent.json. Foreign entries are covered by ownership tests.
    const ctx = makeCtx();
    const mcpPath = join(ctx.home, ".kimi-code", "mcp.json");
    mkdirSync(dirname(mcpPath), { recursive: true });
    writeFileSync(
      mcpPath,
      JSON.stringify({
        mcpServers: {
          theirs: { url: "http://keep-me" },
        },
      })
    );
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    const mcp = JSON.parse(readFileSync(mcpPath, "utf8"));
    expect(mcp.mcpServers.theirs.url).toBe("http://keep-me");
    expect(mcp.mcpServers.contextbase.command).toBe("node");
    expect(mcp.mcpServers.contextbase.env.CONTEXTBASE_MCP_HARNESS).toBe("kimi-code");
    expect(mcp.mcpServers.contextbase.bearerTokenEnvVar).toBeUndefined();
    expect(mcp.mcpServers.contextbase.url).toBeUndefined();
  });

  it("honours KIMI_CODE_HOME, where the CLI and the transcript reader both look", () => {
    const ctx = makeCtx();
    const kimiHome = join(ctx.home, "custom-kimi");
    const original = process.env.KIMI_CODE_HOME;
    process.env.KIMI_CODE_HOME = kimiHome;
    try {
      expect(run(["install", "kimi-code"], ctx)).toBe(0);
      expect(hookEntries(readFileSync(join(kimiHome, "config.toml"), "utf8"))).toHaveLength(3);
      expect(existsSync(join(kimiHome, "mcp.json"))).toBe(true);
      expect(existsSync(join(ctx.home, ".kimi-code", "config.toml"))).toBe(false);
    } finally {
      if (original === undefined) delete process.env.KIMI_CODE_HOME;
      else process.env.KIMI_CODE_HOME = original;
    }
  });

  it("uninstall removes our block, our MCP entry, and nothing else", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".kimi-code", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, '[[hooks]]\nevent = "Stop"\ncommand = "their-tool"\ntimeout = 5\n');
    expect(run(["install", "kimi-code"], ctx)).toBe(0);
    expect(run(["uninstall", "kimi-code"], ctx)).toBe(0);
    const toml = readFileSync(path, "utf8");
    expect(toml).toContain("their-tool");
    expect(toml).not.toContain("CONTEXTBASE_CODING_AGENTS_KIMI");
    const mcp = JSON.parse(readFileSync(join(ctx.home, ".kimi-code", "mcp.json"), "utf8"));
    expect(mcp.mcpServers.contextbase).toBeUndefined();
  });
});

describe("qwen-code installer", () => {
  it("install writes the 3 hook events with our dist commands and timeouts 30000/30000/60000", () => {
    // NOT 30/30/60. Qwen reads this field as MILLISECONDS (hookRunner: DEFAULT_HOOK_TIMEOUT =
    // 60_000, passed straight to setTimeout), so the seconds values every other harness uses would
    // register 30ms/60ms hooks — dead before Node starts, and Qwen terminates the whole detached
    // process tree on timeout, so the turn is simply never retained.
    const ctx = makeCtx();
    expect(run(["install", "qwen-code"], ctx)).toBe(0);
    const hooks = JSON.parse(readFileSync(join(ctx.home, ".qwen", "settings.json"), "utf8")).hooks;
    const entry = (ev: string) => hooks[ev][0].hooks[0];
    expect(entry("SessionStart").timeout).toBe(30_000);
    expect(entry("UserPromptSubmit").timeout).toBe(30_000);
    expect(entry("Stop").timeout).toBe(60_000);
    for (const ev of ["SessionStart", "UserPromptSubmit", "Stop"]) {
      expect(entry(ev).command).toContain(ctx.dist);
      expect(entry(ev).type).toBe("command");
    }
  });

  it("registers the MCP server through the qwen CLI, user scope", () => {
    const ctx = makeCtx();
    expect(run(["install", "qwen-code"], ctx)).toBe(0);
    const argv = ctx.qwenMcp.mock.calls.map((c) => c[0].join(" "));
    expect(argv.some((a) => a.startsWith("mcp remove"))).toBe(false);
    expect(
      argv.some((a) => a.includes("mcp add") && a.includes("CONTEXTBASE_MCP_HARNESS=qwen-code"))
    ).toBe(true);
  });

  it("preserves pre-existing foreign hook entries and appends ours", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".qwen", "settings.json");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(
      path,
      JSON.stringify({
        hooks: { Stop: [{ hooks: [{ type: "command", command: "their-tool", timeout: 5000 }] }] },
      })
    );
    expect(run(["install", "qwen-code"], ctx)).toBe(0);
    const stop = JSON.parse(readFileSync(path, "utf8")).hooks.Stop;
    expect(JSON.stringify(stop)).toContain("their-tool");
    expect(JSON.stringify(stop)).toContain("qwen-stop-hook.js");
  });

  it("uninstall strips our entries and keeps foreign ones", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".qwen", "settings.json");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(
      path,
      JSON.stringify({
        hooks: { Stop: [{ hooks: [{ type: "command", command: "their-tool", timeout: 5000 }] }] },
      })
    );
    expect(run(["install", "qwen-code"], ctx)).toBe(0);
    expect(run(["uninstall", "qwen-code"], ctx)).toBe(0);
    const after = readFileSync(path, "utf8");
    expect(after).toContain("their-tool");
    expect(after).not.toContain("qwen-stop-hook.js");
  });
});

describe("factory-droid installer", () => {
  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".factory", "hooks.json");
  const mcpPath = (ctx: InstallCtx) => join(ctx.home, ".factory", "mcp.json");

  it("installs lifecycle and cancellation hooks at the top level", () => {
    // Droid's user-level hooks file is a standalone event map (no wrapping "hooks" key, unlike
    // Claude Code's settings.json) with Claude-shaped matcher groups. Writing a "hooks" wrapper
    // would register nothing.
    const ctx = makeCtx();
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    const hooks = readJson(hooksPath(ctx));
    expect(Object.keys(hooks).sort()).toEqual([
      "Notification",
      "SessionStart",
      "Stop",
      "UserPromptSubmit",
    ]);
    const entry = (ev: string) => hooks[ev][0].hooks[0];
    expect(entry("SessionStart").timeout).toBe(30);
    expect(entry("UserPromptSubmit").timeout).toBe(30);
    expect(entry("Stop").timeout).toBe(60);
    expect(entry("Notification").timeout).toBe(60);
    expect(entry("SessionStart").command).toContain("droid-sessionstart-hook.js");
    expect(entry("UserPromptSubmit").command).toContain("droid-hook.js");
    expect(entry("Stop").command).toContain("droid-stop-hook.js");
    expect(entry("Notification").command).toContain("droid-stop-hook.js");
  });

  it("copies settings.json fallback hooks before creating hooks.json", () => {
    const ctx = makeCtx();
    const settingsPath = join(ctx.home, ".factory", "settings.json");
    writeJsonAt(settingsPath, {
      hooks: {
        PreToolUse: [{ matcher: "Execute", hooks: [{ command: "their-hook", type: "command" }] }],
      },
      untouched: true,
    });

    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    expect(JSON.stringify(readJson(hooksPath(ctx)).PreToolUse)).toContain("their-hook");
    expect(readJson(settingsPath)).toMatchObject({ untouched: true });
  });

  it("registers the stdio MCP server in mcp.json with the factory-droid harness env", () => {
    const ctx = makeCtx();
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.contextbase).toMatchObject({
      command: "node",
      env: { CONTEXTBASE_MCP_HARNESS: "factory-droid" },
    });
    expect(mcp.mcpServers.contextbase.args[0]).toContain("mcp-server.js");
  });

  it("replaces an existing package-owned MCP entry and preserves other servers", () => {
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), {
      mcpServers: {
        playwright: { command: "npx", args: ["-y", "@playwright/mcp@latest"] },
        contextbase: {
          command: "node",
          args: ["/old/node_modules/contextbase-coding-agents/dist/mcp-server.js"],
        },
      },
    });
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.playwright).toBeDefined();
    expect(mcp.mcpServers.contextbase.env.CONTEXTBASE_MCP_HARNESS).toBe("factory-droid");
  });

  it("refuses to overwrite a user-managed MCP server with the same name", () => {
    const ctx = makeCtx();
    const existing = {
      mcpServers: {
        // An incidental marker string is not proof that this package created the registration.
        contextbase: { command: "coding-agents-proxy", args: ["serve"] },
      },
    };
    writeJsonAt(mcpPath(ctx), existing);

    expect(
      run(
        ["install", "factory-droid", "--server", "self-hosted", "--api-url", "http://box:8888"],
        ctx
      )
    ).toBe(1);
    expect(readJson(mcpPath(ctx))).toEqual(existing);
    expect(existsSync(hooksPath(ctx))).toBe(false);
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agent.json"))).toBe(false);
  });

  it("installs the companion skill into ~/.factory/skills", () => {
    const ctx = makeCtx();
    // makeCtx's pkgRoot is a synthetic /opt path the test cannot write; stage the packaged skill
    // in a real temp package root like the skills-sync family test does.
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-droidskill-"));
    homes.push(pkgRoot);
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(join(pkgRoot, "skill", "SKILL.md"), "packaged skill body");
    const droidCtx: InstallCtx = { ...ctx, pkgRoot, dist: join(pkgRoot, "dist") };
    expect(run(["install", "factory-droid"], droidCtx)).toBe(0);
    const skill = join(
      droidCtx.home,
      ...SKILL_DIRS["factory-droid"],
      "contextbase-coding-agent",
      "SKILL.md"
    );
    expect(readFileSync(skill, "utf8")).toBe("packaged skill body");
  });

  it("uninstall strips our hooks and MCP entry and keeps foreign ones", () => {
    const ctx = makeCtx();
    writeJsonAt(hooksPath(ctx), {
      Stop: [{ hooks: [{ type: "command", command: "their-tool", timeout: 5 }] }],
    });
    writeJsonAt(mcpPath(ctx), {
      mcpServers: {
        playwright: { command: "npx" },
        contextbase: {
          command: "node",
          args: ["/old/coding-agents/dist/mcp-server.js"],
        },
      },
    });
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    expect(run(["uninstall", "factory-droid"], ctx)).toBe(0);
    const hooks = readJson(hooksPath(ctx));
    expect(JSON.stringify(hooks)).toContain("their-tool");
    expect(JSON.stringify(hooks)).not.toContain("droid-stop-hook.js");
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.playwright).toBeDefined();
    expect(mcp.mcpServers.contextbase).toBeUndefined();
  });

  it("uninstall preserves a same-named MCP server that no longer belongs to the package", () => {
    const ctx = makeCtx();
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    const mcp = readJson(mcpPath(ctx));
    mcp.mcpServers.contextbase = { command: "coding-agents-proxy", args: ["serve"] };
    writeJsonAt(mcpPath(ctx), mcp);

    expect(run(["uninstall", "factory-droid"], ctx)).toBe(0);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toEqual({
      command: "coding-agents-proxy",
      args: ["serve"],
    });
  });

  it("uninstall removes empty config files it created", () => {
    const ctx = makeCtx();
    expect(run(["install", "factory-droid"], ctx)).toBe(0);
    expect(run(["uninstall", "factory-droid"], ctx)).toBe(0);
    expect(existsSync(hooksPath(ctx))).toBe(false);
    expect(existsSync(mcpPath(ctx))).toBe(false);
    expect(
      existsSync(join(SKILL_DIRS["factory-droid"].join("/"), "contextbase-coding-agent"))
    ).toBe(false);
  });
});

describe("zcode installer", () => {
  const configPath = (ctx: InstallCtx) => join(ctx.home, ".zcode", "cli", "config.json");

  it("registers the three hooks in ZCode's own CLI config, in its process shape", () => {
    // ZCode spawns hooks WITHOUT a shell, so a `node "…/zcode-hook.js"` command string would be
    // looked up verbatim as an executable and never run. The argv split is the whole point.
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const hooks = readJson(configPath(ctx)).hooks;
    expect(Object.keys(hooks.events).sort()).toEqual(["SessionStart", "Stop", "UserPromptSubmit"]);
    const entry = (ev: string) => hooks.events[ev][0].hooks[0];
    for (const ev of ["SessionStart", "Stop", "UserPromptSubmit"]) {
      expect(entry(ev).type).toBe("process");
      expect(entry(ev).command).toBe("node");
      expect(entry(ev).command).not.toContain(".js");
    }
    expect(entry("SessionStart").args[0]).toContain("zcode-sessionstart-hook.js");
    expect(entry("UserPromptSubmit").args[0]).toContain("zcode-hook.js");
    expect(entry("Stop").args[0]).toContain("zcode-stop-hook.js");
  });

  it("writes the budgets as timeoutMs, in milliseconds", () => {
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const entry = (ev: string) => readJson(configPath(ctx)).hooks.events[ev][0].hooks[0];
    expect(entry("SessionStart")).toMatchObject({ timeoutMs: 30_000 });
    expect(entry("UserPromptSubmit")).toMatchObject({ timeoutMs: 30_000 });
    expect(entry("Stop")).toMatchObject({ timeoutMs: 60_000 });
    // `timeout` seconds is another host's field: writing it here registers no budget at all.
    expect(entry("Stop").timeout).toBeUndefined();
  });

  it("turns ZCode's hook system on — it ships disabled, and off it fires nothing", () => {
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(readJson(configPath(ctx)).hooks).toMatchObject({
      enabled: true,
      maxOutputBytes: 32768,
    });
  });

  it("leaves a tuned maxOutputBytes alone", () => {
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), { hooks: { maxOutputBytes: 65536 } });
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(readJson(configPath(ctx)).hooks.maxOutputBytes).toBe(65536);
  });

  it("preserves the rest of the CLI config and any foreign hooks", () => {
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), {
      model: "glm-4.6",
      theme: "dark",
      hooks: {
        events: {
          UserPromptSubmit: [{ hooks: [{ type: "process", command: "their-hook" }] }],
          PreToolUse: [{ hooks: [{ type: "process", command: "their-other-hook" }] }],
        },
      },
    });
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const config = readJson(configPath(ctx));
    expect(config).toMatchObject({ model: "glm-4.6", theme: "dark" });
    expect(JSON.stringify(config.hooks.events)).toContain("their-hook");
    expect(config.hooks.events.PreToolUse).toBeDefined();
    expect(config.hooks.events.UserPromptSubmit).toHaveLength(2);
  });

  it("is idempotent — a second install replaces our entries rather than stacking them", () => {
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(readJson(configPath(ctx)).hooks.events.UserPromptSubmit).toHaveLength(1);
  });

  it("registers the stdio MCP server in the same config, tagged with the zcode harness", () => {
    // ZCode's server schema is strict — {type?, command, args?, cwd?, env?, enabled?, timeoutMs?} —
    // and infers type "stdio" from a command, which is why the shared entry shape drops straight in.
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const server = readJson(configPath(ctx)).mcp.servers.contextbase;
    expect(server).toMatchObject({ command: "node", env: { CONTEXTBASE_MCP_HARNESS: "zcode" } });
    expect(server.args[0]).toContain("mcp-server.js");
  });

  it("refuses to overwrite a user-managed MCP server already named contextbase", () => {
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), {
      mcp: { servers: { contextbase: { command: "their-own-proxy", args: ["serve"] } } },
    });
    expect(run(["install", "zcode"], ctx)).not.toBe(0);
    expect(readJson(configPath(ctx)).mcp.servers.contextbase.command).toBe("their-own-proxy");
  });

  /** makeCtx's pkgRoot is a synthetic /opt path the test cannot write; stage the packaged skill in
   *  a real temp package root, like the droid and skills-sync tests do. */
  const ctxWithPackagedSkill = (): InstallCtx => {
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-zcodeskill-"));
    homes.push(pkgRoot);
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(join(pkgRoot, "skill", "SKILL.md"), "packaged skill body");
    return { ...makeCtx(), pkgRoot, dist: join(pkgRoot, "dist") };
  };

  it("installs the companion skill in ZCode's own root, not the shared agentskills one", () => {
    const ctx = ctxWithPackagedSkill();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const skill = join(ctx.home, ...SKILL_DIRS.zcode, "contextbase-coding-agent", "SKILL.md");
    expect(readFileSync(skill, "utf8")).toBe("packaged skill body");
    // ~/.agents/skills is Codex's and dsh's copy; uninstalling zcode must never take it.
    expect(existsSync(join(ctx.home, ".agents", "skills", "contextbase-coding-agent"))).toBe(false);
  });

  it("uninstall takes the skill back out of ZCode's root", () => {
    const ctx = ctxWithPackagedSkill();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(run(["uninstall", "zcode"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ...SKILL_DIRS.zcode, "contextbase-coding-agent"))).toBe(false);
  });

  it("uninstall removes our MCP entry and keeps a foreign server", () => {
    // Plain makeCtx: ownership is decided by the dist path (isOurMcpEntry), which only the real
    // package layout satisfies — a temp pkgRoot would read as someone else's server.
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), { mcp: { servers: { playwright: { command: "npx" } } } });
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(run(["uninstall", "zcode"], ctx)).toBe(0);
    const config = readJson(configPath(ctx));
    expect(config.mcp.servers.playwright).toBeDefined();
    expect(config.mcp.servers.contextbase).toBeUndefined();
  });

  it("uninstall preserves a same-named MCP server that no longer belongs to the package", () => {
    const ctx = makeCtx();
    expect(run(["install", "zcode"], ctx)).toBe(0);
    const config = readJson(configPath(ctx));
    config.mcp.servers.contextbase = { command: "coding-agents-proxy", args: ["serve"] };
    writeJsonAt(configPath(ctx), config);
    expect(run(["uninstall", "zcode"], ctx)).toBe(0);
    expect(readJson(configPath(ctx)).mcp.servers.contextbase).toEqual({
      command: "coding-agents-proxy",
      args: ["serve"],
    });
  });

  it("uninstall removes the whole hooks block, so the host goes back to its off default", () => {
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), { model: "glm-4.6" });
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(run(["uninstall", "zcode"], ctx)).toBe(0);
    const config = readJson(configPath(ctx));
    expect(config.hooks).toBeUndefined();
    expect(config).toMatchObject({ model: "glm-4.6" });
  });

  it("uninstall keeps foreign hooks — and the enabled switch they now depend on", () => {
    const ctx = makeCtx();
    writeJsonAt(configPath(ctx), {
      hooks: { events: { PreToolUse: [{ hooks: [{ type: "process", command: "their-hook" }] }] } },
    });
    expect(run(["install", "zcode"], ctx)).toBe(0);
    expect(run(["uninstall", "zcode"], ctx)).toBe(0);
    const hooks = readJson(configPath(ctx)).hooks;
    expect(JSON.stringify(hooks)).toContain("their-hook");
    expect(JSON.stringify(hooks)).not.toContain("zcode-hook.js");
    expect(hooks.enabled).toBe(true);
  });
});

describe("traecode installer", () => {
  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".trae-cn", "hooks.json");
  // Mirrors traecodeUserDataDir's root choice. The env vars it consults are cleared for the whole
  // file (see the top-level beforeAll) so the resolution lands inside the temp home everywhere.
  const userDataRoot = (ctx: InstallCtx) => {
    const base =
      process.platform === "darwin"
        ? join(ctx.home, "Library", "Application Support")
        : process.platform === "win32"
          ? join(ctx.home, "AppData", "Roaming")
          : join(ctx.home, ".config");
    return join(base, "Trae CN");
  };
  const mcpPath = (ctx: InstallCtx) => join(userDataRoot(ctx), "User", "mcp.json");
  const wsStorageDir = (ctx: InstallCtx, name: string) =>
    join(userDataRoot(ctx), "User", "workspaceStorage", name);

  const settingsPath = (ctx: InstallCtx) => join(userDataRoot(ctx), "User", "settings.json");

  it("never flips the workspace-MCP gate on a non-interactive run without the flag", () => {
    const ctx = makeCtx();
    const logs: string[] = [];
    expect(run(["install", "traecode"], { ...ctx, log: (m) => logs.push(m) })).toBe(0);
    expect(existsSync(settingsPath(ctx))).toBe(false);
    expect(logs.join("\n")).toContain("--enable-workspace-mcp");
  });

  it("--enable-workspace-mcp turns the gate on and records it beside the runtime the hooks run from", () => {
    const ctx = makeCtx();
    const runtime = mkdtempSync(join(tmpdir(), "hs-traecode-runtime-"));
    homes.push(runtime);
    const dist = join(runtime, "dist");
    mkdirSync(dirname(settingsPath(ctx)), { recursive: true });
    writeFileSync(settingsPath(ctx), JSON.stringify({ "editor.fontSize": 13 }));

    expect(run(["install", "traecode", "--enable-workspace-mcp"], { ...ctx, dist })).toBe(0);

    expect(readJson(settingsPath(ctx))).toEqual({
      "editor.fontSize": 13,
      "trae.mcp.enableWorkspaceMcp": true,
    });
    expect(readJson(join(runtime, ".workspace-mcp.json"))).toMatchObject({
      workspaceMcpEnabled: true,
    });
  });

  it("registers the three hooks under the hooks key of ~/.trae-cn/hooks.json, in Claude's nested shape", () => {
    // TraeCode reads the event map from the top-level `hooks` KEY (Claude Code's settings.json
    // shape), not from the top level of the file the way Droid's hooks.json is read — and it
    // expects a `version` field it writes itself.
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    const doc = readJson(hooksPath(ctx));
    expect(doc.version).toBe(1);
    expect(Object.keys(doc.hooks).sort()).toEqual(["SessionStart", "Stop", "UserPromptSubmit"]);
    const entry = (ev: string) => doc.hooks[ev][0].hooks[0];
    for (const ev of ["SessionStart", "Stop", "UserPromptSubmit"]) {
      expect(entry(ev).type).toBe("command");
      // TraeCode spawns hooks through a shell, so a quoted command STRING runs — unlike ZCode.
      expect(entry(ev).command).toContain(".js");
    }
    expect(entry("SessionStart").command).toContain("traecode-sessionstart-hook.js");
    expect(entry("UserPromptSubmit").command).toContain("traecode-hook.js");
    expect(entry("Stop").command).toContain("traecode-stop-hook.js");
  });

  it("writes the budgets as timeout, in seconds (30/30/60)", () => {
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    const entry = (ev: string) => readJson(hooksPath(ctx)).hooks[ev][0].hooks[0];
    expect(entry("SessionStart").timeout).toBe(30);
    expect(entry("UserPromptSubmit").timeout).toBe(30);
    expect(entry("Stop").timeout).toBe(60);
  });

  it("leaves a version the host already wrote alone", () => {
    const ctx = makeCtx();
    writeJsonAt(hooksPath(ctx), { version: 2 });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(readJson(hooksPath(ctx)).version).toBe(2);
  });

  it("is idempotent — a second install replaces our entries rather than stacking them", () => {
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(run(["install", "traecode"], ctx)).toBe(0);
    for (const ev of ["SessionStart", "UserPromptSubmit", "Stop"]) {
      expect(readJson(hooksPath(ctx)).hooks[ev]).toHaveLength(1);
    }
  });

  it("preserves foreign hooks on install — and on uninstall", () => {
    const ctx = makeCtx();
    const foreign = { hooks: [{ type: "command", command: "their-hook", timeout: 5 }] };
    writeJsonAt(hooksPath(ctx), { version: 1, hooks: { PreToolUse: [foreign] } });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(readJson(hooksPath(ctx)).hooks.PreToolUse).toHaveLength(1);

    expect(run(["uninstall", "traecode"], ctx)).toBe(0);
    const doc = readJson(hooksPath(ctx));
    expect(JSON.stringify(doc.hooks)).toContain("their-hook");
    expect(JSON.stringify(doc.hooks)).not.toContain("traecode-hook.js");
    expect(doc.version).toBe(1);
  });

  it("uninstall removes the file when nothing but version is left", () => {
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(run(["uninstall", "traecode"], ctx)).toBe(0);
    expect(existsSync(hooksPath(ctx))).toBe(false);
    expect(existsSync(mcpPath(ctx))).toBe(false);
  });

  it("writes no user-level MCP registration — the per-repo hook-written file is the only one", () => {
    // Trae launches user-level servers with the Electron cwd (home), so a registration there is
    // wrong in every configuration (see installer.ts); the SessionStart hook writes each repo's
    // `.trae/mcp.json` instead.
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(existsSync(mcpPath(ctx))).toBe(false);
  });

  it("migrates a stale user-level MCP entry away on install", () => {
    const ctx = makeCtx();
    // An entry only the real package layout satisfies (isOurMcpEntry checks the path shape).
    const stale = {
      command: "node",
      args: [join(ctx.home, "vendor", "coding-agents", "dist", "mcp-server.js")],
      env: { CONTEXTBASE_MCP_HARNESS: "traecode" },
    };
    writeJsonAt(mcpPath(ctx), { mcpServers: { contextbase: stale } });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(existsSync(mcpPath(ctx))).toBe(false); // nothing else in the file: remove it whole
  });

  it("migrates only our entry, keeping foreign servers in the user-level file", () => {
    const ctx = makeCtx();
    const stale = {
      command: "node",
      args: [join(ctx.home, "vendor", "coding-agents", "dist", "mcp-server.js")],
      env: { CONTEXTBASE_MCP_HARNESS: "traecode" },
    };
    writeJsonAt(mcpPath(ctx), {
      mcpServers: { contextbase: stale, playwright: { command: "npx" } },
    });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.playwright).toEqual({ command: "npx" });
    expect(mcp.mcpServers.contextbase).toBeUndefined();
  });

  const sandboxPath = (ctx: InstallCtx) => join(ctx.home, ".trae-cn", "sandbox.json");

  it("seeds sandbox readWrite rules for ~/.contextbase and Trae's workspace storage — hooks run sandboxed", () => {
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(readJson(sandboxPath(ctx)).filesystem.readWrite).toEqual([
      join(ctx.home, ".contextbase"),
      join(userDataRoot(ctx), "User", "workspaceStorage"),
    ]);
  });

  it("merges the sandbox rules without disturbing foreign rules, and never stacks duplicates", () => {
    const ctx = makeCtx();
    writeJsonAt(sandboxPath(ctx), {
      filesystem: { readWrite: ["/opt/other-tool"], readOnly: ["/etc"] },
    });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(readJson(sandboxPath(ctx)).filesystem).toEqual({
      readWrite: [
        "/opt/other-tool",
        join(ctx.home, ".contextbase"),
        join(userDataRoot(ctx), "User", "workspaceStorage"),
      ],
      readOnly: ["/etc"],
    });
  });

  it("uninstall removes our sandbox rules and keeps foreign ones", () => {
    const ctx = makeCtx();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(run(["uninstall", "traecode"], ctx)).toBe(0);
    expect(readJson(sandboxPath(ctx)).filesystem.readWrite).toEqual([]);
  });

  const repoDir = (ctx: InstallCtx, name: string) => join(ctx.home, name);
  const repoMcp = (ctx: InstallCtx, name: string) => join(repoDir(ctx, name), ".trae", "mcp.json");
  const selectProject = (ctx: InstallCtx, repo: string) => {
    ctx.args = ["--project-path", repo];
  };

  /** makeCtx's dist is a synthetic /opt path the registration's `existsSync(dist/mcp-server.js)`
   *  guard rejects; the pre-seed needs a real dist file, laid out as `coding-agents/dist/` so the
   *  entry also satisfies isOurMcpEntry's ownership shape for the uninstall assertions. */
  const ctxWithRealDist = (): InstallCtx => {
    const root = mkdtempSync(join(tmpdir(), "hs-traecode-dist-"));
    homes.push(root);
    const dist = join(root, "coding-agents", "dist");
    mkdirSync(dist, { recursive: true });
    writeFileSync(join(dist, "mcp-server.js"), "// stub");
    return { ...makeCtx(), dist };
  };

  it("registers the explicitly selected Trae workspace independently of the configured Bank", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "repo-a");
    mkdirSync(repo, { recursive: true });
    expect(run(["install", "traecode", "--project-path", repo], ctx)).toBe(0);
    expect(readJson(repoMcp(ctx, "repo-a")).mcpServers.contextbase).toEqual({
      command: "node",
      args: [join(ctx.dist, "mcp-server.js")],
      env: { CONTEXTBASE_MCP_HARNESS: "traecode", CONTEXTBASE_MCP_PROJECT_CWD: repo },
    });
  });

  it("uninstalls every registered Trae project from an unrelated directory, preserving foreign servers", () => {
    const ctx = ctxWithRealDist();
    const a = repoDir(ctx, "repo-a"),
      b = repoDir(ctx, "repo-b");
    for (const repo of [a, b]) {
      mkdirSync(repo, { recursive: true });
      expect(run(["install", "traecode", "--project-path", repo], ctx)).toBe(0);
    }
    const bFile = repoMcp(ctx, "repo-b");
    const bDoc = readJson(bFile);
    bDoc.mcpServers.foreign = { command: "their-own-server" };
    writeJsonAt(bFile, bDoc);
    expect(run(["bank", "use", "other-bank"], ctx)).toBe(0);
    expect(run(["uninstall", "traecode", "--project-path", ctx.home], ctx)).toBe(0);
    expect(existsSync(repoMcp(ctx, "repo-a"))).toBe(false);
    expect(readJson(bFile).mcpServers).toEqual({ foreign: { command: "their-own-server" } });
  });

  it("preserves uninstall bookkeeping when retiring an old path-to-Bank mapping", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "old-project");
    writeJsonAt(join(repo, ".trae", "mcp.json"), {
      mcpServers: { contextbase: { command: "node", args: [join(ctx.dist, "mcp-server.js")] } },
    });
    const path = join(ctx.home, ".contextbase", "coding-agent.json");
    writeJsonAt(path, { mapPathToBank: { [repo]: "old" } });
    expect(run(["bank", "use", "configured"], ctx)).toBe(0);
    expect(readJson(path).mapPathToBank).toBeUndefined();
    expect(run(["uninstall", "traecode", "--project-path", ctx.home], ctx)).toBe(0);
    expect(existsSync(join(repo, ".trae", "mcp.json"))).toBe(false);
    expect(existsSync(join(ctx.home, ".contextbase", "traecode-projects"))).toBe(false);
  });

  it("discovers older project registrations through Trae workspace storage", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "older-project");
    mkdirSync(repo, { recursive: true });
    expect(run(["install", "traecode", "--project-path", repo], ctx)).toBe(0);
    rmSync(join(ctx.home, ".contextbase", "traecode-projects"), { recursive: true });
    const storage = wsStorageDir(ctx, "older-window");
    mkdirSync(storage, { recursive: true });
    writeFileSync(
      join(storage, "workspace.json"),
      JSON.stringify({ folder: pathToFileURL(repo).href })
    );
    expect(run(["uninstall", "traecode", "--project-path", ctx.home], ctx)).toBe(0);
    expect(existsSync(join(repo, ".trae", "mcp.json"))).toBe(false);
  });

  it("re-install leaves a current registration byte-identical and reports it", () => {
    const ctx = ctxWithRealDist();
    mkdirSync(repoDir(ctx, "repo-a"), { recursive: true });
    selectProject(ctx, repoDir(ctx, "repo-a"));
    expect(run(["install", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    const before = readFileSync(repoMcp(ctx, "repo-a"), "utf8");
    const logs: string[] = [];
    expect(
      run(["install", "traecode", ...(ctx.args ?? [])], { ...ctx, log: (m) => logs.push(m) })
    ).toBe(0);
    expect(readFileSync(repoMcp(ctx, "repo-a"), "utf8")).toBe(before);
    expect(logs.join("\n")).toMatch(/0 written, 1 already current/);
  });

  it("never touches a foreign contextbase entry in a repo's .trae/mcp.json", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "repo-a");
    mkdirSync(repo, { recursive: true });
    selectProject(ctx, repo);
    writeJsonAt(repoMcp(ctx, "repo-a"), {
      mcpServers: { contextbase: { command: "their-own-proxy", args: ["serve"] } },
    });
    const logs: string[] = [];
    expect(
      run(["install", "traecode", ...(ctx.args ?? [])], { ...ctx, log: (m) => logs.push(m) })
    ).toBe(0);
    expect(readJson(repoMcp(ctx, "repo-a")).mcpServers.contextbase).toEqual({
      command: "their-own-proxy",
      args: ["serve"],
    });
    expect(logs.join("\n")).toMatch(/1 skipped/);
  });

  it("uninstall removes the pre-seeded registration but keeps a repo's foreign servers", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "repo-a");
    mkdirSync(repo, { recursive: true });
    selectProject(ctx, repo);
    expect(run(["install", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    expect(existsSync(repoMcp(ctx, "repo-a"))).toBe(true);
    expect(run(["uninstall", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    expect(existsSync(repoMcp(ctx, "repo-a"))).toBe(false);

    // A repo that also carries a foreign server keeps the file, minus only our entry.
    const foreign = repoDir(ctx, "repo-b");
    mkdirSync(foreign, { recursive: true });
    selectProject(ctx, foreign);
    expect(run(["install", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    writeJsonAt(repoMcp(ctx, "repo-b"), {
      mcpServers: {
        playwright: { command: "npx" },
        contextbase: {
          command: "node",
          args: [join(ctx.dist, "mcp-server.js")],
          env: { CONTEXTBASE_MCP_HARNESS: "traecode", CONTEXTBASE_MCP_PROJECT_CWD: foreign },
        },
      },
    });
    expect(run(["uninstall", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    const kept = readJson(repoMcp(ctx, "repo-b")).mcpServers;
    expect(kept.playwright).toEqual({ command: "npx" });
    expect(kept.contextbase).toBeUndefined();
  });

  it("uninstall preserves unrelated top-level data when our entry was the only server", () => {
    const ctx = ctxWithRealDist();
    const repo = repoDir(ctx, "repo-a");
    mkdirSync(repo, { recursive: true });
    selectProject(ctx, repo);
    expect(run(["install", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    writeJsonAt(repoMcp(ctx, "repo-a"), {
      mcpServers: {
        contextbase: {
          command: "node",
          args: [join(ctx.dist, "mcp-server.js")],
          env: { CONTEXTBASE_MCP_HARNESS: "traecode", CONTEXTBASE_MCP_PROJECT_CWD: repo },
        },
      },
      inputs: [{ type: "promptString", id: "commitMessage" }],
    });
    expect(run(["uninstall", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
    const kept = readJson(repoMcp(ctx, "repo-a"));
    expect(kept.inputs).toEqual([{ type: "promptString", id: "commitMessage" }]);
    expect(kept.mcpServers).toBeUndefined(); // the emptied husk goes with our entry
  });

  it.runIf(hasSqlite3)(
    "install seeds the enable switch for opted-in repos that already have a Trae window",
    () => {
      const ctx = ctxWithRealDist();
      const repo = repoDir(ctx, "repo-a");
      mkdirSync(repo, { recursive: true });
      selectProject(ctx, repo);
      const ws = wsStorageDir(ctx, "abc123");
      mkdirSync(ws, { recursive: true });
      writeFileSync(
        join(ws, "workspace.json"),
        JSON.stringify({ folder: pathToFileURL(repo).href })
      );
      const db = join(ws, "state.vscdb");
      execFileSync("sqlite3", [
        db,
        "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);",
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('some.other.key', '1');",
      ]);
      expect(run(["install", "traecode", ...(ctx.args ?? [])], ctx)).toBe(0);
      const value = (key: string) =>
        execFileSync("sqlite3", [db, `SELECT value FROM ItemTable WHERE key='${key}';`], {
          encoding: "utf8",
        }).trim();
      expect(value(TRAECODE_WORKSPACE_ENABLED_KEY)).toBe("true");
      expect(value("some.other.key")).toBe("1");
    }
  );

  it("targets the international ~/.trae dot-dir when only it exists — the edition probe", () => {
    const ctx = ctxWithPackagedSkill();
    mkdirSync(join(ctx.home, ".trae"), { recursive: true });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ".trae", "hooks.json"))).toBe(true);
    expect(existsSync(join(ctx.home, ".trae", "skills", "contextbase-coding-agent"))).toBe(true);
    expect(existsSync(join(ctx.home, ".trae-cn"))).toBe(false);
  });

  it("keeps a foreign user-level contextbase entry and still installs — the installer writes no MCP file", () => {
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), {
      mcpServers: { contextbase: { command: "their-own-proxy", args: ["serve"] } },
    });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toEqual({
      command: "their-own-proxy",
      args: ["serve"],
    });
    expect(readJson(hooksPath(ctx)).hooks.SessionStart).toHaveLength(1);
  });

  it("uninstall removes our MCP entry and keeps a foreign server", () => {
    // Plain makeCtx: ownership is decided by the dist path (isOurMcpEntry), which only the real
    // package layout satisfies — a temp pkgRoot would read as someone else's server.
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), { mcpServers: { playwright: { command: "npx" } } });
    expect(run(["install", "traecode"], ctx)).toBe(0);
    expect(run(["uninstall", "traecode"], ctx)).toBe(0);
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.playwright).toBeDefined();
    expect(mcp.mcpServers.contextbase).toBeUndefined();
  });

  it.runIf(hasSqlite3)(
    "uninstall removes the workspace enable switches the hook seeded, and only those",
    () => {
      const ctx = makeCtx();
      const ws = wsStorageDir(ctx, "abc123");
      mkdirSync(ws, { recursive: true });
      writeFileSync(
        join(ws, "workspace.json"),
        JSON.stringify({ folder: pathToFileURL(join(ctx.home, "somewhere")).href })
      );
      const db = join(ws, "state.vscdb");
      execFileSync("sqlite3", [
        db,
        "CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB);",
        `INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('${TRAECODE_WORKSPACE_ENABLED_KEY}', 'true');`,
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES ('some.other.key', '1');",
      ]);
      expect(run(["install", "traecode"], ctx)).toBe(0);
      expect(run(["uninstall", "traecode"], ctx)).toBe(0);
      const query = (key: string) =>
        execFileSync("sqlite3", [db, `SELECT value FROM ItemTable WHERE key='${key}';`], {
          encoding: "utf8",
        }).trim();
      expect(query(TRAECODE_WORKSPACE_ENABLED_KEY)).toBe("");
      expect(query("some.other.key")).toBe("1");
    }
  );

  /** makeCtx's pkgRoot is a synthetic /opt path the test cannot write; stage the packaged skill in
   *  a real temp package root, like the zcode and droid tests do. */
  const ctxWithPackagedSkill = (): InstallCtx => {
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-traecodeskill-"));
    homes.push(pkgRoot);
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(join(pkgRoot, "skill", "SKILL.md"), "packaged skill body");
    return { ...makeCtx(), pkgRoot, dist: join(pkgRoot, "dist") };
  };

  it("installs the companion skill in TraeCode's own root", () => {
    const ctx = ctxWithPackagedSkill();
    expect(run(["install", "traecode"], ctx)).toBe(0);
    const skill = join(ctx.home, ...SKILL_DIRS.traecode, "contextbase-coding-agent", "SKILL.md");
    expect(readFileSync(skill, "utf8")).toBe("packaged skill body");
    expect(run(["uninstall", "traecode"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ...SKILL_DIRS.traecode, "contextbase-coding-agent"))).toBe(
      false
    );
  });
});

// WorkBuddy and CodeBuddy share one installer (same engine, different home folder and MCP file).
describe.each([
  { harness: "workbuddy", home: ".workbuddy", mcpFile: "mcp.json" },
  { harness: "codebuddy", home: ".codebuddy", mcpFile: ".mcp.json" },
])("$harness installer", ({ harness, home, mcpFile }) => {
  const settingsPath = (ctx: InstallCtx) => join(ctx.home, home, "settings.json");
  const mcpPath = (ctx: InstallCtx) => join(ctx.home, home, mcpFile);

  it("registers the three hooks in settings.json, in Claude's nested shape", () => {
    const ctx = makeCtx();
    expect(run(["install", harness], ctx)).toBe(0);
    const hooks = readJson(settingsPath(ctx)).hooks;
    expect(Object.keys(hooks).sort()).toEqual(["SessionStart", "Stop", "UserPromptSubmit"]);
    const entry = (ev: string) => hooks[ev][0].hooks[0];
    for (const ev of ["SessionStart", "Stop", "UserPromptSubmit"]) {
      expect(entry(ev).type).toBe("command");
      expect(entry(ev).command).toContain(ctx.dist);
    }
    expect(entry("SessionStart").command).toContain(`${harness}-sessionstart-hook.js`);
    expect(entry("UserPromptSubmit").command).toContain(`${harness}-hook.js`);
    expect(entry("Stop").command).toContain(`${harness}-stop-hook.js`);
    expect(entry("SessionStart").timeout).toBe(30);
    expect(entry("Stop").timeout).toBe(60);
  });

  it("registers the stdio MCP server in the host MCP file, tagged with its harness", () => {
    const ctx = makeCtx();
    expect(run(["install", harness], ctx)).toBe(0);
    const server = readJson(mcpPath(ctx)).mcpServers.contextbase;
    expect(server).toMatchObject({ command: "node", env: { CONTEXTBASE_MCP_HARNESS: harness } });
    expect(server.args[0]).toContain("mcp-server.js");
  });

  it("preserves the rest of the settings and any foreign hooks", () => {
    const ctx = makeCtx();
    writeJsonAt(settingsPath(ctx), {
      enabledPlugins: { "pptx@codebuddy-plugins-official": true },
      hooks: { PreToolUse: [{ hooks: [{ type: "command", command: "their-hook" }] }] },
    });
    expect(run(["install", harness], ctx)).toBe(0);
    const settings = readJson(settingsPath(ctx));
    expect(settings.enabledPlugins).toBeDefined();
    expect(JSON.stringify(settings.hooks)).toContain("their-hook");
    expect(settings.hooks.PreToolUse).toBeDefined();
    expect(settings.hooks.UserPromptSubmit).toHaveLength(1);
  });

  it("is idempotent — a second install replaces our entries rather than stacking them", () => {
    const ctx = makeCtx();
    expect(run(["install", harness], ctx)).toBe(0);
    expect(run(["install", harness], ctx)).toBe(0);
    expect(readJson(settingsPath(ctx)).hooks.UserPromptSubmit).toHaveLength(1);
  });

  it("preserves a foreign MCP server while adding ours", () => {
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), {
      mcpServers: { affine: { command: "npx", args: ["-y", "affine-mcp-server"] } },
    });
    expect(run(["install", harness], ctx)).toBe(0);
    const servers = readJson(mcpPath(ctx)).mcpServers;
    expect(servers.affine).toBeDefined();
    expect(servers.contextbase).toBeDefined();
  });

  it("uninstall removes our hooks and MCP entry, keeping a foreign server", () => {
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), { mcpServers: { affine: { command: "npx" } } });
    expect(run(["install", harness], ctx)).toBe(0);
    expect(run(["uninstall", harness], ctx)).toBe(0);
    expect(readJson(settingsPath(ctx)).hooks).toBeUndefined();
    const servers = readJson(mcpPath(ctx)).mcpServers;
    expect(servers.affine).toBeDefined();
    expect(servers.contextbase).toBeUndefined();
  });
});

describe("codebuddy installer MCP file chain", () => {
  const settingsPath = (ctx: InstallCtx) => join(ctx.home, ".codebuddy", "settings.json");
  const mcpPath = (ctx: InstallCtx) => join(ctx.home, ".codebuddy", ".mcp.json"); // recommended
  const deprecatedMcpPath = (ctx: InstallCtx) => join(ctx.home, ".codebuddy", "mcp.json");
  const legacyMcpPath = (ctx: InstallCtx) => join(ctx.home, ".codebuddy.json");

  it("creates only the recommended ~/.codebuddy/.mcp.json on a fresh home", () => {
    const ctx = makeCtx();
    expect(run(["install", "codebuddy"], ctx)).toBe(0);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toBeDefined();
    // Fresh home: the recommended file is created, no older link of the chain appears.
    expect(existsSync(deprecatedMcpPath(ctx))).toBe(false);
    expect(existsSync(legacyMcpPath(ctx))).toBe(false);
  });

  // CodeBuddy reads the FIRST existing file of its chain, so creating the recommended file when a
  // deprecated one already exists would shadow the user's servers. Mirror the host's write rule.
  it("merges into an existing deprecated ~/.codebuddy/mcp.json instead of shadowing it", () => {
    const ctx = makeCtx();
    writeJsonAt(deprecatedMcpPath(ctx), {
      mcpServers: { affine: { command: "npx", args: ["-y", "affine-mcp-server"] } },
    });
    expect(run(["install", "codebuddy"], ctx)).toBe(0);
    expect(existsSync(mcpPath(ctx))).toBe(false);
    const servers = readJson(deprecatedMcpPath(ctx)).mcpServers;
    expect(servers.affine).toBeDefined();
    expect(servers.contextbase).toBeDefined();
  });

  it("falls through to the legacy ~/.codebuddy.json when it is the only file present", () => {
    const ctx = makeCtx();
    writeJsonAt(legacyMcpPath(ctx), { mcpServers: { affine: { command: "npx" } }, projects: {} });
    expect(run(["install", "codebuddy"], ctx)).toBe(0);
    const cfg = readJson(legacyMcpPath(ctx));
    expect(cfg.mcpServers.contextbase).toBeDefined();
    expect(cfg.projects).toEqual({});
    expect(existsSync(mcpPath(ctx))).toBe(false);
  });

  it("uninstall clears our entry from the deprecated mcp.json, keeping a foreign server", () => {
    const ctx = makeCtx();
    writeJsonAt(deprecatedMcpPath(ctx), { mcpServers: { affine: { command: "npx" } } });
    expect(run(["install", "codebuddy"], ctx)).toBe(0);
    expect(run(["uninstall", "codebuddy"], ctx)).toBe(0);
    expect(readJson(settingsPath(ctx)).hooks).toBeUndefined();
    const servers = readJson(deprecatedMcpPath(ctx)).mcpServers;
    expect(servers.affine).toBeDefined();
    expect(servers.contextbase).toBeUndefined();
  });

  it("uninstall sweeps our entry from every chain link, keeping foreign servers", () => {
    const ctx = makeCtx();
    expect(run(["install", "codebuddy"], ctx)).toBe(0); // lands in the recommended file
    // A stale entry from an install under the old convention, dormant once the recommended
    // file appeared — CodeBuddy no longer reads it, but it must not survive an uninstall.
    writeJsonAt(deprecatedMcpPath(ctx), {
      mcpServers: {
        affine: { command: "npx" },
        contextbase: { command: "node", args: [join(ctx.dist, "mcp-server.js")] },
      },
    });
    expect(run(["uninstall", "codebuddy"], ctx)).toBe(0);
    expect(readJson(mcpPath(ctx)).mcpServers).toBeUndefined();
    const deprecated = readJson(deprecatedMcpPath(ctx)).mcpServers;
    expect(deprecated.affine).toBeDefined();
    expect(deprecated.contextbase).toBeUndefined();
  });
});

describe("codex installer", () => {
  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".codex", "hooks.json");
  const tomlPath = (ctx: InstallCtx) => join(ctx.home, ".codex", "config.toml");
  it("install writes the 3 hook events into hooks.json", () => {
    const ctx = makeCtx();
    expect(run(["install", "codex"], ctx)).toBe(0);
    const hooks = readJson(hooksPath(ctx)).hooks;
    expect(Object.keys(hooks).sort()).toEqual(["SessionStart", "Stop", "UserPromptSubmit"]);
    expect(hooks.SessionStart[0].hooks[0].command).toContain("codex-sessionstart-hook.js");
    expect(hooks.UserPromptSubmit[0].hooks[0].command).toContain("codex-hook.js");
    expect(hooks.Stop[0].hooks[0].command).toContain("codex-stop-hook.js");
  });

  it("creates config.toml with the features flag and mcp_servers section when missing", () => {
    const ctx = makeCtx();
    run(["install", "codex"], ctx);
    const toml = readFileSync(tomlPath(ctx), "utf8");
    expect(toml).toContain("[features]\nhooks = true");
    expect(toml).toContain("[mcp_servers.contextbase]");
    expect(toml).toContain(join(ctx.dist, "mcp-server.js"));
    expect(toml).toContain('env = { CONTEXTBASE_MCP_HARNESS = "codex" }');
  });

  it("does NOT duplicate an existing [features] section (only appends mcp) and backs up the toml", () => {
    const ctx = makeCtx();
    const original = "[features]\nsome_flag = true\n";
    mkdirSync(join(ctx.home, ".codex"), { recursive: true });
    writeFileSync(tomlPath(ctx), original);
    run(["install", "codex"], ctx);
    const toml = readFileSync(tomlPath(ctx), "utf8");
    expect(toml.match(/^\[features\]/gm)).toHaveLength(1);
    expect(toml).toContain("hooks = true");
    expect(toml).toContain("[mcp_servers.contextbase]");
    expect(readFileSync(`${tomlPath(ctx)}.contextbase-backup`, "utf8")).toBe(original);
  });

  it("appends nothing features-related when hooks is already present", () => {
    const ctx = makeCtx();
    mkdirSync(join(ctx.home, ".codex"), { recursive: true });
    writeFileSync(tomlPath(ctx), "[features]\nhooks = true\n");
    run(["install", "codex"], ctx);
    const toml = readFileSync(tomlPath(ctx), "utf8");
    expect(toml.match(/hooks/g)).toHaveLength(1);
    expect(toml.match(/^\[features\]/gm)).toHaveLength(1);
    expect(toml).toContain("[mcp_servers.contextbase]");
  });

  // Regression: Codex sessions ingested documents tagged `harness:claude-code`. Its registration
  // carried no CONTEXTBASE_MCP_HARNESS, and install skipped whenever a block already existed — so
  // the stale, harness-less block survived every re-install and the shared mcp-server.js kept
  // falling back to claude-code for the bank AND the retain stamp.
  it("re-install REPLACES a harness-less mcp block instead of leaving it stale", () => {
    const ctx = makeCtx();
    mkdirSync(join(ctx.home, ".codex"), { recursive: true });
    writeFileSync(
      tomlPath(ctx),
      '[features]\nhooks = true\n\n[mcp_servers.contextbase]\ncommand = "node"\n' +
        `args = ["${join(ctx.dist, "mcp-server.js")}"]\n\n[ui]\ntheme = "dark"\n`
    );
    run(["install", "codex"], ctx);
    const toml = readFileSync(tomlPath(ctx), "utf8");
    expect(toml.match(/^\[mcp_servers\.contextbase\]/gm)).toHaveLength(1);
    expect(toml).toContain('env = { CONTEXTBASE_MCP_HARNESS = "codex" }');
    expect(toml).toContain('[ui]\ntheme = "dark"'); // foreign sections survive the rewrite
  });

  it("uninstall removes the mcp_servers.contextbase block and leaves the rest of the toml", () => {
    const ctx = makeCtx();
    run(["install", "codex"], ctx);
    run(["uninstall", "codex"], ctx);
    const toml = readFileSync(tomlPath(ctx), "utf8");
    expect(toml).not.toContain("[mcp_servers.contextbase]");
    expect(toml).toContain("hooks = true"); // flag deliberately left in place
    const hooks = readJson(hooksPath(ctx)).hooks;
    expect(Object.keys(hooks)).toHaveLength(0);
  });
});

describe("cline-cli installer", () => {
  const hooksDir = (ctx: InstallCtx) => join(ctx.home, "Documents", "Cline", "Hooks");
  const mcpPath = (ctx: InstallCtx) =>
    join(ctx.home, ".cline", "data", "settings", "cline_mcp_settings.json");

  it("installs the native plugin, MCP, and the companion skill", () => {
    const ctx = makeCtx();
    expect(run(["install", "cline-cli"], ctx)).toBe(0);
    expect(ctx.clinePlugin).toHaveBeenCalledWith(["plugin", "install", "--force", ctx.pkgRoot]);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toEqual({
      command: "node",
      args: [join(ctx.dist, "mcp-server.js")],
      env: { CONTEXTBASE_MCP_HARNESS: "cline-cli" },
    });
  });

  it("removes legacy wrappers but preserves foreign hooks and uninstalls the native plugin", () => {
    const ctx = makeCtx();
    const foreign = join(hooksDir(ctx), "TaskStart");
    mkdirSync(dirname(foreign), { recursive: true });
    writeFileSync(foreign, "#!/usr/bin/env sh\necho foreign\n");
    const legacy = join(hooksDir(ctx), "UserPromptSubmit");
    writeFileSync(legacy, "#!/usr/bin/env sh\n# CONTEXTBASE_CODING_AGENTS_CLINE\n");
    run(["install", "cline-cli"], ctx);
    expect(readFileSync(foreign, "utf8")).toContain("foreign");
    expect(existsSync(legacy)).toBe(false);
    run(["uninstall", "cline-cli"], ctx);
    expect(existsSync(foreign)).toBe(true);
    expect(ctx.clinePlugin).toHaveBeenLastCalledWith([
      "plugin",
      "uninstall",
      "contextbase-coding-agents",
    ]);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toBeUndefined();
  });
});

describe("dsh installer", () => {
  const patchPath = (ctx: InstallCtx) => join(ctx.home, ".dsh", "cordis.patch.yml");

  it("registers the plugin as a file:// row in the home patch layer", () => {
    const ctx = makeCtx();
    expect(run(["install", "dsh"], ctx)).toBe(0);
    const patch = readFileSync(patchPath(ctx), "utf8");
    // A bare absolute path is not a module specifier: Cordis would fail to resolve it and skip
    // the plugin silently, which is exactly the Kilo trap this asserts against.
    expect(patch).toContain(`name: "${pathToFileURL(join(ctx.dist, "dsh.js")).href}"`);
    expect(patch).toContain("- id: contextbase");
  });

  it("replaces its own block on re-install and preserves the user's other patches", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(patchPath(ctx)), { recursive: true });
    writeFileSync(patchPath(ctx), "- id: llm\n  config:\n    provider: deepseek\n");
    run(["install", "dsh"], ctx);
    run(["install", "dsh"], ctx);
    const patch = readFileSync(patchPath(ctx), "utf8");
    expect(patch).toContain("provider: deepseek");
    expect(patch.match(/- id: contextbase/g)).toHaveLength(1);
  });

  it("uninstall leaves a valid empty patch list rather than an unparsable file", () => {
    const ctx = makeCtx();
    run(["install", "dsh"], ctx);
    run(["uninstall", "dsh"], ctx);
    // dsh REQUIRES this file to parse to a top-level array and fails BOOT otherwise, so an
    // emptied file must still be `[]`.
    expect(readFileSync(patchPath(ctx), "utf8").trim()).toBe("[]");
  });

  it("survives install -> uninstall -> install without writing two YAML documents", () => {
    const ctx = makeCtx();
    run(["install", "dsh"], ctx);
    run(["uninstall", "dsh"], ctx);
    run(["install", "dsh"], ctx);
    const patch = readFileSync(patchPath(ctx), "utf8");
    // The previous version carried the `[]` placeholder uninstall leaves behind into `others`,
    // which is truthy, so it emitted `[]` AND our block — two top-level documents. dsh parses this
    // file as a top-level array, refuses that, and then fails BOOT for EVERY profile.
    expect(patch).not.toContain("[]");
    // Nothing precedes our block: the file opens on our marker, not on a stray `[]` document.
    expect(patch.trim().startsWith("# CONTEXTBASE_CODING_AGENTS_DSH_START")).toBe(true);
    expect(patch.match(/- id: contextbase/g)).toHaveLength(1);
  });

  it("repairs a home layer an earlier version already corrupted with a leading `[]`", () => {
    const ctx = makeCtx();
    run(["install", "dsh"], ctx);
    // Byte-for-byte the state that install-after-uninstall used to leave on disk.
    writeFileSync(patchPath(ctx), `[]\n\n${readFileSync(patchPath(ctx), "utf8")}`);
    run(["install", "dsh"], ctx);
    const patch = readFileSync(patchPath(ctx), "utf8");
    // A re-install is the documented repair for a moved package, so it has to heal this too —
    // otherwise the machine stays unbootable with no way out but hand-editing the file.
    expect(patch).not.toContain("[]");
    expect(patch.match(/- id: contextbase/g)).toHaveLength(1);
  });

  it("uninstall keeps the user's own patches", () => {
    const ctx = makeCtx();
    run(["install", "dsh"], ctx);
    const kept = `- id: llm\n  config:\n    provider: deepseek\n`;
    writeFileSync(patchPath(ctx), kept + readFileSync(patchPath(ctx), "utf8"));
    run(["uninstall", "dsh"], ctx);
    const patch = readFileSync(patchPath(ctx), "utf8");
    expect(patch).toContain("provider: deepseek");
    expect(patch).not.toContain("contextbase");
  });
});

describe("antigravity-cli installer", () => {
  it("removes a namespace written under a PREVIOUS marker instead of leaving both live", () => {
    const ctx = makeCtx();
    const hooksPath = join(ctx.home, ".gemini", "config", "hooks.json");
    // Exactly what a marker rename produced: our old namespace, still pointing at a stale path.
    writeJsonAt(hooksPath, {
      "contextbase-coding-agents": {
        PreInvocation: [{ command: 'node "/old/path/coding-agents/dist/antigravity-hook.js"' }],
      },
      "someone-elses-bundle": { PreInvocation: [{ command: "echo other" }] },
    });
    run(["install", "antigravity-cli"], ctx);

    const hooks = readJson(hooksPath);
    // The stale namespace is gone — otherwise Antigravity fires every hook twice.
    expect(hooks["contextbase-coding-agents"]).toBeUndefined();
    expect(hooks[MARKER]).toBeDefined();
    expect(JSON.stringify(hooks)).not.toContain("/old/path/");
    // An unrelated bundle is untouched.
    expect(hooks["someone-elses-bundle"]).toBeDefined();
  });

  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".gemini", "config", "hooks.json");
  const mcpPath = (ctx: InstallCtx) => join(ctx.home, ".gemini", "config", "mcp_config.json");
  const settingsPath = (ctx: InstallCtx) =>
    join(ctx.home, ".gemini", "antigravity-cli", "settings.json");

  it("installs PreInvocation and Stop hooks plus mcpServers.contextbase", () => {
    const ctx = makeCtx();
    expect(run(["install", "antigravity-cli"], ctx)).toBe(0);
    const hooks = readJson(hooksPath(ctx));
    expect(hooks[MARKER].PreInvocation[0].command).toContain("antigravity-hook.js");
    expect(hooks[MARKER].PreInvocation[0].timeout).toBe(30);
    expect(hooks[MARKER].Stop[0].command).toContain("antigravity-stop-hook.js");
    expect(hooks[MARKER].Stop[0].timeout).toBe(30);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toEqual({
      command: "node",
      args: [join(ctx.dist, "mcp-server.js")],
      env: { CONTEXTBASE_MCP_HARNESS: "antigravity-cli" },
    });
    expect(readJson(settingsPath(ctx)).statusLine).toEqual({
      type: "command",
      command: `node "${join(ctx.dist, "antigravity-statusline.js")}"`,
    });
  });

  it("accepts agy as the supported CLI name", () => {
    const ctx = makeCtx();
    expect(run(["install", "agy"], ctx)).toBe(0);
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase.env.CONTEXTBASE_MCP_HARNESS).toBe(
      "antigravity-cli"
    );
  });

  it("preserves existing unrelated settings keys", () => {
    const ctx = makeCtx();
    writeJsonAt(hooksPath(ctx), { foreign: { enabled: false } });
    run(["install", "antigravity-cli"], ctx);
    expect(readJson(hooksPath(ctx)).foreign).toEqual({ enabled: false });
  });

  it("preserves an existing custom status line", () => {
    const ctx = makeCtx();
    writeJsonAt(settingsPath(ctx), { statusLine: { type: "command", command: "my-statusline" } });
    run(["install", "antigravity-cli"], ctx);
    expect(readJson(settingsPath(ctx)).statusLine.command).toBe("my-statusline");
  });

  it("uninstall removes only our hooks and mcp server", () => {
    const ctx = makeCtx();
    writeJsonAt(mcpPath(ctx), {
      mcpServers: { other: { command: "other-tool" } },
    });
    run(["install", "antigravity-cli"], ctx);
    run(["uninstall", "antigravity-cli"], ctx);
    expect(readJson(hooksPath(ctx))).toEqual({});
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.contextbase).toBeUndefined();
    expect(mcp.mcpServers.other).toEqual({ command: "other-tool" });
    expect(JSON.stringify(mcp)).not.toContain(MARKER);
    expect(readJson(settingsPath(ctx)).statusLine).toBeUndefined();
  });
});

/**
 * opencode v2 (`opencode2`) is registered in the SAME `~/.config/opencode/opencode.json[c]` as v1,
 * under the SAME `plugin` key. It has to be: the two CLIs read one file, v1 REJECTS the whole file
 * on v2's `plugins` key, and one entry serves both because they resolve a plugin directory
 * differently (v1 via package.json `main`, v2 via `<dir>/index.js`). See src/opencode2.ts.
 */
describe("opencode2 installer", () => {
  const cfgPath = (ctx: InstallCtx) => join(ctx.home, ".config", "opencode", "opencode.json");

  it("registers the package root in opencode's own config", () => {
    const ctx = makeCtx();
    expect(run(["install", "opencode2"], ctx)).toBe(0);
    expect(readJson(cfgPath(ctx)).plugin).toEqual([ctx.pkgRoot]);
  });

  it("wiring both opencode and opencode2 leaves ONE shared entry", () => {
    // The entry is identical, so the MARKER filter has to collapse them — two copies of the same
    // path would make opencode2 load the plugin twice.
    const ctx = makeCtx();
    run(["install", "opencode"], ctx);
    run(["install", "opencode2"], ctx);
    expect(readJson(cfgPath(ctx)).plugin).toEqual([ctx.pkgRoot]);
  });

  it("detects on the binary alone — ~/.config/opencode must not sway it", () => {
    // That directory is v1's too. Keying on it (as the opencode installer legitimately does) would
    // make `install` — which wires every DETECTED agent — claim opencode2 on every machine that
    // only has v1. Asserted as "the directory changes nothing" rather than a fixed value, because
    // whether the `opencode2` binary is on PATH is a property of the machine running the test.
    const opencode2 = INSTALLERS.find((i) => i.name === "opencode2")!;
    const without = makeCtx();
    const withDir = makeCtx();
    mkdirSync(join(withDir.home, ".config", "opencode"), { recursive: true });
    expect(opencode2.detect(withDir)).toBe(opencode2.detect(without));
    // …whereas v1 DOES treat the directory as a signal, which is exactly the difference.
    const opencode = INSTALLERS.find((i) => i.name === "opencode")!;
    expect(opencode.detect(withDir)).toBe(true);
  });
});

/** Kilo is an opencode fork: same `plugin` array, but a JSONC-capable config that may already
 *  exist under any of several names, and it must load dist/kilo.js (not the package root, which
 *  resolves to the opencode entry and would report the wrong harness). */
describe("kilo installer", () => {
  const kiloDir = (ctx: InstallCtx) => join(ctx.home, ".config", "kilo");
  const entryOf = (ctx: InstallCtx) => pathToFileURL(join(ctx.dist, "kilo.js")).href;

  it("registers dist/kilo.js — NOT the package root, which is the opencode entry", () => {
    const ctx = makeCtx();
    expect(run(["install", "kilo"], ctx)).toBe(0);
    const cfg = readJson(join(kiloDir(ctx), "kilo.json"));
    expect(cfg.plugin).toEqual([entryOf(ctx)]);
    expect(cfg.plugin).not.toContain(ctx.pkgRoot);
  });

  it("registers a file:// URL — a bare path is silently ignored by Kilo", () => {
    const ctx = makeCtx();
    run(["install", "kilo"], ctx);
    const [entry] = readJson(join(kiloDir(ctx), "kilo.json")).plugin;
    // Verified against Kilo 7.4.17: a bare absolute path is treated as an npm module specifier,
    // fails to resolve, and the plugin is skipped with NO error — the session just has no memory.
    expect(entry).toMatch(/^file:\/\//);
    expect(entry).not.toBe(join(ctx.dist, "kilo.js"));
  });

  it("is idempotent across reinstalls and preserves other plugin entries", () => {
    const ctx = makeCtx();
    writeJsonAt(join(kiloDir(ctx), "kilo.json"), { plugin: ["some-other-plugin"] });
    run(["install", "kilo"], ctx);
    run(["install", "kilo"], ctx);
    expect(readJson(join(kiloDir(ctx), "kilo.json")).plugin).toEqual([
      "some-other-plugin",
      entryOf(ctx),
    ]);
  });

  it("edits an existing kilo.jsonc instead of creating a competing kilo.json", () => {
    const ctx = makeCtx();
    const jsonc = join(kiloDir(ctx), "kilo.jsonc");
    mkdirSync(kiloDir(ctx), { recursive: true });
    writeFileSync(jsonc, '{\n  // my config\n  "$schema": "https://app.kilo.ai/config.json"\n}\n');
    run(["install", "kilo"], ctx);
    expect(existsSync(join(kiloDir(ctx), "kilo.json"))).toBe(false);
    const text = readFileSync(jsonc, "utf8");
    const cfg = parseJsonc(text)!;
    expect(cfg.plugin).toEqual([entryOf(ctx)]);
    expect(cfg.$schema).toBe("https://app.kilo.ai/config.json");
    // The comment used to be dropped here: the read was JSONC-aware but the write re-serialized
    // the parsed object, so a commented config came back stripped.
    expect(text).toContain("// my config");
  });

  it("refuses to clobber a config it cannot parse", () => {
    const ctx = makeCtx();
    const jsonc = join(kiloDir(ctx), "kilo.jsonc");
    mkdirSync(kiloDir(ctx), { recursive: true });
    const broken = '{ "provider": { unquoted } }';
    writeFileSync(jsonc, broken);
    run(["install", "kilo"], ctx);
    // A naive JSON.parse->{} fallback would have replaced the whole file with just our plugin key.
    expect(readFileSync(jsonc, "utf8")).toBe(broken);
  });

  it("uninstall removes our entry and deletes the plugin key when empty", () => {
    const ctx = makeCtx();
    run(["install", "kilo"], ctx);
    run(["uninstall", "kilo"], ctx);
    expect(readJson(join(kiloDir(ctx), "kilo.json")).plugin).toBeUndefined();
  });
});

describe("opencode installer", () => {
  const ocDir = (ctx: InstallCtx) => join(ctx.home, ".config", "opencode");
  const cfgPath = (ctx: InstallCtx) => join(ocDir(ctx), "opencode.json");

  // opencode loads `opencode.json` OR `opencode.jsonc` from ~/.config/opencode. Creating the
  // .json variant next to an existing .jsonc leaves the user with two configs — their settings in
  // one, our plugin entry in the other — so the install has to edit whichever already exists.
  it("edits an existing opencode.jsonc instead of creating a competing opencode.json", () => {
    const ctx = makeCtx();
    const jsonc = join(ocDir(ctx), "opencode.jsonc");
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(jsonc, '{\n  "$schema": "https://opencode.ai/config.json"\n}\n');
    run(["install", "opencode"], ctx);
    expect(existsSync(cfgPath(ctx))).toBe(false);
    expect(readJson(jsonc).plugin).toEqual([ctx.pkgRoot]);
  });

  it("uninstall edits the same opencode.jsonc the install wrote to", () => {
    const ctx = makeCtx();
    const jsonc = join(ocDir(ctx), "opencode.jsonc");
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(jsonc, "{}\n");
    run(["install", "opencode"], ctx);
    run(["uninstall", "opencode"], ctx);
    expect(readJson(jsonc).plugin).toBeUndefined();
    expect(existsSync(cfgPath(ctx))).toBe(false);
  });

  it("creates opencode.json when neither candidate exists", () => {
    const ctx = makeCtx();
    run(["install", "opencode"], ctx);
    expect(existsSync(cfgPath(ctx))).toBe(true);
    expect(existsSync(join(ocDir(ctx), "opencode.jsonc"))).toBe(false);
  });

  // The reported data loss: a commented config went through strict JSON.parse, which threw, and
  // readJson's {} fallback meant the whole file was rewritten as just our plugin key. Every
  // provider, agent override and MCP entry in it was gone.
  it("keeps the rest of a commented config instead of replacing it with just our key", () => {
    const ctx = makeCtx();
    const jsonc = join(ocDir(ctx), "opencode.jsonc");
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(
      jsonc,
      `{\n  // where memory lives\n  "share": "disabled",\n  "provider": {\n    "openai": { "name": "gw" },\n  },\n}\n`
    );
    run(["install", "opencode"], ctx);
    const cfg = parseJsonc(readFileSync(jsonc, "utf8"))!;
    expect(cfg.plugin).toEqual([ctx.pkgRoot]);
    expect(cfg.share).toBe("disabled"); // survived — this is what used to be wiped
    expect(cfg.provider).toEqual({ openai: { name: "gw" } });
  });

  // Reading the file correctly is only half of it: re-serializing the parsed object would drop
  // every comment the user wrote, so a config that survived would still come back damaged.
  it("leaves the user's comments and formatting in place", () => {
    const ctx = makeCtx();
    const jsonc = join(ocDir(ctx), "opencode.jsonc");
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(
      jsonc,
      `{\n  /** Providers **/\n  "provider": {\n    // via the gateway\n    "openai": { "name": "gw" },\n  },\n}\n`
    );
    run(["install", "opencode"], ctx);
    const text = readFileSync(jsonc, "utf8");
    expect(text).toContain("/** Providers **/");
    expect(text).toContain("// via the gateway");
    expect(text).toContain('"openai": { "name": "gw" },');
  });

  it("uninstall drops the plugin key without reformatting the file", () => {
    const ctx = makeCtx();
    const jsonc = join(ocDir(ctx), "opencode.jsonc");
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(jsonc, `{\n  /** mine **/\n  "share": "disabled",\n}\n`);
    run(["install", "opencode"], ctx);
    run(["uninstall", "opencode"], ctx);
    const text = readFileSync(jsonc, "utf8");
    expect(text).toContain("/** mine **/");
    expect(parseJsonc(text)).toEqual({ share: "disabled" });
  });

  // Trailing commas are as common as comments in a hand-written config, and JSON.parse rejects
  // both — so a .json file carrying them hit the very same wipe.
  it("parses a trailing-comma opencode.json rather than clobbering it", () => {
    const ctx = makeCtx();
    mkdirSync(ocDir(ctx), { recursive: true });
    writeFileSync(
      cfgPath(ctx),
      `{\n  "model": "openai/gpt-5",\n  "plugin": [\n    "other",\n  ],\n}\n`
    );
    run(["install", "opencode"], ctx);
    // Read back with the JSONC parser: the trailing commas are PRESERVED by the write, so the
    // result is still not strict JSON — which is the point.
    const cfg = parseJsonc(readFileSync(cfgPath(ctx), "utf8"))!;
    expect(cfg.model).toBe("openai/gpt-5");
    expect(cfg.plugin).toEqual(["other", ctx.pkgRoot]);
  });

  it("refuses to clobber a config it cannot parse", () => {
    const ctx = makeCtx();
    mkdirSync(ocDir(ctx), { recursive: true });
    const broken = '{ "provider": { unquoted } }';
    writeFileSync(cfgPath(ctx), broken);
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    run(["install", "opencode"], ctx);
    expect(readFileSync(cfgPath(ctx), "utf8")).toBe(broken);
    expect(logs.join("\n")).toContain("SKIPPED");
  });

  it("uninstall leaves an unparseable config untouched", () => {
    const ctx = makeCtx();
    mkdirSync(ocDir(ctx), { recursive: true });
    const broken = '{ "provider": { unquoted } }';
    writeFileSync(cfgPath(ctx), broken);
    run(["uninstall", "opencode"], ctx);
    expect(readFileSync(cfgPath(ctx), "utf8")).toBe(broken);
  });

  it("install adds ctx.pkgRoot to the plugin array exactly once, even across reinstalls", () => {
    const ctx = makeCtx();
    expect(run(["install", "opencode"], ctx)).toBe(0);
    run(["install", "opencode"], ctx);
    const cfg = readJson(cfgPath(ctx));
    expect(cfg.plugin).toEqual([ctx.pkgRoot]);
  });

  it("preserves other plugin entries", () => {
    const ctx = makeCtx();
    writeJsonAt(cfgPath(ctx), { plugin: ["some-other-plugin"] });
    run(["install", "opencode"], ctx);
    expect(readJson(cfgPath(ctx)).plugin).toEqual(["some-other-plugin", ctx.pkgRoot]);
  });

  it("uninstall removes our entry and deletes the plugin key when empty", () => {
    const ctx = makeCtx();
    run(["install", "opencode"], ctx);
    run(["uninstall", "opencode"], ctx);
    expect(readJson(cfgPath(ctx)).plugin).toBeUndefined();
  });

  it("uninstall keeps the plugin key when other entries remain", () => {
    const ctx = makeCtx();
    writeJsonAt(cfgPath(ctx), { plugin: ["some-other-plugin"] });
    run(["install", "opencode"], ctx);
    run(["uninstall", "opencode"], ctx);
    expect(readJson(cfgPath(ctx)).plugin).toEqual(["some-other-plugin"]);
  });
});

// pi and Prime Agent share one installer factory but must stay independently wired: each writes
// only its own settings.json, and each registers the bundle that reports its own harness.
describe.each([
  { harness: "pi", dir: [".pi", "agent"] },
  { harness: "prime-agent", dir: [".prime", "agent"] },
])("$harness installer", ({ harness, dir }) => {
  const cfgPath = (ctx: InstallCtx) => join(ctx.home, ...dir, "settings.json");
  const entry = (ctx: InstallCtx) => join(ctx.pkgRoot, "dist", `${harness}.js`);

  it("install adds the built extension to the extensions array exactly once, even across reinstalls", () => {
    const ctx = makeCtx();
    expect(run(["install", harness], ctx)).toBe(0);
    run(["install", harness], ctx);
    expect(readJson(cfgPath(ctx)).extensions).toEqual([entry(ctx)]);
  });

  it("preserves other extension entries", () => {
    const ctx = makeCtx();
    writeJsonAt(cfgPath(ctx), { extensions: ["/some/other/ext.js"] });
    run(["install", harness], ctx);
    expect(readJson(cfgPath(ctx)).extensions).toEqual(["/some/other/ext.js", entry(ctx)]);
  });

  it("uninstall removes our entry and deletes the extensions key when empty", () => {
    const ctx = makeCtx();
    run(["install", harness], ctx);
    run(["uninstall", harness], ctx);
    expect(readJson(cfgPath(ctx)).extensions).toBeUndefined();
  });

  it("uninstall keeps the extensions key when other entries remain", () => {
    const ctx = makeCtx();
    writeJsonAt(cfgPath(ctx), { extensions: ["/some/other/ext.js"] });
    run(["install", harness], ctx);
    run(["uninstall", harness], ctx);
    expect(readJson(cfgPath(ctx)).extensions).toEqual(["/some/other/ext.js"]);
  });
});

describe("pi-family companion skill", () => {
  // Both hosts discover their own skills root AND the shared `~/.agents/skills`. We write the OWN
  // directory: the shared root is where Codex and dsh install, and uninstallSkill removes by a
  // fixed name, so installing there would make `uninstall pi` delete their copy too.
  const HOSTS: [string, string[]][] = [
    ["pi", [".pi", "agent", "skills"]],
    ["prime-agent", [".prime", "agent", "skills"]],
  ];

  /** makeCtx's pkgRoot is a synthetic /opt path that does not exist, so the packaged skill can't be
   *  staged in it. Build a real temp package root instead, like the cross-host skill test below. */
  function ctxWithSkill(): InstallCtx {
    const home = mkdtempSync(join(tmpdir(), "hs-inst-pi-skill-"));
    homes.push(home);
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-"));
    homes.push(pkgRoot);
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(
      join(pkgRoot, "skill", "SKILL.md"),
      "---\nname: contextbase-coding-agent\n---\nbody"
    );
    return { home, pkgRoot, dist: join(pkgRoot, "dist"), claudeMcp: vi.fn(() => true) };
  }

  it.each(HOSTS)(
    "%s installs the packaged skill into its own skills directory and removes it on uninstall",
    (harness, dir) => {
      const ctx = ctxWithSkill();
      const base = join(ctx.home, ...dir);
      run(["install", harness], ctx);
      expect(existsSync(join(base, "contextbase-coding-agent", "SKILL.md"))).toBe(true);
      run(["uninstall", harness], ctx);
      expect(existsSync(join(base, "contextbase-coding-agent"))).toBe(false);
    }
  );

  it.each(HOSTS)(
    "uninstalling %s cannot strip Codex's copy from the shared ~/.agents/skills root",
    (harness) => {
      const ctx = ctxWithSkill();
      run(["install", "codex"], ctx);
      const shared = join(ctx.home, ".agents", "skills", "contextbase-coding-agent");
      expect(existsSync(shared)).toBe(true);

      run(["install", harness], ctx);
      run(["uninstall", harness], ctx);
      expect(existsSync(shared)).toBe(true);
    }
  );

  // The two hosts write DIFFERENT roots, so one's uninstall must not touch the other's skill —
  // the same independence the settings files already have.
  it("installing both gives each its own copy, and uninstalling one leaves the other", () => {
    const ctx = ctxWithSkill();
    run(["install", "pi"], ctx);
    run(["install", "prime-agent"], ctx);
    const primeSkill = join(ctx.home, ".prime", "agent", "skills", "contextbase-coding-agent");
    expect(existsSync(primeSkill)).toBe(true);

    run(["uninstall", "pi"], ctx);
    expect(existsSync(primeSkill)).toBe(true);
  });
});

/**
 * pi and Prime Agent both read `pkg.pi.extensions` when this package is installed as a distributed
 * pi package, so that key can only ever name one bundle — and the host it did not name loads the
 * other's, reports the wrong harness, and stamps it on every document it retains. It named Prime
 * Agent's until pi got an entry of its own, which is exactly how pi mis-attributed.
 *
 * `contextbase-coding-agents install pi|prime-agent` is the supported route for both, so the key is
 * gone. Re-adding it would be silent: nothing in this package reads it, the wrong attribution only
 * shows up later on retained documents, and it looks like the obvious way to support `pi install`.
 */
describe("the published manifest", () => {
  it("carries no `pi` key, which could only ever be right for one of the two hosts", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../package.json", import.meta.url), "utf8")
    ) as Record<string, unknown>;
    expect(manifest.pi).toBeUndefined();
    // The single-host manifest keys are fine and stay: exactly one harness reads each.
    expect(manifest.dsh).toBeDefined();
    expect(manifest.cline).toBeDefined();
  });
});

describe("pi and prime-agent do not disturb each other", () => {
  const piCfg = (ctx: InstallCtx) => join(ctx.home, ".pi", "agent", "settings.json");
  const primeCfg = (ctx: InstallCtx) => join(ctx.home, ".prime", "agent", "settings.json");

  it("wires each host to its own bundle and leaves the other config untouched", () => {
    const ctx = makeCtx();
    run(["install", "pi"], ctx);
    expect(existsSync(primeCfg(ctx))).toBe(false);

    run(["install", "prime-agent"], ctx);
    expect(readJson(piCfg(ctx)).extensions).toEqual([join(ctx.pkgRoot, "dist", "pi.js")]);
    expect(readJson(primeCfg(ctx)).extensions).toEqual([
      join(ctx.pkgRoot, "dist", "prime-agent.js"),
    ]);
  });

  it("uninstalling one leaves the other wired", () => {
    const ctx = makeCtx();
    run(["install", "pi"], ctx);
    run(["install", "prime-agent"], ctx);
    run(["uninstall", "prime-agent"], ctx);
    expect(readJson(piCfg(ctx)).extensions).toEqual([join(ctx.pkgRoot, "dist", "pi.js")]);
  });
});

describe("cursor-cli installer", () => {
  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".cursor", "hooks.json");
  const mcpPath = (ctx: InstallCtx) => join(ctx.home, ".cursor", "mcp.json");

  it("install writes sessionStart, beforeSubmitPrompt, and stop hooks plus the mcp.json server entry", () => {
    const ctx = makeCtx();
    expect(run(["install", "cursor-cli"], ctx)).toBe(0);
    const cfg = readJson(hooksPath(ctx));
    // Cursor refuses to list hooks.json in Customize > Hooks without a schema version.
    expect(cfg.version).toBe(1);
    const hooks = cfg.hooks;
    expect(hooks.sessionStart).toHaveLength(1);
    expect(hooks.sessionStart[0].command).toContain(join(ctx.dist, "cursor-sessionstart-hook.js"));
    expect(hooks.sessionStart[0].timeout).toBe(30);
    expect(hooks.beforeSubmitPrompt).toHaveLength(1);
    expect(hooks.beforeSubmitPrompt[0].command).toContain(join(ctx.dist, "cursor-hook.js"));
    expect(hooks.stop).toHaveLength(1);
    expect(hooks.stop[0].command).toContain(join(ctx.dist, "cursor-stop-hook.js"));
    expect(hooks.stop[0].timeout).toBe(30);
    const mcp = readJson(mcpPath(ctx));
    expect(mcp.mcpServers.contextbase).toEqual({
      command: "node",
      args: [join(ctx.dist, "mcp-server.js"), "${workspaceFolder}"],
      env: { CONTEXTBASE_MCP_HARNESS: "cursor-cli" },
    });
  });

  it("uninstall cleans both files", () => {
    const ctx = makeCtx();
    run(["install", "cursor-cli"], ctx);
    run(["uninstall", "cursor-cli"], ctx);
    expect(readJson(hooksPath(ctx)).hooks).toBeUndefined();
    expect(readJson(mcpPath(ctx)).mcpServers.contextbase).toBeUndefined();
  });

  it("fills in a missing schema version on reinstall without clobbering one already present", () => {
    const ctx = makeCtx();
    writeJsonAt(hooksPath(ctx), {
      hooks: { stop: [{ command: "echo other" }] },
    });
    expect(run(["install", "cursor-cli"], ctx)).toBe(0);
    expect(readJson(hooksPath(ctx)).version).toBe(1);
    expect(
      readJson(hooksPath(ctx)).hooks.stop.map((h: { command: string }) => h.command)
    ).toContain("echo other");

    writeJsonAt(hooksPath(ctx), {
      version: 2,
      hooks: { stop: [{ command: "echo other" }] },
    });
    expect(run(["install", "cursor-cli"], ctx)).toBe(0);
    expect(readJson(hooksPath(ctx)).version).toBe(2);
    expect(readJson(hooksPath(ctx)).hooks.stop).toHaveLength(2);
  });
});

describe("grok-build installer", () => {
  const configPath = (ctx: InstallCtx) => join(ctx.home, ".grok", "config.toml");
  const hooksPath = (ctx: InstallCtx) => join(ctx.home, ".grok", "hooks", "contextbase.json");

  it("re-install REPLACES the block so a moved package is repointed, not left stale", () => {
    const ctx = makeCtx();
    run(["install", "grok-build"], ctx);
    // Simulate the package moving (the exact case that broke: the install used to skip whenever a
    // block already existed, leaving dead paths behind and no way to repair them but by hand).
    const moved = { ...ctx, dist: join("/opt", MARKER, "moved-dist") };
    run(["install", "grok-build"], moved);

    const toml = readFileSync(configPath(ctx), "utf8");
    expect(toml).toContain(join("/opt", MARKER, "moved-dist"));
    expect(toml).not.toContain(ctx.dist); // the old path is gone, not merely appended past
    // Exactly one block — a replace, not an accumulation.
    expect(toml.match(/CONTEXTBASE_CODING_AGENTS_GROK_START/g)).toHaveLength(1);
    const hooks = readFileSync(hooksPath(ctx), "utf8");
    expect(hooks).toContain(join("/opt", MARKER, "moved-dist"));
    expect(hooks).not.toContain(ctx.dist);
    expect(readJson(hooksPath(ctx)).hooks.Stop).toHaveLength(1);
  });

  // Grok loads `[[hooks.*]]` tables from config.toml, but its config validator flags the `hooks`
  // key as unrecognized on every `grok inspect`. The hooks directory draws no warning.
  it("installs lifecycle hooks in ~/.grok/hooks and MCP in config.toml", () => {
    const ctx = makeCtx();
    expect(run(["install", "grok-build"], ctx)).toBe(0);
    expect(readJson(hooksPath(ctx)).hooks).toEqual({
      SessionStart: [
        {
          hooks: [
            {
              type: "command",
              command: `node "${join(ctx.dist, "grok-sessionstart-hook.js")}"`,
              timeout: 30,
            },
          ],
        },
      ],
      UserPromptSubmit: [
        {
          hooks: [
            { type: "command", command: `node "${join(ctx.dist, "grok-hook.js")}"`, timeout: 30 },
          ],
        },
      ],
      Stop: [
        {
          hooks: [
            {
              type: "command",
              command: `node "${join(ctx.dist, "grok-stop-hook.js")}"`,
              timeout: 60,
            },
          ],
        },
      ],
      // Grok hands the model context only from tool hooks (#5467): the prompt entry delivers it.
      PostToolUse: [
        {
          hooks: [
            { type: "command", command: `node "${join(ctx.dist, "grok-hook.js")}"`, timeout: 30 },
          ],
        },
      ],
    });
    const config = readFileSync(configPath(ctx), "utf8");
    expect(parseToml(config)).not.toHaveProperty("hooks");
    expect(config).toContain("[mcp_servers.contextbase]");
    expect(config).toContain(join(ctx.dist, "mcp-server.js"));
    expect(config).toContain('env = { CONTEXTBASE_MCP_HARNESS = "grok-build" }');
    expect(existsSync(join(ctx.home, ".claude"))).toBe(false);
  });

  // A config written before the markers existed (or hand-edited so they were lost) keeps an
  // unmarked `[mcp_servers.contextbase]` + hook entries. TOML forbids redefining a table, so
  // appending on top of them made the whole file unparsable and disabled every MCP server.
  const legacyToml = (dist: string) =>
    `[ui]\ntheme = "dark"\n\n` +
    `[[hooks.SessionStart]]\n  [[hooks.SessionStart.hooks]]\n  type = "command"\n  command = "node \\"${join(dist, "grok-sessionstart-hook.js")}\\""\n  timeout = 30\n\n` +
    `[[hooks.UserPromptSubmit]]\n  [[hooks.UserPromptSubmit.hooks]]\n  type = "command"\n  command = "node \\"${join(dist, "grok-hook.js")}\\""\n  timeout = 30\n\n` +
    `[mcp_servers.contextbase]\ncommand = "node"\nargs = ["${join(dist, "mcp-server.js")}"]\n`;

  it("replaces an unmarked legacy block instead of duplicating the TOML tables", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    writeFileSync(configPath(ctx), legacyToml(join("/opt", MARKER, "old-dist")));
    expect(run(["install", "grok-build"], ctx)).toBe(0);

    const toml = readFileSync(configPath(ctx), "utf8");
    // The whole point: the file still parses. A duplicate table makes Grok drop every MCP server.
    const parsed = parseToml(toml) as any;
    expect(Object.keys(parsed.mcp_servers)).toEqual(["contextbase"]);
    expect(toml.match(/\[mcp_servers\.contextbase\]/g)).toHaveLength(1);
    expect(parsed).not.toHaveProperty("hooks");
    expect(toml).not.toContain(join("/opt", MARKER, "old-dist"));
    expect(toml).toContain(join(ctx.dist, "mcp-server.js"));
    expect(toml).toContain('[ui]\ntheme = "dark"'); // foreign config preserved
  });

  it("leaves a foreign MCP server and unrelated hooks untouched", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    writeFileSync(
      configPath(ctx),
      `${legacyToml(join("/opt", MARKER, "old-dist"))}\n` +
        `[mcp_servers.other]\ncommand = "other-server"\n\n` +
        `[[hooks.Stop]]\n  [[hooks.Stop.hooks]]\n  type = "command"\n  command = "my-own-script"\n`
    );
    run(["install", "grok-build"], ctx);

    const toml = readFileSync(configPath(ctx), "utf8");
    const parsed = parseToml(toml) as any;
    expect(parsed.mcp_servers.other.command).toBe("other-server");
    expect(parsed.hooks.Stop[0].hooks[0].command).toBe("my-own-script");
    expect(toml).toContain('[mcp_servers.other]\ncommand = "other-server"');
    expect(toml).toContain('command = "my-own-script"');
    expect(toml.match(/\[mcp_servers\.contextbase\]/g)).toHaveLength(1);
  });

  // The reported end state (#4295): the duplicate already exists, so config.toml no longer parses
  // and `grok mcp list` shows nothing. Re-running install must repair it.
  it("repairs a config already broken by a duplicated block", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    const legacy = legacyToml(join("/opt", MARKER, "old-dist"));
    writeFileSync(configPath(ctx), legacy);
    run(["install", "grok-build"], ctx);
    // Re-create the pre-fix damage: the marked block appended on top of the untouched legacy one.
    const installed = readFileSync(configPath(ctx), "utf8");
    const marked = installed.slice(installed.indexOf("# CONTEXTBASE_CODING_AGENTS_GROK_START"));
    const broken = `${legacy}\n${marked}`;
    expect(() => parseToml(broken)).toThrow();
    writeFileSync(configPath(ctx), broken);

    expect(run(["install", "grok-build"], ctx)).toBe(0);
    const toml = readFileSync(configPath(ctx), "utf8");
    const parsed = parseToml(toml) as any;
    expect(Object.keys(parsed.mcp_servers)).toEqual(["contextbase"]);
    expect(parsed.mcp_servers.contextbase.args).toEqual([join(ctx.dist, "mcp-server.js")]);
    expect(toml.match(/CONTEXTBASE_CODING_AGENTS_GROK_START/g)).toHaveLength(1);
  });

  it("uninstall removes an unmarked legacy block too", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    writeFileSync(configPath(ctx), legacyToml(join("/opt", MARKER, "old-dist")));
    run(["uninstall", "grok-build"], ctx);

    const toml = readFileSync(configPath(ctx), "utf8");
    expect(parseToml(toml)).toEqual({ ui: { theme: "dark" } });
    expect(toml).not.toContain("[mcp_servers.contextbase]");
    expect(toml).not.toContain("grok-sessionstart-hook.js");
    expect(toml).toContain('[ui]\ntheme = "dark"');
  });

  it("moves the hooks a previous release kept in its marked block", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    const old = join("/opt", MARKER, "old-dist");
    writeFileSync(
      configPath(ctx),
      '[ui]\ntheme = "dark"\n\n# CONTEXTBASE_CODING_AGENTS_GROK_START\n' +
        `${legacyToml(old).slice('[ui]\ntheme = "dark"\n\n'.length)}` +
        `env = { CONTEXTBASE_MCP_HARNESS = "grok-build" }\n# CONTEXTBASE_CODING_AGENTS_GROK_END\n`
    );
    expect(run(["install", "grok-build"], ctx)).toBe(0);

    const parsed = parseToml(readFileSync(configPath(ctx), "utf8")) as any;
    expect(parsed).not.toHaveProperty("hooks");
    expect(parsed.ui).toEqual({ theme: "dark" });
    expect(parsed.mcp_servers.contextbase.args).toEqual([join(ctx.dist, "mcp-server.js")]);
    expect(Object.keys(readJson(hooksPath(ctx)).hooks)).toEqual([
      "SessionStart",
      "UserPromptSubmit",
      "Stop",
      "PostToolUse",
    ]);
  });

  it("uninstall keeps other hooks in the Grok hooks file", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(hooksPath(ctx)), { recursive: true });
    const mine = { hooks: [{ type: "command", command: "my-own-script" }] };
    writeFileSync(hooksPath(ctx), JSON.stringify({ hooks: { Stop: [mine] } }));
    run(["install", "grok-build"], ctx);
    expect(readJson(hooksPath(ctx)).hooks.Stop).toHaveLength(2);

    run(["uninstall", "grok-build"], ctx);
    expect(readJson(hooksPath(ctx))).toEqual({ hooks: { Stop: [mine] } });
  });

  // readJson returns {} for any top-level value that is not a plain object, so a hand-mangled
  // file is replaced rather than merged into and written back out as an array.
  it("replaces a Grok hooks file that is not a JSON object", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(hooksPath(ctx)), { recursive: true });
    writeFileSync(hooksPath(ctx), '["junk"]');
    expect(run(["install", "grok-build"], ctx)).toBe(0);
    const file = readJson(hooksPath(ctx));
    // Spreading the array in would have left a stray "0": "junk" beside the hooks.
    expect(Object.keys(file)).toEqual(["hooks"]);
    expect(Object.keys(file.hooks)).toEqual(
      expect.arrayContaining(["SessionStart", "UserPromptSubmit", "Stop"])
    );
  });

  it("replaces a Grok hooks file whose hooks are not an object", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(hooksPath(ctx)), { recursive: true });
    writeFileSync(hooksPath(ctx), JSON.stringify({ hooks: [] }));
    expect(run(["install", "grok-build"], ctx)).toBe(0);
    expect(Object.keys(readJson(hooksPath(ctx)).hooks)).toEqual(
      expect.arrayContaining(["SessionStart", "UserPromptSubmit", "Stop"])
    );
  });

  it("uninstall deletes a Grok hooks file left empty", () => {
    const ctx = makeCtx();
    run(["install", "grok-build"], ctx);
    run(["uninstall", "grok-build"], ctx);
    expect(existsSync(hooksPath(ctx))).toBe(false);
  });

  it("removes only its marked Grok TOML block", () => {
    const ctx = makeCtx();
    mkdirSync(dirname(configPath(ctx)), { recursive: true });
    writeFileSync(configPath(ctx), '[ui]\ntheme = "dark"\n');
    run(["install", "grok-build"], ctx);
    run(["uninstall", "grok-build"], ctx);
    const config = readFileSync(configPath(ctx), "utf8");
    expect(config).toContain('[ui]\ntheme = "dark"');
    expect(config).not.toContain("CONTEXTBASE_CODING_AGENTS_GROK");
    expect(config).not.toContain("[mcp_servers.contextbase]");
  });
});

describe("dcode installer", () => {
  it("uses Dcode's native marketplace and plugin commands", () => {
    const ctx = makeCtx();
    expect(run(["install", "dcode"], ctx)).toBe(0);
    const marketplacePath = join(
      ctx.home,
      ".contextbase",
      ".agents",
      "plugins",
      "marketplace.json"
    );
    expect(readJson(marketplacePath)).toMatchObject({
      name: "contextbase-coding-agents",
      plugins: [
        {
          name: "contextbase-coding-agents",
          source: { source: "local", path: "./coding-agents" },
        },
      ],
    });
    expect(ctx.dcodePlugin.mock.calls.map(([args]) => args)).toEqual([
      ["plugin", "marketplace", "add", join(ctx.home, ".contextbase")],
      ["plugin", "install", "contextbase-coding-agents@contextbase-coding-agents"],
    ]);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(existsSync(join(ctx.home, ".deepagents"))).toBe(false);
  });

  it("merges the marketplace without dropping foreign entries", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".contextbase", ".agents", "plugins", "marketplace.json");
    const foreign = { name: "other-plugin", source: { source: "github", repo: "acme/other" } };
    writeJsonAt(path, { name: "contextbase-coding-agents", plugins: [foreign] });
    expect(run(["install", "dcode"], ctx)).toBe(0);
    expect(readJson(path).plugins).toEqual([
      foreign,
      { name: "contextbase-coding-agents", source: { source: "local", path: "./coding-agents" } },
    ]);
  });

  it("isolates from a foreign marketplace name instead of rewriting it", () => {
    const ctx = makeCtx();
    const conventionalPath = join(
      ctx.home,
      ".contextbase",
      ".agents",
      "plugins",
      "marketplace.json"
    );
    const foreignMarketplace = {
      name: "team-marketplace",
      plugins: [{ name: "other-plugin", source: { source: "github", repo: "acme/other" } }],
    };
    writeJsonAt(conventionalPath, foreignMarketplace);

    expect(run(["install", "dcode"], ctx)).toBe(0);
    expect(readJson(conventionalPath)).toEqual(foreignMarketplace);
    const fallbackPath = join(
      ctx.home,
      ".contextbase",
      "contextbase-coding-agents-marketplace.json"
    );
    expect(readJson(fallbackPath)).toMatchObject({
      name: "contextbase-coding-agents",
      plugins: [
        {
          name: "contextbase-coding-agents",
          source: { source: "local", path: "./coding-agents" },
        },
      ],
    });
    expect(ctx.dcodePlugin).toHaveBeenCalledWith(["plugin", "marketplace", "add", fallbackPath]);
  });

  it("returns failure when native Dcode installation fails", () => {
    const ctx = makeCtx();
    ctx.dcodePlugin.mockReturnValue(false);
    const logs: string[] = [];
    ctx.log = (message) => logs.push(message);

    expect(run(["install", "dcode"], ctx)).toBe(1);
    expect(logs.join("\n")).toContain("could not install the native plugin");
  });

  it("continues installing other named targets when Dcode fails", () => {
    const ctx = makeCtx();
    ctx.dcodePlugin.mockReturnValue(false);

    expect(run(["install", "dcode", "claude-code"], ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(true);
  });

  it("continues a literal install all when Dcode fails", () => {
    const ctx = makeCtx();
    const binDir = mkdtempSync(join(tmpdir(), "contextbase-installer-bin-"));
    homes.push(binDir);
    writeFileSync(join(binDir, "dcode"), "", { mode: 0o755 });
    writeFileSync(join(binDir, "claude"), "", { mode: 0o755 });
    vi.stubEnv("PATH", `${binDir}:/usr/bin:/bin`);
    ctx.dcodePlugin.mockReturnValue(false);

    expect(run(["install", "all"], ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(true);
  });

  it("uninstalls the native plugin id and retires only OUR marketplace", () => {
    const ctx = makeCtx();
    expect(run(["uninstall", "dcode"], ctx)).toBe(0);
    // `plugin uninstall` alone leaves the plugin listed as `disabled` and the marketplace still
    // registered — our own leftovers in Dcode's state. Only the marketplace WE named is removed,
    // so a foreign one at the conventional path is untouched.
    expect(ctx.dcodePlugin.mock.calls.map(([args]) => args)).toEqual([
      ["plugin", "uninstall", "contextbase-coding-agents@contextbase-coding-agents"],
      ["plugin", "marketplace", "remove", "contextbase-coding-agents"],
    ]);
  });

  it("still reports a clean uninstall when only the marketplace removal fails", () => {
    const ctx = makeCtx();
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    ctx.dcodePlugin.mockImplementation((args: string[]) => args[1] !== "marketplace");
    // The plugin is gone, which is what "uninstalled" means; the stale marketplace is reported
    // with the command to clear it rather than failing the whole run.
    expect(run(["uninstall", "dcode"], ctx)).toBe(0);
    expect(logs.join("\n")).toContain("dcode plugin marketplace remove contextbase-coding-agents");
  });
});

describe("run() CLI behavior", () => {
  it("returns 1 for an unknown harness name and touches nothing", () => {
    const ctx = makeCtx();
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    expect(run(["install", "not-a-harness"], ctx)).toBe(1);
    expect(logs.join("\n")).toContain('unknown harness "not-a-harness"');
    expect(existsSync(join(ctx.home, ".claude"))).toBe(false);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
  });

  it("returns 0 with usage when no command is given", () => {
    const ctx = makeCtx();
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    expect(run([], ctx)).toBe(0);
    expect(logs.join("\n")).toContain("usage:");
  });

  it("returns 1 for an unknown command", () => {
    const ctx = makeCtx();
    expect(run(["frobnicate"], ctx)).toBe(1);
  });

  it("explicit harness names bypass detection — installs into an empty home", () => {
    const ctx = makeCtx();
    // nothing pre-exists in this fresh home, yet the named harness installs fine
    expect(run(["install", "antigravity-cli", "opencode"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ".gemini", "config", "hooks.json"))).toBe(true);
    expect(existsSync(join(ctx.home, ".config", "opencode", "opencode.json"))).toBe(true);
  });

  it("first write to a pre-existing json creates <file>.contextbase-backup with the original content", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".gemini", "config", "hooks.json");
    writeJsonAt(path, { auth: { selectedType: "oauth" } });
    const original = readFileSync(path, "utf8");
    run(["install", "antigravity-cli"], ctx);
    run(["install", "antigravity-cli"], ctx); // second write must NOT overwrite the backup
    expect(readFileSync(`${path}.contextbase-backup`, "utf8")).toBe(original);
  });

  it("MARKER identifies our entries under BOTH the npm and repo-checkout layouts", () => {
    // Dedupe-on-reinstall and uninstall both key off this substring appearing in the package path.
    // It silently stopped matching a checkout when the directory dropped its `contextbase-` prefix.
    expect("/usr/lib/node_modules/contextbase-coding-agents/dist").toContain(MARKER);
    expect("/repo/hindsight-integrations/coding-agents/dist").toContain(MARKER);
  });

  it("re-install from a repo-checkout path leaves exactly one hook entry per event", () => {
    const ctx = makeCtx();
    const repoStyle = {
      ...ctx,
      pkgRoot: "/repo/hindsight-integrations/coding-agents",
      dist: "/repo/hindsight-integrations/coding-agents/dist",
    };
    run(["install", "claude-code"], repoStyle);
    run(["install", "claude-code"], repoStyle);
    const hooks = readJson(join(ctx.home, ".claude", "settings.json")).hooks;
    for (const ev of ["SessionStart", "UserPromptSubmit", "Stop"]) {
      expect(hooks[ev]).toHaveLength(1);
    }
  });

  it("exposes the supported harnesses", () => {
    expect(INSTALLERS.map((i) => i.name)).toEqual([
      "codearts-agent",
      "codearts-cli",
      "opencode",
      "opencode2",
      "kilo",
      "pi",
      "prime-agent",
      "claude-code",
      "codex",
      "antigravity-cli",
      "devin-cli",
      "cursor-cli",
      "copilot-cli",
      "grok-build",
      "qwen-code",
      "kimi-code",
      "cline-cli",
      "dcode",
      "dsh",
      "factory-droid",
      "zcode",
      "traecode",
      "workbuddy",
      "codebuddy",
    ]);
  });
});

/**
 * Every host launches the SAME `dist/mcp-server.js`, so the command line cannot say who is calling
 * — only `CONTEXTBASE_MCP_HARNESS` can. A registration that omits it silently inherits the server's
 * claude-code fallback, which is how a Codex `contextbase_ingest_document` was stored tagged
 * `harness:claude-code` on a machine running both (#3603).
 *
 * Swept over INSTALLERS rather than a hand-written list of config paths: the harness that gets this
 * wrong is by construction the one nobody wrote a test for, so the guard has to find the
 * registration itself — any file the install wrote that names mcp-server.js, wherever it landed.
 */
describe("MCP registrations name the calling harness", () => {
  /** Every file under `dir`, recursively. */
  function filesUnder(dir: string): string[] {
    return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? filesUnder(join(dir, e.name)) : [join(dir, e.name)]
    );
  }

  // These hosts have no INSTALLER-written MCP registration. The in-process ones load our
  // plugin/extension in-process (src/kilo.ts, src/dsh.ts, src/pi.ts, src/prime-agent.ts,
  // dist/index.js for opencode, index.js -> dist/opencode2.js for opencode2), and that entry
  // hands its own harness name straight to RuntimeCore. TraeCode's registration is per-repo
  // `<repo>/.trae/mcp.json`, written by the SessionStart hook (covered in core/traecode-mcp.test.ts)
  // — the installer deliberately writes no user-level MCP file (see installer.ts's traecode docs).
  const NO_INSTALLER_MCP = new Set([
    "opencode",
    "opencode2",
    "kilo",
    "pi",
    "prime-agent",
    "dsh",
    "dcode",
    "traecode",
  ]);
  const MCP_HOSTS = INSTALLERS.map((i) => i.name).filter((n) => !NO_INSTALLER_MCP.has(n));

  it.each(MCP_HOSTS)("%s", (harness) => {
    const ctx = makeCtx();
    const args =
      harness === "codearts-agent" ? ["--mcp-config", join(ctx.home, "mcp_settings.json")] : [];
    expect(run(["install", harness, ...args], ctx)).toBe(0);
    const registrations = [
      ...filesUnder(ctx.home)
        .map((f) => readFileSync(f, "utf8"))
        // claude-code and qwen-code register through their host CLI instead of a file we write,
        // so their registration is the argv we handed the mock.
        .concat(ctx.claudeMcp.mock.calls.map((c) => c[0].join(" ")))
        .concat(ctx.qwenMcp.mock.calls.map((c) => c[0].join(" ")))
        .filter((text) => text.includes("mcp-server.js")),
    ];
    expect(registrations.length).toBeGreaterThan(0);
    for (const text of registrations) expect(text).toContain(`CONTEXTBASE_MCP_HARNESS`);
    for (const text of registrations) expect(text).toContain(harness);
  });
});

/**
 * A JSONC-configured host must survive the install with its comments intact.
 *
 * Swept over the family rather than asserted per harness: opencode and kilo each read with
 * `parseJsonc` and then wrote with `writeJson`, which re-serializes and strips exactly what the
 * JSONC-aware read preserved. The sibling that forgets is by construction the one nobody wrote a
 * test for, so this drives the real install and checks the file that came out.
 */
describe("JSONC hosts keep their comments through an install", () => {
  // Each entry is the config file the harness edits when it already exists, with the comment we
  // expect to still be there afterwards. Hosts absent from this list are strict-JSON by design
  // (claude-code's settings.json, cursor's hooks.json, …) or not JSON at all (grok/dsh: TOML/YAML).
  const JSONC_HOSTS: { harness: string; relPath: string[] }[] = [
    { harness: "opencode", relPath: [".config", "opencode", "opencode.jsonc"] },
    { harness: "kilo", relPath: [".config", "kilo", "kilo.jsonc"] },
  ];

  it.each(JSONC_HOSTS)("$harness", ({ harness, relPath }) => {
    const ctx = makeCtx();
    const path = join(ctx.home, ...relPath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, `{\n  // keep me\n  "share": "disabled",\n}\n`);

    expect(run(["install", harness], ctx)).toBe(0);
    const afterInstall = readFileSync(path, "utf8");
    expect(afterInstall).toContain("// keep me");
    expect(parseJsonc(afterInstall)!.share).toBe("disabled");
    expect(parseJsonc(afterInstall)!.plugin).toHaveLength(1);

    expect(run(["uninstall", harness], ctx)).toBe(0);
    const afterUninstall = readFileSync(path, "utf8");
    expect(afterUninstall).toContain("// keep me");
    expect(parseJsonc(afterUninstall)).toEqual({ share: "disabled" });
  });
});

/**
 * `all` is an explicit target rather than the default for a bare command: wiring every detected
 * agent rewrites a lot of a machine's config and should not happen by accident.
 */
describe("all vs named harnesses", () => {
  it("`install all` wires every DETECTED agent", () => {
    const ctx = makeCtx();
    mkdirSync(join(ctx.home, ".claude"), { recursive: true });
    mkdirSync(join(ctx.home, ".codex"), { recursive: true });
    expect(run(["install", "all"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(true);
    expect(existsSync(join(ctx.home, ".codex", "hooks.json"))).toBe(true);
  });

  it("a bare `install` changes NOTHING and explains the choice", () => {
    const ctx = makeCtx();
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    mkdirSync(join(ctx.home, ".claude"), { recursive: true });
    expect(run(["install"], ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(false);
    expect(logs.join("\n")).toContain("all");
  });

  it("a named harness wires only that one", () => {
    const ctx = makeCtx();
    mkdirSync(join(ctx.home, ".claude"), { recursive: true });
    mkdirSync(join(ctx.home, ".codex"), { recursive: true });
    run(["install", "claude-code"], ctx);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(true);
    expect(existsSync(join(ctx.home, ".codex", "hooks.json"))).toBe(false);
  });

  it("`uninstall all` is accepted too, so the pair stays symmetric", () => {
    const ctx = makeCtx();
    mkdirSync(join(ctx.home, ".claude"), { recursive: true });
    run(["install", "all"], ctx);
    expect(run(["uninstall", "all"], ctx)).toBe(0);
    expect(readJson(join(ctx.home, ".claude", "settings.json")).hooks).toBeUndefined();
  });
});

/**
 * Running from an npx cache used to be refused: the wiring is absolute paths into this package, and
 * a cache eviction would break every hook silently. The runtime is now copied somewhere stable
 * first, so `npx` works and nobody needs a global install of a tool that only sets other tools up.
 */
describe("runtime staging", () => {
  /** A package layout convincing enough to be staged: staging keys off a built dist. */
  function fakePackage(root: string): { pkgRoot: string; dist: string } {
    const dist = join(root, "dist");
    mkdirSync(dist, { recursive: true });
    writeFileSync(join(dist, "installer.js"), "// built");
    writeFileSync(join(dist, "claude-hook.js"), "// built");
    writeFileSync(join(root, "package.json"), JSON.stringify({ name: "x", main: "dist/index.js" }));
    mkdirSync(join(root, "skill"), { recursive: true });
    writeFileSync(join(root, "skill", "SKILL.md"), "# skill");
    return { pkgRoot: root, dist };
  }

  it("installs from an npx cache, wiring the stable copy instead of the cache", () => {
    const ctx = makeCtx();
    const cache = mkdtempSync(join(tmpdir(), "npx-cache-"));
    homes.push(cache);
    Object.assign(ctx, fakePackage(join(cache, "_npx", "abc123", "node_modules", "coding-agents")));

    expect(run(["install", "claude-code"], ctx)).toBe(0);
    const staged = join(ctx.home, ".contextbase", "coding-agents");
    const command = readJson(join(ctx.home, ".claude", "settings.json")).hooks.SessionStart[0]
      .hooks[0].command as string;
    expect(command).toContain(join(staged, "dist"));
    // The whole point: nothing in a host config may reference the evictable cache.
    expect(command).not.toContain("_npx");
    expect(existsSync(join(staged, "dist", "claude-hook.js"))).toBe(true);
  });

  // MARKER matching is what makes re-install replace and uninstall remove, and it looks for this
  // substring in the command path — so the staged location must keep it.
  it("stages somewhere the marker still matches", () => {
    const ctx = makeCtx();
    const src = mkdtempSync(join(tmpdir(), "pkg-"));
    homes.push(src);
    Object.assign(ctx, fakePackage(src));

    run(["install", "claude-code"], ctx);
    expect(join(ctx.home, ".contextbase", "coding-agents")).toContain(MARKER);
    run(["uninstall", "claude-code"], ctx);
    expect(readJson(join(ctx.home, ".claude", "settings.json")).hooks).toBeUndefined();
  });

  it("copies the plugin entry point too, since opencode loads the directory", () => {
    const ctx = makeCtx();
    const src = mkdtempSync(join(tmpdir(), "pkg-"));
    homes.push(src);
    Object.assign(ctx, fakePackage(src));

    run(["install", "opencode"], ctx);
    const staged = join(ctx.home, ".contextbase", "coding-agents");
    expect(existsSync(join(staged, "package.json"))).toBe(true);
    expect(existsSync(join(staged, "skill", "SKILL.md"))).toBe(true);
    const cfg = readJson(join(ctx.home, ".config", "opencode", "opencode.json"));
    expect(cfg.plugin).toContain(staged);
  });

  it("upgrading replaces the staged runtime, stale files and all", () => {
    const ctx = makeCtx();
    const v1 = mkdtempSync(join(tmpdir(), "v1-"));
    const v2 = mkdtempSync(join(tmpdir(), "v2-"));
    homes.push(v1, v2);
    fakePackage(v1);
    writeFileSync(join(v1, "dist", "old-only.js"), "// dropped in the next version");
    fakePackage(v2);
    writeFileSync(join(v2, "dist", "new-only.js"), "// added in the next version");

    Object.assign(ctx, { pkgRoot: v1, dist: join(v1, "dist") });
    run(["install", "claude-code"], ctx);
    Object.assign(ctx, { pkgRoot: v2, dist: join(v2, "dist") });
    run(["install", "claude-code"], ctx);

    const staged = join(ctx.home, ".contextbase", "coding-agents", "dist");
    expect(existsSync(join(staged, "new-only.js"))).toBe(true);
    // Merging instead of replacing would leave an entry point a host config could still name.
    expect(existsSync(join(staged, "old-only.js"))).toBe(false);
    const events = readJson(join(ctx.home, ".claude", "settings.json")).hooks.SessionStart;
    expect(events).toHaveLength(1);
  });

  // Re-running the STAGED installer must not delete the dist it is executing from.
  it("is a no-op when run from the staged copy itself", () => {
    const ctx = makeCtx();
    const src = mkdtempSync(join(tmpdir(), "pkg-"));
    homes.push(src);
    fakePackage(src);
    Object.assign(ctx, { pkgRoot: src, dist: join(src, "dist") });
    run(["install", "claude-code"], ctx);

    const staged = join(ctx.home, ".contextbase", "coding-agents");
    Object.assign(ctx, { pkgRoot: staged, dist: join(staged, "dist") });
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    expect(existsSync(join(staged, "dist", "installer.js"))).toBe(true);
  });

  // `update` is what core/auto-update.ts spawns unattended, so its blast radius IS the contract:
  // it refreshes the staged runtime and rewrites nothing a host reads.
  it("`update` re-stages the runtime without touching any host config", () => {
    const ctx = makeCtx();
    const v1 = mkdtempSync(join(tmpdir(), "v1-"));
    const v2 = mkdtempSync(join(tmpdir(), "v2-"));
    homes.push(v1, v2);
    fakePackage(v1);
    fakePackage(v2);
    writeFileSync(join(v2, "dist", "new-only.js"), "// added in the next version");

    Object.assign(ctx, { pkgRoot: v1, dist: join(v1, "dist") });
    run(["install", "claude-code"], ctx);
    const settingsPath = join(ctx.home, ".claude", "settings.json");
    const before = readFileSync(settingsPath, "utf8");

    Object.assign(ctx, { pkgRoot: v2, dist: join(v2, "dist") });
    expect(run(["update"], ctx)).toBe(0);

    const staged = join(ctx.home, ".contextbase", "coding-agents", "dist");
    expect(existsSync(join(staged, "new-only.js"))).toBe(true);
    // Byte-identical: the hooks already point at the staged path, so an update has no reason to
    // rewrite them — and rewriting is exactly what would let an unattended run wire agents the
    // user never installed.
    expect(readFileSync(settingsPath, "utf8")).toBe(before);
  });

  it("`update` needs no harness argument and wires nothing when nothing is installed", () => {
    const ctx = makeCtx();
    const src = mkdtempSync(join(tmpdir(), "pkg-"));
    homes.push(src);
    fakePackage(src);
    Object.assign(ctx, { pkgRoot: src, dist: join(src, "dist") });

    expect(run(["update"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agents", "dist"))).toBe(true);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(false);
  });

  // The marker is what core/auto-update.ts reads to decide whether it may replace this runtime,
  // so staging has to write it — an absent marker fails closed and auto-update never runs.
  it("records where the runtime was staged from", () => {
    const ctx = makeCtx();
    const cache = mkdtempSync(join(tmpdir(), "npx-cache-"));
    homes.push(cache);
    const src = join(cache, "_npx", "abc123", "node_modules", "coding-agents");
    Object.assign(ctx, fakePackage(src));

    run(["install", "claude-code"], ctx);
    const origin = readJson(
      join(ctx.home, ".contextbase", "coding-agents", ".install-origin.json")
    ) as { source: string };
    expect(origin.source).toBe(src);
  });

  // A checkout whose dist was never built has nothing to copy; wiring the source path is better
  // than pointing every hook at a directory that does not exist.
  it("wires in place when there is nothing to stage", () => {
    const ctx = makeCtx();
    run(["install", "claude-code"], ctx);
    const command = readJson(join(ctx.home, ".claude", "settings.json")).hooks.SessionStart[0]
      .hooks[0].command as string;
    expect(command).toContain(ctx.dist);
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agents", "dist"))).toBe(false);
  });
});

describe("skill install across skills-capable hosts", () => {
  it("copies the packaged skill for claude/codex(~/.agents)/antigravity/cursor/qwen/prime-agent and uninstall removes each", () => {
    const home = mkdtempSync(join(tmpdir(), "hs-inst-skill-"));
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-"));
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(
      join(pkgRoot, "skill", "SKILL.md"),
      "---\nname: contextbase-coding-agent\n---\nbody"
    );
    const ctx = {
      home,
      pkgRoot,
      dist: join(pkgRoot, "dist"),
      claudeMcp: vi.fn(() => true),
      qwenMcp: vi.fn((args: string[]) => {
        const path = join(home, ".qwen", "settings.json");
        const config = existsSync(path) ? readJson(path) : {};
        config.mcpServers ??= {};
        if (args[1] === "add") {
          if (config.mcpServers.contextbase) return false;
          const name = args.indexOf("contextbase");
          config.mcpServers.contextbase = {
            command: args[name + 1],
            args: args.slice(name + 2),
            env: { CONTEXTBASE_MCP_HARNESS: "qwen-code" },
          };
        } else if (args[1] === "remove") {
          if (!args.includes("user"))
            throw new Error("MCP removal must explicitly select user scope");
          delete config.mcpServers.contextbase;
        }
        writeJsonAt(path, config);
        return true;
      }),
    };
    const targets: [string, string][] = [
      ["claude-code", join(home, ".claude", "skills")],
      ["codex", join(home, ".agents", "skills")],
      ["antigravity-cli", join(home, ".gemini", "config", "skills")],
      ["cursor-cli", join(home, ".cursor", "skills")],
      ["qwen-code", join(home, ".qwen", "skills")],
      // Prime Agent's OWN root, never the shared ~/.agents one it also reads: uninstall removes a
      // fixed directory name, so the shared root would take Codex's and dsh's copy with it (#3772).
      ["prime-agent", join(home, ".prime", "agent", "skills")],
    ];
    run(["install", ...targets.map(([h]) => h)], ctx);
    for (const [, base] of targets) {
      expect(existsSync(join(base, "contextbase-coding-agent", "SKILL.md"))).toBe(true);
    }
    run(["uninstall", ...targets.map(([h]) => h)], ctx);
    for (const [, base] of targets) {
      expect(existsSync(join(base, "contextbase-coding-agent"))).toBe(false);
    }
    rmSync(home, { recursive: true, force: true });
    rmSync(pkgRoot, { recursive: true, force: true });
  });

  // uninstallSkill removes a fixed directory NAME, so a host installing into the shared
  // agentskills root would delete the copy another host is still using.
  it("uninstalling prime-agent leaves the shared ~/.agents copy Codex installed", () => {
    const home = mkdtempSync(join(tmpdir(), "hs-inst-skill-"));
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-"));
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(
      join(pkgRoot, "skill", "SKILL.md"),
      "---\nname: contextbase-coding-agent\n---\nbody"
    );
    const ctx = {
      home,
      pkgRoot,
      dist: join(pkgRoot, "dist"),
      claudeMcp: vi.fn(() => true),
      qwenMcp: vi.fn((args: string[]) => {
        const path = join(home, ".qwen", "settings.json");
        const config = existsSync(path) ? readJson(path) : {};
        config.mcpServers ??= {};
        if (args[1] === "add") {
          if (config.mcpServers.contextbase) return false;
          const name = args.indexOf("contextbase");
          config.mcpServers.contextbase = {
            command: args[name + 1],
            args: args.slice(name + 2),
            env: { CONTEXTBASE_MCP_HARNESS: "qwen-code" },
          };
        } else if (args[1] === "remove") {
          if (!args.includes("user"))
            throw new Error("MCP removal must explicitly select user scope");
          delete config.mcpServers.contextbase;
        }
        writeJsonAt(path, config);
        return true;
      }),
    };

    run(["install", "codex", "prime-agent"], ctx);
    run(["uninstall", "prime-agent"], ctx);

    expect(
      existsSync(join(home, ".agents", "skills", "contextbase-coding-agent", "SKILL.md"))
    ).toBe(true);
    expect(existsSync(join(home, ".prime", "agent", "skills", "contextbase-coding-agent"))).toBe(
      false
    );
    rmSync(home, { recursive: true, force: true });
    rmSync(pkgRoot, { recursive: true, force: true });
  });
});

/**
 * Devin is the only harness that cannot fall back to a transcript file: its hooks pass a session id
 * and the conversation lives in a SQLite database. Without `node:sqlite` the install used to
 * succeed and then retain nothing, forever (#3125).
 */
describe("devin-cli preflight", () => {
  it("refuses to install when the hook node can't read SQLite", () => {
    const ctx = makeCtx();
    ctx.nodeSqlite = vi.fn(() => false);
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);

    expect(run(["install", "devin-cli"], ctx)).toBe(1);
    // Nothing written: a blocked harness must leave the machine untouched.
    expect(existsSync(join(ctx.home, ".config", "devin", "config.json"))).toBe(false);
    const output = logs.join("\n");
    expect(output).toContain("node:sqlite");
    expect(output).toContain("Node 22.5");
    expect(output).not.toContain("✅ installed");
  });

  it("installs normally when SQLite is available", () => {
    const ctx = makeCtx();
    expect(run(["install", "devin-cli"], ctx)).toBe(0);
    expect(existsSync(join(ctx.home, ".config", "devin", "config.json"))).toBe(true);
    expect(ctx.nodeSqlite).toHaveBeenCalled();
  });

  it("blocks only the failing harness, still wiring the rest", () => {
    const ctx = makeCtx();
    ctx.nodeSqlite = vi.fn(() => false);
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);

    // Non-zero exit so a script notices, but Claude Code is still set up.
    expect(run(["install", "claude-code", "devin-cli"], ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(true);
    expect(existsSync(join(ctx.home, ".config", "devin", "config.json"))).toBe(false);
    expect(logs.join("\n")).toContain("not installed: devin-cli");
  });

  it("does not block uninstall", () => {
    const ctx = makeCtx();
    run(["install", "devin-cli"], ctx);
    ctx.nodeSqlite = vi.fn(() => false);
    expect(run(["uninstall", "devin-cli"], ctx)).toBe(0);
  });
});

describe("explicit remote server setup", () => {
  const configPath = (ctx: InstallCtx) => join(ctx.home, ".contextbase", "coding-agent.json");
  it("honors the same config path as the runtime", () => {
    const ctx = makeCtx();
    const override = join(ctx.home, "elsewhere", "config.json");
    vi.stubEnv("CONTEXTBASE_CONFIG", override);
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    expect(readJson(override).apiUrl).toBe("https://service.example");
    expect(existsSync(configPath(ctx))).toBe(false);
  });
  it("fails before registering hooks when no endpoint is configured", () => {
    vi.stubEnv("CONTEXTBASE_API_URL", "");
    const ctx = makeCtx();
    const logs: string[] = [];
    ctx.log = (m) => logs.push(m);
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(logs.join("\n")).toContain("API Endpoint");
    expect(existsSync(configPath(ctx))).toBe(false);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(false);
  });
  it.each(["daemon", "hybrid"])("rejects unsupported mode %s", (mode) => {
    const ctx = makeCtx();
    expect(run(["install", "claude-code", "--server", mode], ctx)).toBe(1);
    expect(existsSync(configPath(ctx))).toBe(false);
  });
  it.each([
    "file:///tmp/api",
    "https://user:secret@service.example",
    "https://service.example?token=secret",
  ])("rejects invalid endpoint %s", (url) => {
    const ctx = makeCtx();
    expect(run(["install", "claude-code", "--api-url", url], ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(false);
  });
  it("stores an explicit endpoint and token, and is idempotent", () => {
    const ctx = makeCtx();
    expect(
      run(
        [
          "install",
          "claude-code",
          "--api-url",
          "https://tenant.example/api/",
          "--api-token",
          "tenant-key",
        ],
        ctx
      )
    ).toBe(0);
    expect(run(["install", "claude-code"], ctx)).toBe(0);
    expect(readJson(configPath(ctx))).toMatchObject({
      apiUrl: "https://tenant.example/api",
      apiToken: "tenant-key",
    });
  });
  it("does not reuse a stored credential when changing endpoint", () => {
    const ctx = makeCtx();
    vi.stubEnv("CONTEXTBASE_API_TOKEN", "");
    writeJsonAt(configPath(ctx), { apiUrl: "https://old.example", apiToken: "old-key" });
    expect(run(["install", "claude-code", "--api-url", "https://new.example"], ctx)).toBe(0);
    expect(readJson(configPath(ctx)).apiToken).toBeUndefined();
  });
});

/**
 * Companion-skill parity across every host that installs one (#3524 shape).
 *
 * The installer writes the skill and core/skill-sync.ts re-copies it on drift at every session
 * start, so `npm update -g` upgrades the skill too. Those were two hand-maintained path lists, and
 * the self-update one covered four of the ten hosts — the six it missed kept whichever SKILL.md
 * they were installed with, forever, with nothing failing. A per-host test cannot catch that: the
 * host that is forgotten is by definition the one nobody wrote a test for.
 *
 * So drive the real thing over the WHOLE family: install each harness into a temp home, find where
 * the skill actually landed, and require that the self-update refreshes that same copy.
 */
describe("every installed companion skill is kept current by the session-start self-update", () => {
  const SKILL_NAME = "contextbase-coding-agent";

  /** makeCtx's pkgRoot is a synthetic /opt path, so the packaged skill can't be staged in it.
   *  Build a real temp package root holding a SKILL.md the installer can copy. */
  function ctxWithPackagedSkill(body: string): InstallCtx {
    const ctx = makeCtx();
    const pkgRoot = mkdtempSync(join(tmpdir(), "hs-pkg-skillsync-"));
    homes.push(pkgRoot);
    mkdirSync(join(pkgRoot, "skill"), { recursive: true });
    writeFileSync(join(pkgRoot, "skill", "SKILL.md"), body);
    return { ...ctx, pkgRoot, dist: join(pkgRoot, "dist") };
  }

  /** Every directory named `contextbase-coding-agent` under `root`, home-relative. */
  function findSkillCopies(root: string, prefix: string[] = []): string[][] {
    return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
      if (!entry.isDirectory()) return [];
      const rel = [...prefix, entry.name];
      return entry.name === SKILL_NAME ? [rel] : findSkillCopies(join(root, entry.name), rel);
    });
  }

  /** Hosts that install no skill at all, and why — so a host that silently STOPS installing one
   *  fails here instead of passing as "nothing to check". opencode (both major versions) and its
   *  Kilo fork have no skills mechanism; Devin and Dcode read no user-level skills directory
   *  either. */
  // CodeArts currently exposes MCP tools without installing lifecycle skills.
  const NO_SKILL_MECHANISM = [
    "codearts-agent",
    "codearts-cli",
    "dcode",
    "devin-cli",
    "kilo",
    "opencode",
    "opencode2",
  ];

  it("lands in the mapped directory and is refreshed there, for every host that has one", async () => {
    const { syncCompanionSkill } = await import("./core/skill-sync");
    const withoutSkill: string[] = [];
    for (const harness of INSTALLERS.map((i) => i.name)) {
      const ctx = ctxWithPackagedSkill("packaged v1");
      run(["install", harness], ctx);
      const copies = findSkillCopies(ctx.home);
      if (!copies.length) {
        withoutSkill.push(harness);
        continue;
      }
      // Where it landed must be the directory the shared map names, so the self-update looks there.
      expect(
        copies.map((parts) => parts.slice(0, -1)),
        harness
      ).toEqual([SKILL_DIRS[harness]]);

      // And the self-update must actually refresh THIS host's copy when the package moves on.
      const installed = join(ctx.home, ...copies[0], "SKILL.md");
      const srcDir = mkdtempSync(join(tmpdir(), "hs-pkg-newer-"));
      homes.push(srcDir);
      writeFileSync(join(srcDir, "SKILL.md"), "packaged v2");
      syncCompanionSkill(harness, { home: ctx.home, srcDir });
      expect(readFileSync(installed, "utf8"), harness).toBe("packaged v2");
    }
    expect(withoutSkill.sort()).toEqual(NO_SKILL_MECHANISM);
  });
});

describe("shared MCP registration ownership", () => {
  it.each([
    ["antigravity-cli", [".gemini", "config", "mcp_config.json"]],
    ["devin-cli", [".config", "devin", "mcp_config.json"]],
    ["cursor-cli", [".cursor", "mcp.json"]],
    ["copilot-cli", [".copilot", "mcp-config.json"]],
    ["kimi-code", [".kimi-code", "mcp.json"]],
    ["cline-cli", [".cline", "data", "settings", "cline_mcp_settings.json"]],
    ["factory-droid", [".factory", "mcp.json"]],
    ["workbuddy", [".workbuddy", "mcp.json"]],
    ["codebuddy", [".codebuddy", ".mcp.json"]],
    ["qwen-code", [".qwen", "settings.json"]],
    ["claude-code", [".claude.json"]],
  ] as const)("keeps a user-managed server during %s install and uninstall", (harness, parts) => {
    for (const foreign of [
      {
        type: "http",
        url: "https://service.example/mcp",
        headers: { Authorization: "Bearer user-key" },
      },
      {
        command: "node",
        args: ["/user/independent-server.js"],
        env: { TOKEN: "fixture-credential" },
      },
    ]) {
      const ctx = makeCtx();
      const file = join(ctx.home, ...parts);
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, JSON.stringify({ mcpServers: { contextbase: foreign } }));
      const installer = INSTALLERS.find((i) => i.name === harness)!;
      installer.install(ctx);
      installer.install(ctx);
      expect(JSON.parse(readFileSync(file, "utf8")).mcpServers.contextbase).toEqual(foreign);
      installer.uninstall(ctx);
      expect(JSON.parse(readFileSync(file, "utf8")).mcpServers.contextbase).toEqual(foreign);
    }
  });
});

describe("CodeArts MCP configuration", () => {
  it.each(["codearts-agent", "codearts-cli"])(
    "preserves credentials and host settings when reinstalling %s",
    (harness) => {
      const ctx = makeCtx();
      const cli = harness === "codearts-cli";
      const path = join(ctx.home, "mcp_settings.json");
      const key = cli ? "mcp" : "mcpServers";
      const environment = {
        CONTEXTBASE_MCP_HARNESS: "stale-harness",
        CONTEXTBASE_API_TOKEN: "fixture-token",
        NODE_EXTRA_CA_CERTS: "C:\\Corp CA\\root.pem",
        HTTPS_PROXY: "http://proxy.example:8080",
      };
      const script = "C:\\Users\\A\\.contextbase\\coding-agents\\dist\\mcp-server.js";
      const original = cli
        ? {
            type: "local",
            command: ["node", script, "user-argument"],
            environment,
            enabled: false,
            timeout: 600000,
          }
        : {
            command: "node",
            args: [script, "user-argument"],
            env: environment,
            disabled: true,
            timeout: 600000,
          };
      writeJsonAt(path, { [key]: { contextbase: original } });
      const args = [harness, "--mcp-config", path];
      expect(run(["install", ...args], ctx)).toBe(0);
      expect(run(["install", ...args], ctx)).toBe(0);
      const entry = readJson(path)[key].contextbase;
      const updatedEnvironment = { ...environment, CONTEXTBASE_MCP_HARNESS: harness };
      expect(entry).toEqual(
        cli
          ? {
              ...original,
              command: ["node", join(ctx.dist, "mcp-server.js"), "user-argument"],
              environment: updatedEnvironment,
            }
          : {
              ...original,
              args: [join(ctx.dist, "mcp-server.js"), "user-argument"],
              env: updatedEnvironment,
            }
      );
      expect(run(["uninstall", ...args], ctx)).toBe(0);
      expect(readJson(path)[key].contextbase).toBeUndefined();
    }
  );

  it.each(["codearts-agent", "codearts-cli"])(
    "installs, refreshes and uninstalls %s while preserving other config",
    (harness) => {
      const ctx = makeCtx();
      const path = join(
        ctx.home,
        "custom path",
        harness === "codearts-agent" ? "mcp_settings.json" : "codearts_cli.jsonc"
      );
      const key = harness === "codearts-cli" ? "mcp" : "mcpServers";
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(
        path,
        `{\n  // keep user settings\n  "theme": "dark",\n  "${key}": {\n    // keep other server\n    "other": {"url": "https://other.example.com"}\n  }\n}`
      );
      const original = readFileSync(path, "utf8");
      const args = [harness, "--mcp-config", path];
      expect(run(["install", ...args], ctx)).toBe(0);
      expect(run(["install", ...args], ctx)).toBe(0);
      const installed = parseJsonc(readFileSync(path, "utf8"))!;
      const entry = installed[key].contextbase;
      expect(Object.keys(installed[key]).sort()).toEqual(["contextbase", "other"]);
      if (harness === "codearts-cli") {
        expect(entry).toMatchObject({
          type: "local",
          enabled: true,
          command: ["node", join(ctx.dist, "mcp-server.js")],
          environment: { CONTEXTBASE_MCP_HARNESS: harness },
        });
      } else {
        expect(entry).toMatchObject({
          command: "node",
          args: [join(ctx.dist, "mcp-server.js")],
          env: { CONTEXTBASE_MCP_HARNESS: harness },
        });
      }
      expect(run(["uninstall", ...args], ctx)).toBe(0);
      const after = readFileSync(path, "utf8");
      expect(after).toContain("// keep user settings");
      expect(after).toContain("// keep other server");
      expect(parseJsonc(after)).toEqual({
        theme: "dark",
        [key]: { other: { url: "https://other.example.com" } },
      });
      expect(readFileSync(`${path}.contextbase-backup`, "utf8")).toBe(original);
    }
  );

  it("uses the CLI's existing JSONC file and the IDE's existing mcp map", () => {
    const ctx = makeCtx();
    const cli = join(ctx.home, ".codeartsdoer", "codearts_cli.jsonc");
    mkdirSync(dirname(cli), { recursive: true });
    writeFileSync(cli, '{"mcp": {}}');
    expect(run(["install", "codearts-cli"], ctx)).toBe(0);
    expect(parseJsonc(readFileSync(cli, "utf8"))!.mcp.contextbase.type).toBe("local");
    expect(existsSync(join(dirname(cli), "codearts_cli.json"))).toBe(false);
    const ide = join(ctx.home, "mcp_settings.json");
    writeFileSync(ide, '{"mcp": {}}');
    expect(run(["install", "codearts-agent", "--mcp-config", ide], ctx)).toBe(0);
    const config = parseJsonc(readFileSync(ide, "utf8"))!;
    expect(config.mcp.contextbase.command).toBe("node");
    expect(config.mcpServers).toBeUndefined();
  });

  it("requires one explicit IDE path and preserves invalid or externally managed configuration", () => {
    const ctx = makeCtx();
    expect(run(["install", "codearts-agent"], ctx)).toBe(1);
    expect(run(["install", "codearts-agent", "--mcp-config"], ctx)).toBe(1);
    const path = join(ctx.home, "mcp_settings.json");
    for (const content of [
      "{broken",
      "[]",
      '{"mcpServers": []}',
      '{"mcp": {}, "mcpServers": {}}',
      '{"mcpServers":{"contextbase":{"url":"https://external.example.com"}}}',
    ]) {
      writeFileSync(path, content);
      expect(run(["install", "codearts-agent", "--mcp-config", path], ctx)).toBe(1);
      run(["uninstall", "codearts-agent", "--mcp-config", path], ctx);
      expect(readFileSync(path, "utf8")).toBe(content);
    }
    expect(run(["install", "codearts-agent", "codearts-cli", "--mcp-config", path], ctx)).toBe(1);
  });
});

describe("Claude and Codex protect the UI's independent remote MCP registration", () => {
  const foreign = {
    type: "http",
    url: "https://mcp.example/gateway/workspace",
    headers: { Authorization: "Bearer fixture-credential" },
  };
  it("Claude install/uninstall keeps a foreign user-scoped entry and never calls remove/add", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".claude.json");
    const original = {
      mcpServers: { contextbase: foreign },
      projects: { project: { mcpServers: { other: foreign } } },
    };
    writeJsonAt(path, original);
    const bytes = readFileSync(path, "utf8");
    const logs: string[] = [];
    ctx.log = (line) => logs.push(line);
    run(["install", "claude-code"], ctx);
    run(["uninstall", "claude-code"], ctx);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(readFileSync(path, "utf8")).toBe(bytes);
    expect(logs.join("\n")).toContain("preserved");
  });
  it("Claude unreadable or malformed config is preserved without destructive CLI calls", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".claude.json");
    writeFileSync(path, "{ broken JSON");
    run(["install", "claude-code"], ctx);
    run(["uninstall", "claude-code"], ctx);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(readFileSync(path, "utf8")).toBe("{ broken JSON");
  });
  it("Claude uninstall removes only an owned script entry, preserving other scopes and names", () => {
    const ctx = makeCtx();
    run(["install", "claude-code"], ctx);
    const path = join(ctx.home, ".claude.json");
    const config = readJson(path);
    config.mcpServers.other = foreign;
    config.projects = { project: { mcpServers: { contextbase: foreign } } };
    writeJsonAt(path, config);
    run(["uninstall", "claude-code"], ctx);
    expect(readJson(path)).toEqual({ mcpServers: { other: foreign }, projects: config.projects });
  });
  it.each([
    'url = "https://mcp.example/gateway/workspace"\nhttp_headers = { Authorization = "Bearer fixture-credential" }',
    'command = "node"\nargs = ["/user/independent-server.js"]\nenv = { TOKEN = "fixture-credential" }',
  ])("Codex install/uninstall preserves a foreign MCP entry: %s", (entry) => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".codex", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    const original = `[features]\nhooks = true\n\n[mcp_servers.contextbase]\n${entry}\n`;
    writeFileSync(path, original);
    run(["install", "codex"], ctx);
    run(["uninstall", "codex"], ctx);
    expect(readFileSync(path, "utf8")).toBe(original);
  });
  it.each(["[mcp_servers.contextbase]", '[mcp_servers."contextbase"]'])(
    "updates a moved owned script in %s and can uninstall it",
    (table) => {
      const ctx = makeCtx();
      const path = join(ctx.home, ".codex", "config.toml");
      mkdirSync(dirname(path), { recursive: true });
      writeFileSync(
        path,
        `${table}\ncommand = "node"\nargs = ["/old/contextbase-coding-agents/dist/mcp-server.js"]\n\n[unrelated]\nvalue = "preserve"\n`
      );
      run(["install", "codex"], ctx);
      const config = parseToml(readFileSync(path, "utf8"));
      expect((config.mcp_servers as any).contextbase.args).toEqual([
        join(ctx.dist, "mcp-server.js"),
      ]);
      run(["uninstall", "codex"], ctx);
      expect(readFileSync(path, "utf8")).toContain('[unrelated]\nvalue = "preserve"');
      expect(readFileSync(path, "utf8")).not.toContain("mcp_servers.contextbase");
    }
  );
  it("Codex malformed TOML is left intact by install and uninstall", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".codex", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "[broken");
    run(["install", "codex"], ctx);
    run(["uninstall", "codex"], ctx);
    expect(readFileSync(path, "utf8")).toBe("[broken");
  });
});

describe("Qwen scoped ownership", () => {
  it("repoints only owned scripts and explicitly removes in user scope", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".qwen", "settings.json");
    writeJsonAt(path, {
      mcpServers: {
        contextbase: {
          command: "node",
          args: ["/old/contextbase-coding-agents/dist/mcp-server.js"],
        },
        other: { url: "https://other.example/mcp" },
      },
    });
    run(["install", "qwen-code"], ctx);
    run(["install", "qwen-code"], ctx);
    expect(readJson(path).mcpServers.contextbase.args).toEqual([join(ctx.dist, "mcp-server.js")]);
    run(["uninstall", "qwen-code"], ctx);
    expect(readJson(path).mcpServers).toEqual({ other: { url: "https://other.example/mcp" } });
    const removals = ctx.qwenMcp.mock.calls.filter(([args]) => args[1] === "remove");
    expect(removals).toHaveLength(3);
    for (const [args] of removals)
      expect(args).toEqual(["mcp", "remove", "-s", "user", "contextbase"]);
  });
  it("preserves malformed user configuration without calling the host CLI", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".qwen", "settings.json");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "{ broken");
    expect(run(["install", "qwen-code"], ctx)).toBe(1);
    expect(run(["uninstall", "qwen-code"], ctx)).toBe(1);
    expect(ctx.qwenMcp).not.toHaveBeenCalled();
    expect(readFileSync(path, "utf8")).toBe("{ broken");
  });
});

describe("customer Workspace setup", () => {
  it.each([true, false, undefined])(
    "preserves existing optInOnly=%s when adding a project",
    (optInOnly) => {
      const ctx = makeCtx();
      const path = join(ctx.home, ".contextbase", "coding-agent.json");
      writeJsonAt(path, { apiUrl: "https://service.example", optInOnly });
      expect(
        run(["install", "claude-code", "--bank-id", "new-bank", "--project-path", ctx.home], ctx)
      ).toBe(0);
      expect(readJson(path).optInOnly).toBe(optInOnly);
    }
  );
  it("does not force opt-in for a new customer configuration", () => {
    const ctx = makeCtx();
    expect(
      run(
        [
          "install",
          "claude-code",
          "--api-url",
          "https://service.example",
          "--bank-id",
          "new-bank",
          "--project-path",
          ctx.home,
        ],
        ctx
      )
    ).toBe(0);
    expect(readJson(join(ctx.home, ".contextbase", "coding-agent.json")).optInOnly).toBeUndefined();
  });

  it("sets one Bank for every project and client, replacing obsolete selection settings", () => {
    const ctx = makeCtx();
    const project = join(ctx.home, "project with spaces");
    mkdirSync(project);
    const path = join(ctx.home, ".contextbase", "coding-agent.json");
    writeJsonAt(path, {
      apiUrl: "https://service.example",
      mapPathToBank: { "/other": "other-bank" },
      optInOnly: true,
      optInPaths: [project],
      banks: { "other-bank": { autoSeed: true } },
    });
    const args = [
      "install",
      "claude-code",
      "codex",
      "--bank-id",
      "customer-bank",
      "--project-path",
      project,
    ];
    expect(run(args, ctx)).toBe(0);
    expect(run(args, ctx)).toBe(0);
    const cfg = readJson(path);
    expect(cfg.mapPathToBank).toBeUndefined();
    expect(cfg.bankId).toBe("customer-bank");
    expect(cfg.optInOnly).toBe(true);
    expect(cfg.banks["customer-bank"]).toEqual({
      manageBankConfig: false,
      autoSeed: false,
      codebaseSurvey: false,
    });
    expect(cfg.banks["other-bank"]).toEqual({ autoSeed: true });
    for (const harness of ["claude-code", "codex"]) {
      const loaded = loadConfig({ path, harness });
      const bank = configuredBankId(loaded);
      expect(bank).toBe("customer-bank");
      expect(applyBankConfig(loaded, bank, project).cfg).toMatchObject({
        autoSeed: false,
        manageBankConfig: false,
        codebaseSurvey: false,
        retainSessions: true,
      });
      expect(applyBankConfig(loaded, "unrelated", ctx.home).cfg.disabled).toBe(true);
    }
    expect(
      parseToml(readFileSync(join(ctx.home, ".codex", "config.toml"), "utf8")).features
    ).toMatchObject({ hooks: true });
  });
  it.each([
    ["--bank-id"],
    ["--bank-id", "--api-url", "https://service.example"],
    ["--bank-id="],
    ["--bank-id", "bank", "--project-path", "/does-not-exist/contextbase"],
  ])("rejects incomplete binding %j before registering clients", (...args) => {
    const ctx = makeCtx();
    expect(run(["install", "claude-code", ...args], ctx)).toBe(1);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agent.json"))).toBe(false);
  });
  it("preserves malformed customer configuration and fails", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".contextbase", "coding-agent.json");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "{broken");
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(readFileSync(path, "utf8")).toBe("{broken");
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
  });
  it.each([
    "[features]\nhooks = false # disabled\nother = true\n",
    "[features]\nother = true\n",
    '["features"]\n"hooks" = false\n',
    "[features]\ncodex_hooks = true\n",
    "[unrelated]\nhooks = false\n",
  ])("enables Codex hooks in the correct table without changing model settings: %s", (features) => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".codex", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    const original = 'model = "custom-model"\n# keep this comment\n' + features;
    writeFileSync(path, original);
    expect(run(["install", "codex"], ctx)).toBe(0);
    const saved = readFileSync(path, "utf8");
    const parsed = parseToml(saved);
    expect(parsed.features).toMatchObject({ hooks: true });
    expect(parsed.model).toBe("custom-model");
    expect(saved).toContain("# keep this comment");
    expect(readFileSync(path + ".contextbase-backup", "utf8")).toBe(original);
    expect(run(["install", "codex"], ctx)).toBe(0);
  });
  it("does not claim success for an unreadable Codex config", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".codex", "config.toml");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "[broken");
    expect(run(["install", "codex"], ctx)).toBe(1);
    expect(readFileSync(path, "utf8")).toBe("[broken");
  });
});

it("treats a bank named codex as a flag value without losing the Codex target", () => {
  const ctx = makeCtx();
  const path = join(ctx.home, ".contextbase", "coding-agent.json");
  writeJsonAt(path, { banks: { codex: { bank: "old-alias", autoSeed: true } } });
  expect(run(["install", "codex", "--bank-id", "codex", "--project-path", ctx.home], ctx)).toBe(0);
  expect(readJson(path).banks.codex.bank).toBeUndefined();
  expect(existsSync(join(ctx.home, ".codex", "config.toml"))).toBe(true);
});

describe("bank use", () => {
  it("switches only the shared configuration and preserves connection, behavior and host files", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".contextbase", "coding-agent.json");
    const settings = join(ctx.home, ".claude", "settings.json");
    writeJsonAt(settings, { hooks: { foreign: [] } });
    const before = readFileSync(settings, "utf8");
    writeJsonAt(path, {
      apiUrl: "https://service.example",
      apiToken: "keep-token",
      bankId: "old",
      retainSessions: false,
      dynamicBankId: true,
      bankIdTemplate: "{project}",
      mapPathToBank: { "/work": "legacy" },
      banks: { old: { disabled: true }, next: { bank: "alias", retainSessions: true } },
    });
    expect(run(["bank", "use", "next"], ctx)).toBe(0);
    const cfg = readJson(path);
    expect(cfg).toMatchObject({
      apiUrl: "https://service.example",
      apiToken: "keep-token",
      bankId: "next",
      retainSessions: false,
    });
    expect(cfg.banks.old).toEqual({ disabled: true });
    expect(cfg.banks.next).toEqual({
      retainSessions: true,
      manageBankConfig: false,
      autoSeed: false,
      codebaseSurvey: false,
    });
    for (const key of ["mapPathToBank", "bankIdTemplate", "dynamicBankId"])
      expect(cfg[key]).toBeUndefined();
    expect(readFileSync(settings, "utf8")).toBe(before);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agents"))).toBe(false);
    for (const harness of ["claude-code", "codex", "opencode"])
      expect(loadConfig({ path, harness }).bankId).toBe("next");
  });
  it("honors CONTEXTBASE_CONFIG", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, "custom", "config.json");
    vi.stubEnv("CONTEXTBASE_CONFIG", path);
    expect(run(["bank", "use", "configured"], ctx)).toBe(0);
    expect(readJson(path).bankId).toBe("configured");
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agent.json"))).toBe(false);
  });
  it.each([
    ["bank", "use"],
    ["bank", "use", "  "],
    ["bank", "use", "a", "b"],
    ["bank", "list"],
  ])("rejects invalid arguments without writing: %s", (...args) => {
    const ctx = makeCtx();
    expect(run(args, ctx)).toBe(1);
    expect(existsSync(join(ctx.home, ".contextbase", "coding-agent.json"))).toBe(false);
  });
  it("preserves malformed configuration instead of replacing it", () => {
    const ctx = makeCtx();
    const path = join(ctx.home, ".contextbase", "coding-agent.json");
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, "{invalid");
    expect(run(["bank", "use", "next"], ctx)).toBe(1);
    expect(readFileSync(path, "utf8")).toBe("{invalid");
  });
  it("requires an explicit Bank before installing any host", () => {
    const ctx = makeCtx();
    vi.stubEnv("CONTEXTBASE_BANK_ID", "");
    expect(run(["install", "claude-code"], ctx)).toBe(1);
    expect(ctx.claudeMcp).not.toHaveBeenCalled();
    expect(existsSync(join(ctx.home, ".claude", "settings.json"))).toBe(false);
  });
});
