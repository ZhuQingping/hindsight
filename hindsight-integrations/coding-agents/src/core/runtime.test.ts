import { existsSync, mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { resolveConfig } from "./config";
import type { HindsightClient } from "./hindsight";
import { RuntimeCore } from "./runtime";
import { log } from "./log";

describe("RuntimeCore", () => {
  it("uses the shared prompt lifecycle and consumes the new-bank reflect deferral once", async () => {
    const client = {
      listDocumentIds: vi.fn(async () => new Set(["git:existing"])),
      listPages: vi.fn(async () => ({ items: [] })),
      reflect: vi.fn(async () => "shared reflect"),
    } as unknown as HindsightClient;
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );

    await runtime.seedIfCold("/definitely-not-a-git-repository");
    await runtime.onPrompt("runtime-shared-lifecycle", "first prompt");
    expect(client.reflect).not.toHaveBeenCalled();

    await runtime.onPrompt("runtime-shared-lifecycle", "second prompt");
    expect(client.reflect).toHaveBeenCalledTimes(1);
    expect(runtime.getInjection("runtime-shared-lifecycle")).toContain("shared reflect");
  });

  it("the knowledge roster tracks the pages a SESSION sees, not the ones plugin load saw", async () => {
    // These hosts outlive every session. A preamble frozen at load told each new session "No
    // knowledge pages yet" for the process's whole life, while the same turn's memory block listed
    // pages by id — the agent was told both, and believed the stale half (#4607).
    let pages: { id: string; name: string }[] = [];
    const client = {
      listDocumentIds: vi.fn(async () => new Set(["git:existing"])),
      listPages: vi.fn(async () => ({ items: pages })),
      reflect: vi.fn(async () => ""),
    } as unknown as HindsightClient;
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );

    await runtime.seedIfCold("/definitely-not-a-git-repository"); // cold: zero pages
    await runtime.onPrompt("session-cold", "first prompt");
    expect(runtime.getInjection("session-cold")).toContain("No knowledge pages yet");

    pages = [
      { id: "kp-1", name: "Component map" },
      { id: "kp-2", name: "Key decisions and rationale" },
    ];
    await runtime.onPrompt("session-warm", "first prompt");
    const warm = runtime.getInjection("session-warm") ?? "";
    expect(warm).toContain("2 knowledge pages cover");
    expect(warm).not.toContain("No knowledge pages yet");
  });
});

/**
 * `messages.transform` fires while the host BUILDS a request, so the transcript it passes never
 * contains the reply that request produces. session.idle is the only moment a completed exchange is
 * readable — without it write-back lagged a turn and a session's final exchange was lost entirely.
 */
