import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock the ContextBaseClient before importing the plugin
vi.mock("contextbase-client", () => {
  const MockContextBaseClient = vi.fn(function (this: any) {
    this.retain = vi.fn().mockResolvedValue({});
    this.recall = vi.fn().mockResolvedValue({ results: [] });
    this.reflect = vi.fn().mockResolvedValue({ text: "" });
    this.createBank = vi.fn().mockResolvedValue({});
  });
  return { ContextBaseClient: MockContextBaseClient };
});

import { ContextBasePlugin } from "./index.js";
import { DEFAULT_CONTEXTBASE_API_URL } from "./config.js";
import { ContextBaseClient } from "contextbase-client";

const mockPluginInput = {
  client: {
    session: {
      messages: vi.fn().mockResolvedValue({ data: [] }),
    },
  },
  project: { id: "test-project", worktree: "/tmp/test", vcs: "git" },
  directory: "/tmp/test-project",
  worktree: "/tmp/test-project",
  serverUrl: new URL("http://localhost:3000"),
  $: {} as any,
};

describe("ContextBasePlugin", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith("CONTEXTBASE_")) delete process.env[key];
    }
    vi.clearAllMocks();
  });

  afterEach(() => {
    process.env = { ...originalEnv };
  });

  it("defaults to the hosted backend URL when no API URL is configured", async () => {
    const result = await ContextBasePlugin(mockPluginInput as any);

    expect(ContextBaseClient).toHaveBeenCalledWith({
      baseUrl: DEFAULT_CONTEXTBASE_API_URL,
      apiKey: undefined,
      userAgent: expect.stringMatching(/^contextbase-opencode\/\d+\.\d+\.\d+$/),
    });
    // Full tool + hook surface still returned — the plugin doesn't disable
    // itself just because the URL was left at its default.
    expect(result.tool).toBeDefined();
    expect(result.event).toBeDefined();
    expect(result["experimental.session.compacting"]).toBeDefined();
    expect(result["experimental.chat.system.transform"]).toBeDefined();
  });

  it("returns tools and hooks when configured", async () => {
    process.env.CONTEXTBASE_API_URL = "http://localhost:8888";

    const result = await ContextBasePlugin(mockPluginInput as any);

    expect(ContextBaseClient).toHaveBeenCalledWith({
      baseUrl: "http://localhost:8888",
      apiKey: undefined,
      userAgent: expect.stringMatching(/^contextbase-opencode\/\d+\.\d+\.\d+$/),
    });

    expect(result.tool).toBeDefined();
    expect(result.tool!.contextbase_retain).toBeDefined();
    expect(result.tool!.contextbase_recall).toBeDefined();
    expect(result.tool!.contextbase_reflect).toBeDefined();
    expect(result.event).toBeDefined();
    expect(result["experimental.session.compacting"]).toBeDefined();
    expect(result["experimental.chat.system.transform"]).toBeDefined();
  });

  it("passes API key when configured", async () => {
    process.env.CONTEXTBASE_API_URL = "http://localhost:8888";
    process.env.CONTEXTBASE_API_TOKEN = "my-token";

    await ContextBasePlugin(mockPluginInput as any);

    expect(ContextBaseClient).toHaveBeenCalledWith({
      baseUrl: "http://localhost:8888",
      apiKey: "my-token",
      userAgent: expect.stringMatching(/^contextbase-opencode\/\d+\.\d+\.\d+$/),
    });
  });

  it("accepts plugin options", async () => {
    const result = await ContextBasePlugin(mockPluginInput as any, {
      contextbaseApiUrl: "http://example.com",
      bankId: "custom-bank",
    });

    expect(result.tool).toBeDefined();
    expect(ContextBaseClient).toHaveBeenCalledWith({
      baseUrl: "http://example.com",
      apiKey: undefined,
      userAgent: expect.stringMatching(/^contextbase-opencode\/\d+\.\d+\.\d+$/),
    });
  });
});

describe("ContextBasePlugin state sharing", () => {
  beforeEach(() => {
    for (const key of Object.keys(process.env)) {
      if (key.startsWith("CONTEXTBASE_")) delete process.env[key];
    }
    vi.clearAllMocks();
  });

  it("shares state across multiple plugin instantiations (sessions)", async () => {
    process.env.CONTEXTBASE_API_URL = "http://localhost:8888";

    // Simulate two sessions calling the plugin (OpenCode instantiates per session)
    const result1 = await ContextBasePlugin(mockPluginInput as any);
    const result2 = await ContextBasePlugin(mockPluginInput as any);

    // Trigger session.created on session 1 — should track 'sess-A'
    await result1.event!({
      event: { type: "session.created", properties: { info: { id: "sess-A" } } },
    });

    // Session 2's system transform should see 'sess-A' because state is shared
    const output = { system: [] as string[] };
    await result2["experimental.chat.system.transform"]!(
      { sessionID: "sess-A", model: {} },
      output
    );

    // The recall was attempted (state was shared — sess-A was found in recalledSessions).
    // If state were per-instance, result2 would have an empty recalledSessions and skip recall.
    // result2 uses the second ContextBaseClient instance (index 1).
    const clientInstance = (ContextBaseClient as any).mock.instances[1];
    expect(clientInstance.recall).toHaveBeenCalled();
  });
});

describe("plugin default export", () => {
  it("default-exports the Plugin function itself", async () => {
    const mod = await import("./index.js");
    expect(typeof mod.default).toBe("function");
    // OpenCode iterates Object.entries(mod) and calls every export as a
    // Plugin factory, deduping by reference. The default export must be
    // the same reference as the named ContextBasePlugin export to avoid
    // running the factory twice.
    expect(mod.default).toBe(mod.ContextBasePlugin);
  });

  it("does not expose non-function exports from the plugin entry (#2028)", async () => {
    // OpenCode >=1.16 iterates EVERY export of the plugin entry and treats it
    // as a Plugin factory, throwing "Plugin export is not a function" on any
    // non-function value — a single re-exported constant (e.g. a string URL)
    // bricks the whole plugin load. Keep the entry surface function-only.
    const mod = await import("./index.js");
    for (const [name, value] of Object.entries(mod)) {
      expect(typeof value, `export "${name}" must be a function`).toBe("function");
    }
  });

  it("does not expose other callable utilities from the plugin entry (legacy-loader invariant)", async () => {
    // OpenCode's legacy plugin loader (getLegacyPlugins) iterates Object.values(mod)
    // and calls every function export as a Plugin factory. It deduplicates by
    // reference, so default and ContextBasePlugin (same fn) are fine. But any
    // other callable utility re-exported from the entry (e.g. loadConfig,
    // deriveBankId) would be incorrectly invoked as a plugin — likely producing
    // a hooks object with the wrong shape (a string, a config object, etc.) and
    // silently breaking session behavior.
    //
    // The fix is to NOT re-export utilities from the entry; consumers that
    // need them import from "@huaweicloud/opencode-contextbase/dist/config.js"
    // or rely on the plugin itself using them internally.
    const mod = await import("./index.js");
    const functionValues = Object.values(mod).filter((v) => typeof v === "function");
    // Exactly two function exports remain: the default export and the
    // ContextBasePlugin named export, both pointing at the same function.
    expect(functionValues.length).toBe(2);
    expect(functionValues[0]).toBe(functionValues[1]);
    // And the only callable symbol in the entry is the plugin itself.
    expect(new Set(functionValues).size).toBe(1);
  });
});
