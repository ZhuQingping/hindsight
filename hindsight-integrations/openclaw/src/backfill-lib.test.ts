import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { runCli } from "./backfill.js";
import {
  buildBackfillPlan,
  loadPluginConfigFromOpenClawRoot,
  stableDocumentId,
} from "./backfill-lib.js";

const tempDirs: string[] = [];

function makeTempRoot(): string {
  const dir = mkdtempSync(join(tmpdir(), "contextbase-openclaw-backfill-"));
  tempDirs.push(dir);
  return dir;
}

function writeOpenClawConfig(root: string, config: Record<string, unknown>) {
  writeFileSync(join(root, "openclaw.json"), JSON.stringify(config, null, 2));
}

function writeSession(
  root: string,
  agentId: string,
  fileName: string,
  lines: unknown[],
  archive = false
) {
  const dir = archive
    ? join(root, "agents", agentId, "sessions-archive-from-migration_backup")
    : join(root, "agents", agentId, "sessions");
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, fileName), lines.map((line) => JSON.stringify(line)).join("\n") + "\n");
}

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("backfill planning", () => {
  it("mirrors plugin bank routing from config by default", () => {
    const root = makeTempRoot();
    writeOpenClawConfig(root, {
      plugins: {
        entries: {
          "contextbase-openclaw": {
            config: {
              bankId: "team",
            },
          },
        },
      },
    });
    writeSession(root, "proj-run", "one.jsonl", [
      { type: "session", id: "session-1", sessionKey: "agent:proj-run:discord:channel:123" },
      { type: "message", message: { role: "user", content: "hello" } },
      { type: "message", message: { role: "assistant", content: "world" } },
    ]);

    const config = loadPluginConfigFromOpenClawRoot(root);
    const result = buildBackfillPlan(config, {
      openclawRoot: root,
      includeArchive: true,
      bankStrategy: "mirror-config",
    });

    expect(result.discoveredSessions).toBe(1);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].bankId).toBe("team");
    expect(result.entries[0].documentId).toBe(
      stableDocumentId(
        {
          filePath: result.entries[0].filePath,
          agentId: "proj-run",
          sessionId: "session-1",
          sessionKey: "agent:proj-run:discord:channel:123",
          messages: [],
        },
        result.entries[0].bankId
      )
    );
  });

  it("supports an explicitly configured backfill destination", () => {
    const root = makeTempRoot();
    writeOpenClawConfig(root, {
      plugins: { entries: { "contextbase-openclaw": { config: { bankId: "team" } } } },
    });
    writeSession(root, "proj-debug", "two.jsonl", [
      { type: "session", id: "session-2", sessionKey: "agent:proj-debug:discord:group:abc" },
      { type: "message", message: { role: "user", content: "hello" } },
      { type: "message", message: { role: "assistant", content: "world" } },
    ]);

    const config = loadPluginConfigFromOpenClawRoot(root);
    const result = buildBackfillPlan(config, {
      openclawRoot: root,
      includeArchive: true,
      bankStrategy: "fixed",
      fixedBank: "archive-bank",
    });

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].bankId).toBe("archive-bank");
  });

  it("can exclude archive sessions", () => {
    const root = makeTempRoot();
    writeOpenClawConfig(root, {
      plugins: { entries: { "contextbase-openclaw": { config: { bankId: "team" } } } },
    });
    writeSession(root, "main", "live.jsonl", [
      { type: "session", id: "live" },
      { type: "message", message: { role: "user", content: "live" } },
      { type: "message", message: { role: "assistant", content: "reply" } },
    ]);
    writeSession(
      root,
      "main",
      "archive.jsonl",
      [
        { type: "session", id: "archive" },
        { type: "message", message: { role: "user", content: "archived" } },
        { type: "message", message: { role: "assistant", content: "reply" } },
      ],
      true
    );

    const config = loadPluginConfigFromOpenClawRoot(root);
    const result = buildBackfillPlan(config, {
      openclawRoot: root,
      includeArchive: false,
      bankStrategy: "mirror-config",
    });

    expect(result.discoveredSessions).toBe(1);
    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].sessionId).toBe("live");
  });
});

it.each([200, 404])("backfill checks the configured Bank before retaining (%s)", async (status) => {
  const root = makeTempRoot();
  writeOpenClawConfig(root, {
    plugins: {
      entries: {
        "contextbase-openclaw": {
          config: {
            contextbaseApiUrl: "http://localhost:8888/customer",
            bankId: "team",
            bankMission: "Reflect.",
          },
        },
      },
    },
  });
  writeSession(root, "agent", "one.jsonl", [
    { type: "session", id: "session-1" },
    { type: "message", message: { role: "user", content: "Remember this." } },
  ]);
  const requests: string[] = [];
  const fetch = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
    const request = new Request(input, init);
    const path = new URL(request.url).pathname;
    requests.push(`${request.method} ${path}`);
    if (path.endsWith("/profile")) return Response.json({ detail: "Retired" }, { status: 410 });
    if (path.endsWith("/config"))
      return status === 404
        ? Response.json({ detail: "Bank not found" }, { status })
        : Response.json({ bank_id: "team", config: {}, overrides: {} });
    if (path.endsWith("/stats"))
      return Response.json({ pending_operations: 0, failed_operations: 0 });
    if (path.endsWith("/memories")) return Response.json({ success: true, operation_id: "op-1" });
    throw new Error(`Unexpected request: ${path}`);
  });
  const log = vi.spyOn(console, "log").mockImplementation(() => {});
  try {
    const result = runCli(["--openclaw-root", root, "--checkpoint", join(root, "checkpoint.json")]);
    if (status === 404) await expect(result).rejects.toThrow("Bank not found");
    else await result;
    const writes = requests.filter((request) => !request.startsWith("GET "));
    expect(writes).toEqual(
      status === 404
        ? []
        : [
            "PATCH /customer/v1/default/banks/team/config",
            "POST /customer/v1/default/banks/team/memories",
          ]
    );
    expect(requests).toContain("GET /customer/v1/default/banks/team/config");
  } finally {
    fetch.mockRestore();
    log.mockRestore();
  }
});