describe("RuntimeCore session-idle write-back", () => {
  const turn = (role: string, content: string) => ({ role, content }) as never;

  /** A client that records what retain() was given. */
  function makeClient() {
    const retained: { turns: unknown; docId: string }[] = [];
    const client = {
      retain: vi.fn(async (text: string, _ctx: string, docId: string) => {
        retained.push({ turns: text, docId });
      }),
    } as unknown as HindsightClient;
    return { client, retained };
  }

  it("retains the completed exchange on idle — the reply the turn-driven path never sees", async () => {
    const { client, retained } = makeClient();
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );

    // The turn-driven path sees only what existed BEFORE the reply.
    await runtime.onTranscript("s1", [turn("user", "how do we round?")], false);
    await new Promise((r) => setTimeout(r, 0)); // retain is fire-and-forget
    expect(retained).toHaveLength(1);
    expect(String(retained[0].turns)).not.toContain("we round half up");

    // Idle refetches, so the assistant's answer finally lands.
    runtime.setTranscriptSource(async () => [
      turn("user", "how do we round?"),
      turn("assistant", "we round half up"),
    ]);
    await runtime.onSessionIdle("s1");
    await new Promise((r) => setTimeout(r, 0)); // retain is fire-and-forget

    expect(retained).toHaveLength(2);
    expect(String(retained[1].turns)).toContain("we round half up");
    expect(retained[1].docId).toBe("conversation:s1");
  });

  it("writes back every turn — no client-side cadence to strand a short session", async () => {
    // There used to be a retainEveryTurns threshold here, which suppressed a session shorter than
    // it entirely. Batching now happens server-side (engine.retain.fold coalesces queued retains
    // for one document), so every turn is submitted immediately and nothing is held in a process
    // the host can close without warning.
    const { client, retained } = makeClient();
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );

    await runtime.onTranscript("s2", [turn("user", "only turn")], false);
    await new Promise((r) => setTimeout(r, 0));
    expect(retained).toHaveLength(1);

    runtime.setTranscriptSource(async () => [turn("user", "only turn"), turn("assistant", "done")]);
    await runtime.onSessionIdle("s2");
    await new Promise((r) => setTimeout(r, 0));
    expect(retained).toHaveLength(2);
  });

  it("does not re-retain when idle fires again with no new turns", async () => {
    const { client, retained } = makeClient();
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );
    runtime.setTranscriptSource(async () => [turn("user", "hi"), turn("assistant", "hello")]);

    await runtime.onSessionIdle("s3");
    await runtime.onSessionIdle("s3");
    await new Promise((r) => setTimeout(r, 0));
    expect(retained).toHaveLength(1);
  });

  it("records agentstratum usage for a turn only once its reply is in", async () => {
    const usageFile = join(mkdtempSync(join(tmpdir(), "hs-rt-usage-")), "usage.jsonl");
    vi.stubEnv("AGENTSTRATUM_USAGE_FILE", usageFile);
    try {
      const { client } = makeClient();
      const runtime = new RuntimeCore(
        client,
        "bank-1",
        resolveConfig({ apiUrl: "https://service.example" }),
        "kilo"
      );

      // Built before the reply: recording turn 1 now would log it with no calls, for good.
      await runtime.onTranscript("s6", [turn("user", "how do we round?")], false);
      expect(existsSync(usageFile)).toBe(false);

      runtime.setTranscriptSource(async () => [
        turn("user", "how do we round?"),
        turn("action", "agentstratum_search_knowledge_pages rounding"),
        turn("assistant", "🧠 From agentstratum memory — half up"),
      ]);
      await runtime.onSessionIdle("s6");
      const recorded = readFileSync(usageFile, "utf8")
        .trim()
        .split("\n")
        .map((l) => JSON.parse(l));
      expect(recorded).toMatchObject([
        {
          harness: "kilo",
          session: "s6",
          bank: "bank-1",
          turn: 1,
          calls: ["agentstratum_search_knowledge_pages"],
          credited: true,
        },
      ]);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it("no-ops when the host cannot refetch, rather than retaining a stale transcript", async () => {
    const { client, retained } = makeClient();
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );
    await runtime.onSessionIdle("s4"); // no transcript source wired
    await new Promise((r) => setTimeout(r, 0));
    expect(retained).toHaveLength(0);
  });

  it("survives a failing refetch without throwing into the host", async () => {
    const { client, retained } = makeClient();
    const runtime = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );
    runtime.setTranscriptSource(async () => {
      throw new Error("session gone");
    });
    await expect(runtime.onSessionIdle("s5")).resolves.toBeUndefined();
    expect(retained).toHaveLength(0);
  });
});

