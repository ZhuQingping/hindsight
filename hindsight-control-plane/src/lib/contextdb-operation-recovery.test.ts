// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  contextDBRequest,
  ContextDBError,
  workspaceMutation,
  workspaceIntents,
  saveWorkspaceIntent,
  replayWorkspaceIntent,
  waitForWorkspaceOperation,
} from "./contextdb-api";
const operation = (state: string) =>
  new Response(
    JSON.stringify({
      operation_id: "11111111111111111111111111111111",
      workspace_id: "22222222222222222222222222222222",
      state,
    })
  );
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  sessionStorage.clear();
});
describe("operation recovery and error contract", () => {
  it("refuses an expired uncertain write while preserving read-only operation recovery", async () => {
    const fetch = vi.fn().mockResolvedValue(operation("succeeded"));
    vi.stubGlobal("fetch", fetch);
    saveWorkspaceIntent({
      path: "/workspaces",
      method: "POST",
      idempotency_key: "old",
      raw_body: '{"name":"PG"}',
      created_at: Date.now() - 25 * 60 * 60 * 1000,
    });
    const intent = workspaceIntents()[0];
    await expect(replayWorkspaceIntent(intent)).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
    await waitForWorkspaceOperation("11111111111111111111111111111111");
    expect(fetch.mock.calls[0][1].method).toBe("GET");
  });
  it.each([400, 409])("does not retain a rejected first request (%s)", async (status) => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "name_conflict",
          message: "Workspace name already exists",
          request_id: "rejected",
        }),
        { status }
      )
    );
    vi.stubGlobal("fetch", fetch);
    await expect(
      workspaceMutation("/workspaces", "POST", "rejected", { name: "PG" })
    ).rejects.toMatchObject({ status });
    expect(workspaceIntents()).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("keeps a failed uncertain submission recoverable", async () => {
    const fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "unavailable",
          message: "Unavailable",
          request_id: "unknown",
        }),
        { status: 503 }
      )
    );
    vi.stubGlobal("fetch", fetch);
    await expect(
      workspaceMutation("/workspaces", "POST", "uncertain", { name: "PG" })
    ).rejects.toMatchObject({ status: 503 });
    expect(workspaceIntents()).toHaveLength(1);
  });
  it("persists original spelling before an unknown response without credentials", async () => {
    const fetch = vi.fn().mockRejectedValue(new Error("closed"));
    vi.stubGlobal("fetch", fetch);
    await expect(
      workspaceMutation("/workspaces", "POST", "original", {
        name: "  ＰＧ  ",
        description: "demo",
      })
    ).rejects.toThrow("Result unknown");
    expect(workspaceIntents()).toEqual([
      {
        path: "/workspaces",
        method: "POST",
        idempotency_key: "original",
        raw_body: '{"name":"  ＰＧ  ","description":"demo"}',
        created_at: expect.any(Number),
      },
    ]);
    expect(sessionStorage.getItem("contextdb-workspace-intents")).not.toMatch(
      /Bearer|secret|password/
    );
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("only queries a known failed operation until an explicit replay", async () => {
    vi.useFakeTimers();
    saveWorkspaceIntent({
      path: "/workspaces",
      method: "POST",
      idempotency_key: "original",
      raw_body: '{"name":"  ＰＧ  "}',
      operation_id: "11111111111111111111111111111111",
    });
    const fetch = vi.fn().mockResolvedValue(operation("failed"));
    vi.stubGlobal("fetch", fetch);
    const waiting = workspaceMutation("/workspaces", "POST", "original", { name: "  ＰＧ  " });
    const rejected = expect(waiting).rejects.toThrow("Workspace operation failed");
    await vi.advanceTimersByTimeAsync(1000);
    await rejected;
    expect(fetch.mock.calls[0][1].method).toBe("GET");
    expect(workspaceIntents()).toHaveLength(1);
    fetch.mockResolvedValueOnce(operation("succeeded"));
    await replayWorkspaceIntent(workspaceIntents()[0]);
    expect(fetch.mock.calls[1][1].method).toBe("POST");
    expect(fetch.mock.calls[1][1].headers.get("Idempotency-Key")).toBe("original");
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ name: "  ＰＧ  " });
    expect(workspaceIntents()).toHaveLength(0);
  });
  it("backs off 1/2/4/5 seconds and can stop without a server cancellation", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockImplementation(async () => operation("running"));
    vi.stubGlobal("fetch", fetch);
    const abort = new AbortController();
    const waiting = waitForWorkspaceOperation("11111111111111111111111111111111", abort.signal);
    const rejected = expect(waiting).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(999);
    expect(fetch).toHaveBeenCalledTimes(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetch).toHaveBeenCalledTimes(3);
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetch).toHaveBeenCalledTimes(4);
    abort.abort();
    await rejected;
    expect(fetch.mock.calls.every(([, options]) => options.method === "GET")).toBe(true);
  });
  it("does not reuse a saved request ID for a changed body", async () => {
    saveWorkspaceIntent({
      path: "/workspaces",
      method: "POST",
      idempotency_key: "original",
      raw_body: '{"name":"  ＰＧ  "}',
    });
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    await expect(
      workspaceMutation("/workspaces", "POST", "original", { name: "PG" })
    ).rejects.toThrow("same original request");
    expect(fetch).not.toHaveBeenCalled();
  });
  it("replays an uncertain delete with its original generation, never a newly fetched ETag", async () => {
    const etag = '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1"';
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new Error("closed"))
      .mockResolvedValueOnce(operation("succeeded"));
    vi.stubGlobal("fetch", fetch);
    await expect(
      workspaceMutation(
        "/workspaces/jiamu",
        "DELETE",
        "delete-original",
        undefined,
        undefined,
        etag
      )
    ).rejects.toThrow("Result unknown");
    expect(workspaceIntents()[0].etag).toBe(etag);
    await expect(
      workspaceMutation(
        "/workspaces/jiamu",
        "DELETE",
        "delete-original",
        undefined,
        undefined,
        '"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:1"'
      )
    ).rejects.toThrow("same original request");
    await replayWorkspaceIntent(workspaceIntents()[0]);
    expect(fetch.mock.calls.map(([, options]) => options.headers.get("If-Match"))).toEqual([
      etag,
      etag,
    ]);
    expect(fetch.mock.calls.map(([url]) => url)).toEqual([
      "/api/contextdb/workspaces/jiamu",
      "/api/contextdb/workspaces/jiamu",
    ]);
    expect(workspaceIntents()).toEqual([]);
  });
  it("restores generation-bound deletes for preserved UUID bank IDs", () => {
    const path = "/workspaces/11111111111111111111111111111111";
    const etag = '"22222222222222222222222222222222:1"';
    saveWorkspaceIntent({ path, method: "DELETE", idempotency_key: "legacy-delete", etag });
    expect(workspaceIntents()).toEqual([expect.objectContaining({ path, etag })]);
  });
  it("does not restore delete intents missing their generation precondition", () => {
    sessionStorage.setItem(
      "contextdb-workspace-intents",
      JSON.stringify([
        {
          path: "/workspaces/jiamu",
          method: "DELETE",
          idempotency_key: "old",
          created_at: Date.now(),
        },
      ])
    );
    expect(workspaceIntents()).toEqual([]);
  });
  it("preserves safe status/code/request ID for callers", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ code: "version_conflict", message: "stale", request_id: "trace-123" }),
            { status: 412 }
          )
        )
    );
    const error = await contextDBRequest("/users/example").catch((error: unknown) => error);
    expect(error).toBeInstanceOf(ContextDBError);
    expect(error).toMatchObject({ status: 412, code: "version_conflict", request_id: "trace-123" });
  });
});
