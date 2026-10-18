import { afterEach, describe, expect, it, vi } from "vitest";
import { ContextDBError, workspaceMutation } from "@/lib/contextdb-api";
afterEach(() => vi.unstubAllGlobals());
const workspace = {
  workspace_id: "a".repeat(32),
  bank_id: "mysql",
  state: "active",
  version: 1,
  etag: `"${"a".repeat(32)}:1"`,
  name: "mysql",
  description: "",
  created_at: "2026-10-20T00:00:00Z",
};
const etag = `"${workspace.workspace_id}:1"`;

describe("synchronous workspace lifecycle client", () => {
  it("returns the created resource with one POST and no idempotency or operation request", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(workspace), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(
      await workspaceMutation("/workspaces", "POST", { name: "MySQL", description: "Demo" })
    ).toEqual(workspace);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/contextdb/workspaces");
    expect(options.method).toBe("POST");
    expect(options.headers.has("Idempotency-Key")).toBe(false);
    expect(JSON.parse(options.body)).toEqual({ name: "MySQL", description: "Demo" });
  });
  it("accepts 204 deletion and sends the original identity-bound ETag", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(
      await workspaceMutation("/workspaces/mysql", "DELETE", undefined, undefined, etag)
    ).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1].headers.get("If-Match")).toBe(etag);
    expect(fetchMock.mock.calls[0][1].headers.has("Idempotency-Key")).toBe(false);
  });
  it.each([undefined, '"1"', '"*:1"'])(
    "rejects deletion without a bound identity %s before sending",
    (invalid) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      expect(() =>
        workspaceMutation("/workspaces/mysql", "DELETE", undefined, undefined, invalid)
      ).toThrow("original identity-bound ETag");
      expect(fetchMock).not.toHaveBeenCalled();
    }
  );
  it.each([0, 503])(
    "reports uncertain writes without retry or rollback claims (%s)",
    async (status) => {
      const fetchMock = status
        ? vi.fn().mockResolvedValue(new Response('{"message":"Unavailable"}', { status }))
        : vi.fn().mockRejectedValue(new TypeError("Disconnected"));
      vi.stubGlobal("fetch", fetchMock);
      await expect(workspaceMutation("/workspaces", "POST", { name: "mysql" })).rejects.toThrow(
        "Result unknown"
      );
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  );
  it("treats a lost or malformed success body as unknown, without replay", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("truncated", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(workspaceMutation("/workspaces", "POST", { name: "mysql" })).rejects.toMatchObject(
      { code: "response_unknown", status: 0, message: expect.stringContaining("Result unknown") }
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("does not retarget or retry an old DELETE when the same name identifies a successor", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response('{"code":"version_conflict","message":"stale"}', { status: 412 })
      );
    vi.stubGlobal("fetch", fetchMock);
    const error = await workspaceMutation(
      "/workspaces/mysql",
      "DELETE",
      undefined,
      undefined,
      etag
    ).catch((error) => error);
    expect(error).toBeInstanceOf(ContextDBError);
    expect(error.status).toBe(412);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1].headers.get("If-Match")).toBe(etag);
  });
});