describe("RuntimeCore remote connection", () => {
  it.each([
    { config: { apiUrl: "" }, message: "API Endpoint is required" },
    { config: { apiUrl: "not-a-url" }, message: "API Endpoint must be a valid" },
    {
      config: { serverMode: "daemon" as const },
      message: "Local engines are not distributed",
    },
  ])("reports $message without rejecting or seeding", async ({ config, message }) => {
    const client = {
      listDocumentIds: vi.fn(),
      listPages: vi.fn(),
      retain: vi.fn(),
    } as unknown as HindsightClient;
    const core = new RuntimeCore(client, "bank-1", resolveConfig(config));
    const notify = vi.fn();
    const warning = vi.spyOn(log, "warn");
    core.setNotifier(notify);
    try {
      await expect(core.seedIfCold("/repos/one")).resolves.toBeUndefined();
      expect(warning).toHaveBeenCalledWith("opencode", expect.stringContaining(message));
      expect(notify).toHaveBeenCalledWith(
        "agentstratum configuration",
        expect.stringContaining(message)
      );
      expect(client.listDocumentIds).not.toHaveBeenCalled();
      expect(client.listPages).not.toHaveBeenCalled();
      expect(client.retain).not.toHaveBeenCalled();
    } finally {
      warning.mockRestore();
    }
  });

  it.each(["absent", "throws", "rejects"])(
    "survives an %s host notice channel while logging configuration guidance",
    async (channel) => {
      const client = { listDocumentIds: vi.fn() } as unknown as HindsightClient;
      const core = new RuntimeCore(client, "bank-1", resolveConfig({ apiUrl: "" }));
      if (channel === "throws") {
        core.setNotifier(() => {
          throw new Error("host notice unavailable");
        });
      } else if (channel === "rejects") {
        core.setNotifier(async () => {
          throw new Error("host notice unavailable");
        });
      }
      const warning = vi.spyOn(log, "warn");
      try {
        await expect(core.seedIfCold("/repos/one")).resolves.toBeUndefined();
        expect(warning).toHaveBeenCalledWith(
          "opencode",
          expect.stringContaining("AGENTSTRATUM_API_URL")
        );
        expect(client.listDocumentIds).not.toHaveBeenCalled();
      } finally {
        warning.mockRestore();
      }
    }
  );
});

/**
 * The plugin harnesses (opencode, kilo, cline, dsh, ...) register the tools through toolSpecs()
 * rather than the MCP server, so they hit the same #3590 bug: without these forwarded, every
 * agentstratum_reflect on those hosts aborts at the client's hardcoded 120s.
 */
describe("RuntimeCore reflect tool settings", () => {
  it("forwards the resolved reflect timeout and budget into agentstratum_reflect", async () => {
    const reflect = vi.fn(async () => "answer");
    const client = { reflect } as unknown as HindsightClient;
    const core = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({
        apiUrl: "https://service.example",
        reflectToolTimeoutMs: 660_000,
        reflectBudget: "mid",
      })
    );

    const tool = core.toolSpecs().find((spec) => spec.name === "agentstratum_reflect")!;
    await tool.handler({ query: "why?" });
    expect(reflect).toHaveBeenCalledWith("why?", { budget: "mid", timeoutMs: 660_000 });
  });
});

/**
 * dsh serves several repositories from ONE process, launched in a directory that is routinely not
 * the session's — so it constructs a core per workspace and passes that root. Every tool that
 * answers "what does this repo's memory look like" has to be bound to it: otherwise
 * `agentstratum_sync_status` runs its git checks in the launch directory and looks for THAT repo's
 * `gitlog:<name>` document in the SESSION's bank, reporting a seeded repo as unsynced.
 */
describe("RuntimeCore tool workspace binding", () => {
  const client = {
    listDocumentIds: vi.fn(async () => new Set<string>()),
    listPages: vi.fn(async () => ({ items: [] })),
    activeOperations: vi.fn(async () => 0),
  } as unknown as HindsightClient;

  const workspaceOf = async (core: RuntimeCore): Promise<string> => {
    const diagnose = core.toolSpecs().find((spec) => spec.name === "agentstratum_diagnose")!;
    return (JSON.parse((await diagnose.handler({})).content[0].text) as { workspace: string })
      .workspace;
  };

  it("binds the tools to the workspace the host opened, not the process cwd", async () => {
    const core = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" }),
      "dsh",
      "/repos/session-one"
    );
    expect(await workspaceOf(core)).toBe("/repos/session-one");
    expect(await workspaceOf(core)).not.toBe(process.cwd());
  });

  it("falls back to the process cwd for hosts whose process IS the project", async () => {
    const core = new RuntimeCore(
      client,
      "bank-1",
      resolveConfig({ apiUrl: "https://service.example" })
    );
    expect(await workspaceOf(core)).toBe(process.cwd());
  });
});
