import { createServer } from "node:http";
import { afterEach, describe, expect, it } from "vitest";
import { HindsightClient } from "./hindsight";
import { retainLiveSession, type TransportTurn } from "./chat";
import { memoryCursorStore } from "./retain-cursor";
import { buildRetain } from "./retain-hook";
import { memoryUsageCursorStore } from "./usage";

const turn = (content: string): TransportTurn => ({ role: "user", content });
const startTs = "2026-01-01T00:00:00Z";
const close: Array<() => Promise<void>> = [];
afterEach(async () => {
  for (const stop of close.splice(0)) await stop();
});

/** Real integration HTTP client against a deterministic async-operation service. Like the API's
 *  _resolve_retain_replay, duplicate ids acknowledge the existing job even when it failed. */
async function service() {
  const operations = new Map<string, "completed" | "failed">();
  const requests: Array<{ id: string; content: string; append: boolean }> = [];
  let document: TransportTurn[] = [];
  let failures = 0;
  let loseReply = false;
  const server = createServer(async (req, res) => {
    res.setHeader("Content-Type", "application/json");
    if (req.url === "/v1/version") return res.end(JSON.stringify({ api_version: "1.0.0" }));
    if (req.url?.endsWith("/config")) {
      return res.end(JSON.stringify({ config: { store_document_text: true } }));
    }
    if (req.method === "GET" && req.url?.includes("/operations/")) {
      const status = operations.get(req.url.split("/").at(-1)!);
      res.statusCode = status ? 200 : 404;
      return res.end(JSON.stringify({ status }));
    }
    if (req.method !== "POST" || !req.url?.endsWith("/memories")) {
      res.statusCode = 404;
      return res.end("{}");
    }
    let body = "";
    for await (const chunk of req) body += chunk;
    const payload = JSON.parse(body) as {
      operation_id: string;
      items: Array<{ content: string; update_mode?: string }>;
    };
    const id = payload.operation_id;
    const item = payload.items[0];
    const append = item.update_mode === "append";
    requests.push({ id, content: item.content, append });
    if (!operations.has(id)) {
      if (failures > 0) {
        failures--;
        operations.set(id, "failed");
      } else {
        const turns = item.content.split("\n").map((line) => JSON.parse(line) as TransportTurn);
        document = append ? [...document, ...turns] : turns;
        operations.set(id, "completed");
      }
    }
    if (loseReply) {
      loseReply = false;
      return req.socket.destroy();
    }
    res.end(JSON.stringify({ operation_id: id }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  close.push(() => new Promise<void>((resolve) => server.close(() => resolve())));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing test server address");
  const client = new HindsightClient({ apiUrl: `http://127.0.0.1:${address.port}`, bank: "test" });
  let cursors = memoryCursorStore();
  const files = new Map<string, TransportTurn[]>();
  const write = async (turns: TransportTurn[], path?: string, viaHook = false) => {
    if (path) files.set(path, turns);
    if (viaHook && path) {
      return buildRetain({
        harness: "codex",
        sessionId: "session",
        transcriptPath: path,
        client,
        cursors,
        readTranscript: (p) => files.get(p) ?? [],
        usageCursors: memoryUsageCursorStore(),
      });
    }
    await retainLiveSession(client, "session", turns, startTs, "codex", {
      cursors,
      transcriptPath: path,
      readTranscript: (p) => files.get(p) ?? [],
    });
  };
  return {
    write,
    requests,
    operations,
    files,
    restart: () => {
      const saved = JSON.stringify(cursors.read("session"));
      cursors = memoryCursorStore();
      cursors.write("session", JSON.parse(saved));
    },
    fail: (count = 1) => {
      failures = count;
    },
    loseNextReply: () => {
      loseReply = true;
    },
    contents: () => document.filter((t) => t.role !== "system"),
  };
}

describe("session recovery through the HTTP client", () => {
  it("uses the host transcript reader on the actual Stop-hook path", async () => {
    const s = await service();
    await s.write([turn("A")], "/a", true);
    s.fail();
    await s.write([turn("B")], "/b", true);
    await s.write([turn("B"), turn("C")], "/b", true);
    expect(s.contents()).toEqual([turn("A"), turn("B"), turn("C")]);
  });

  it("preserves earlier continuation segments and continues appending after recovery", async () => {
    const s = await service();
    await s.write([turn("A")], "/a");
    await s.write([turn("B")], "/b");
    s.fail();
    await s.write([turn("B"), turn("C")], "/b");
    await s.write([turn("B"), turn("C"), turn("D")], "/b");
    expect(s.contents()).toEqual([turn("A"), turn("B"), turn("C"), turn("D")]);
    expect(s.requests.at(-1)?.append).toBe(false);
    await s.write([turn("B"), turn("C"), turn("D"), turn("E")], "/b");
    expect(s.requests.at(-1)?.append).toBe(true);
    expect(s.contents()).toEqual([turn("A"), turn("B"), turn("C"), turn("D"), turn("E")]);
  });

  it("retains exact source slices when a continuation copies an earlier prefix", async () => {
    const s = await service();
    await s.write([turn("A")], "/a");
    await s.write([turn("A"), turn("B")], "/b");
    s.fail();
    await s.write([turn("C")], "/c");
    await s.write([turn("C"), turn("D")], "/c");
    expect(s.contents()).toEqual([turn("A"), turn("B"), turn("C"), turn("D")]);
  });

  it("does not lose sources when the bounded path-routing cache evicts old paths", async () => {
    const s = await service();
    for (let i = 0; i < 18; i++) await s.write([turn(String(i))], `/${i}`);
    s.fail();
    await s.write([turn("17"), turn("18")], "/17");
    await s.write([turn("17"), turn("18")], "/17");
    expect(s.contents()).toEqual(Array.from({ length: 19 }, (_, i) => turn(String(i))));
  });

  it.each(["missing", "rewritten"])(
    "refuses a destructive replacement when an old source is %s",
    async (damage) => {
      const s = await service();
      await s.write([turn("A")], "/a");
      await s.write([turn("B")], "/b");
      s.fail();
      await s.write([turn("B"), turn("C")], "/b");
      if (damage === "missing") s.files.delete("/a");
      else s.files.set("/a", [turn("rewritten")]);
      await expect(s.write([turn("B"), turn("C")], "/b")).rejects.toThrow("unavailable or changed");
      expect(s.requests).toHaveLength(3);
      expect(s.contents()).toEqual([turn("A"), turn("B")]);
      s.files.set("/a", [turn("A")]);
      await s.write([turn("B"), turn("C")], "/b");
      expect(s.contents()).toEqual([turn("A"), turn("B"), turn("C")]);
    }
  );

  it("creates a new operation for every confirmed failure even with identical content", async () => {
    const s = await service();
    s.fail(2);
    for (let i = 0; i < 3; i++) await s.write([turn("unchanged")]);
    expect(new Set(s.requests.map((r) => r.id)).size).toBe(3);
    expect([...s.operations.values()]).toEqual(["failed", "failed", "completed"]);
    expect(s.contents()).toEqual([turn("unchanged")]);
  });

  it("reuses a recovery id after a lost acknowledgement and keeps every segment", async () => {
    const s = await service();
    await s.write([turn("A")], "/a");
    s.fail();
    await s.write([turn("B")], "/b");
    s.loseNextReply();
    await expect(s.write([turn("B")], "/b")).rejects.toThrow();
    s.restart(); // a new Stop process reads the persisted source slices and recovery identity
    await s.write([turn("B")], "/b");
    expect(s.requests.at(-1)?.id).toBe(s.requests.at(-2)?.id);
    expect(s.operations.size).toBe(3);
    expect(s.contents()).toEqual([turn("A"), turn("B")]);
  });
});
