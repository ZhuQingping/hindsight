import { afterEach, describe, expect, it, vi } from "vitest";
import { ContextDBError, createContextDBBank, deleteContextDBBank } from "@/lib/contextdb-api";
afterEach(() => vi.unstubAllGlobals());
const workspace = {
  workspace_id: "a".repeat(32),
  bank_id: "mysql",
  state: "active",
  version: 1,
  etag: `"${"a".repeat(32)}:1"`,
  name: "mysql",
  description: "Demo",
  created_at: "2026-10-20T00:00:00Z",
};
const profile = {
  bank_id: "mysql",
  name: "mysql",
  mission: "",
  disposition: { skepticism: 3, literalism: 3, empathy: 3 },
};
const success = () =>
  new Response(JSON.stringify(profile), {
    status: 200,
    headers: { "X-ContextDB-Workspace-ETag": workspace.etag },
  });

describe("Bank lifecycle client", () => {
  it("strictly creates once, then verifies the original identity with one GET", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(success())
      .mockResolvedValueOnce(new Response(JSON.stringify(workspace)));
    vi.stubGlobal("fetch", fetchMock);
    expect(await createContextDBBank({ name: "  MySQL  ", description: "Demo" })).toEqual(
      workspace
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/banks/mysql");
    expect(options.method).toBe("PUT");
    expect(options.headers.get("If-None-Match")).toBe("*");
    expect(options.headers.has("Idempotency-Key")).toBe(false);
    expect(JSON.parse(options.body)).toEqual({ name: "mysql", description: "Demo" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/contextdb/workspaces/mysql");
    expect(fetchMock.mock.calls[1][1].method).toBe("GET");
  });
  it("validates a native deletion response and forwards only the confirmed condition", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ success: true, message: "Deleted", deleted_count: 3 }))
      );
    vi.stubGlobal("fetch", fetchMock);
    expect(await deleteContextDBBank("mysql", workspace.etag)).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/banks/mysql");
    expect(fetchMock.mock.calls[0][1].headers.get("If-Match")).toBe(workspace.etag);
  });
  it.each([undefined, '"1"', '"*:1"'])("rejects unbound deletion condition %s", (etag) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    expect(() => deleteContextDBBank("mysql", etag as string)).toThrow(
      "original identity-bound ETag"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it.each([0, 503])("does not retry an uncertain write (%s)", async (status) => {
    const mock = status
      ? vi.fn().mockResolvedValue(new Response("{}", { status }))
      : vi.fn().mockRejectedValue(new TypeError("Disconnected"));
    vi.stubGlobal("fetch", mock);
    await expect(createContextDBBank({ name: "mysql" })).rejects.toThrow("Result unknown");
    expect(mock).toHaveBeenCalledTimes(1);
  });
  it.each([null, '"1"', `"${"b".repeat(32)}:1"`])(
    "rejects missing, malformed or successor identity (%s)",
    async (etag) => {
      const put = etag === null ? new Response(JSON.stringify(profile)) : success();
      const observed = { ...workspace, etag, description: "" };
      const mock = vi
        .fn()
        .mockResolvedValueOnce(put)
        .mockResolvedValueOnce(new Response(JSON.stringify(observed)));
      vi.stubGlobal("fetch", mock);
      await expect(createContextDBBank({ name: "mysql" })).rejects.toMatchObject({
        code: "response_unknown",
        status: 0,
      });
      expect(mock.mock.calls.filter(([, options]) => options.method !== "GET")).toHaveLength(1);
    }
  );
  it.each([false, null, {}, { success: true, message: "Deleted", deleted_count: -1 }])(
    "does not accept a malformed deletion success: %j",
    async (body) => {
      const mock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body)));
      vi.stubGlobal("fetch", mock);
      await expect(deleteContextDBBank("mysql", workspace.etag)).rejects.toMatchObject({
        code: "response_unknown",
      });
      expect(mock).toHaveBeenCalledTimes(1);
    }
  );
  it("does not retarget or replay a stale delete", async () => {
    const mock = vi
      .fn()
      .mockResolvedValue(new Response('{"code":"precondition_failed"}', { status: 412 }));
    vi.stubGlobal("fetch", mock);
    const error = await deleteContextDBBank("mysql", workspace.etag).catch((error) => error);
    expect(error).toBeInstanceOf(ContextDBError);
    expect(error.status).toBe(412);
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock.mock.calls[0][1].headers.get("If-Match")).toBe(workspace.etag);
  });
  it("reports a strict creation name conflict without reading or replaying", async () => {
    const mock = vi.fn().mockResolvedValue(
      new Response('{"code":"precondition_failed","detail":"Bank is already registered"}', {
        status: 412,
        headers: { "X-Request-ID": "create-conflict" },
      })
    );
    vi.stubGlobal("fetch", mock);
    await expect(createContextDBBank({ name: "mysql" })).rejects.toMatchObject({
      status: 412,
      code: "precondition_failed",
      request_id: "create-conflict",
      message: "A workspace with this name already exists. Choose another name.",
    });
    expect(mock).toHaveBeenCalledTimes(1);
    expect(mock.mock.calls[0][1].method).toBe("PUT");
  });
  it.each([
    { ...workspace, workspace_id: "b".repeat(32), etag: `"${"b".repeat(32)}:1"` },
    { ...workspace, version: 2, etag: `"${"a".repeat(32)}:2"` },
  ])("rejects a self-consistent successor identity or version: %j", async (observed) => {
    const mock = vi
      .fn()
      .mockResolvedValueOnce(success())
      .mockResolvedValueOnce(new Response(JSON.stringify(observed)));
    vi.stubGlobal("fetch", mock);
    await expect(createContextDBBank({ name: "mysql", description: "Demo" })).rejects.toMatchObject(
      {
        code: "response_unknown",
        status: 0,
      }
    );
    expect(mock).toHaveBeenCalledTimes(2);
    expect(mock.mock.calls.map(([, options]) => options.method)).toEqual(["PUT", "GET"]);
  });
});
