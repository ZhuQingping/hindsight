import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ContextDBError,
  contextDBRequest,
  createContextDBKey,
  createContextDBUser,
  workspaceMutation,
} from "@/lib/contextdb-api";
const userId = "b".repeat(32);
const workspaceId = "a".repeat(32);
const workspace = {
  workspace_id: workspaceId,
  bank_id: "mysql",
  etag: `"${workspaceId}:1"`,
  name: "mysql",
  description: "",
  state: "active",
  version: 1,
  created_at: "2026-10-20T00:00:00Z",
};
const issued = {
  key_id: "c".repeat(32),
  user_id: userId,
  name: "Agent",
  authorization: { mode: "all", permission: "read_write" },
  display_key: null,
  version: 1,
  created_at: "2026-10-20T00:00:00Z",
  secret: "synthetic-one-time-secret",
};
const keyInput = {
  name: "Agent",
  authorization: { mode: "all", permission: "read_write" },
} as const;
function respond(body: string, status: number) {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(body, { status, headers: { "X-Request-ID": "from-header" } }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
afterEach(() => vi.unstubAllGlobals());
describe("management response boundaries", () => {
  it.each(["null", "[]", '"text"', "1", "true", "{}", "<html>unavailable</html>", '{"truncated"'])(
    "keeps malformed 503 error as an uncertain write: %s",
    async (body) => {
      const fetchMock = respond(body, 503);
      await expect(
        contextDBRequest("/workspaces", { method: "POST", body: { name: "mysql" } })
      ).rejects.toMatchObject({
        name: "ContextDBError",
        status: 503,
        code: "request_failed",
        request_id: "from-header",
        message: expect.stringContaining("Result unknown"),
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  );
  it.each([400, 412])(
    "preserves a definite HTTP error even with JSON null (%s)",
    async (status) => {
      const fetchMock = respond("null", status);
      const error = await contextDBRequest("/users", { method: "PATCH", body: {} }).catch((e) => e);
      expect(error).toBeInstanceOf(ContextDBError);
      if (!(error instanceof ContextDBError)) throw error;
      expect(error.status).toBe(status);
      expect(error.message).not.toContain("Result unknown");
      expect(error.message).toContain(status === 412 ? "This record changed" : "400");
      expect(fetchMock).toHaveBeenCalledTimes(1);
    }
  );
  it("uses only string error fields and falls back to the response request ID", async () => {
    respond('{"message":{},"error":[],"code":4,"request_id":null}', 400);
    await expect(contextDBRequest("/users")).rejects.toMatchObject({
      code: "request_failed",
      request_id: "from-header",
      message: "Request failed (400)",
    });
    respond('{"message":"safe message","code":"safe_code","request_id":"from-body"}', 409);
    await expect(contextDBRequest("/users")).rejects.toMatchObject({
      code: "safe_code",
      request_id: "from-body",
      message: "safe message",
    });
  });
  it.each([
    null,
    {},
    [[]],
    "text",
    { ...workspace, bank_id: "other" },
    { ...workspace, workspace_id: "invalid" },
    { ...workspace, etag: undefined },
    { ...workspace, etag: `"${"d".repeat(32)}:1"` },
    { ...workspace, version: 2 },
    { ...workspace, state: "creating" },
  ])("rejects workspace creation without submitted identity and active ETag: %j", async (body) => {
    const fetchMock = respond(JSON.stringify(body), 201);
    await expect(workspaceMutation("/workspaces", "POST", { name: "MySQL" })).rejects.toMatchObject(
      { code: "response_unknown", status: 0, request_id: "from-header" }
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("accepts the normalized workspace target with the original identity-bound ETag", async () => {
    const fetchMock = respond(JSON.stringify(workspace), 201);
    expect(await workspaceMutation("/workspaces", "POST", { name: "  MySQL  " })).toEqual(
      workspace
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("validates against the submitted workspace name, not a later draft mutation", async () => {
    let finish!: (response: Response) => void;
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        })
    );
    vi.stubGlobal("fetch", fetchMock);
    const body = { name: "mysql" };
    const pending = workspaceMutation("/workspaces", "POST", body);
    body.name = "other";
    finish(new Response(JSON.stringify(workspace), { status: 201 }));
    expect(await pending).toEqual(workspace);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([200, 202, 204])("rejects another workspace success status (%s)", async (status) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(status === 204 ? null : JSON.stringify(workspace), { status })
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(workspaceMutation("/workspaces", "POST", { name: "mysql" })).rejects.toMatchObject(
      { code: "response_unknown", status: 0 }
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([
    null,
    {},
    [[]],
    { ...issued, secret: undefined },
    { ...issued, secret: "" },
    { ...issued, secret: 1 },
    { ...issued, user_id: "d".repeat(32) },
    { ...issued, key_id: "invalid" },
  ])("rejects an incomplete or wrong-target issued Key: %j", async (body) => {
    const fetchMock = respond(JSON.stringify(body), 201);
    await expect(createContextDBKey(userId, keyInput)).rejects.toMatchObject({
      code: "response_unknown",
      status: 0,
      request_id: "from-header",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("returns the one-time secret only from a valid 201 Key creation", async () => {
    const fetchMock = respond(JSON.stringify(issued), 201);
    expect(await createContextDBKey(userId, keyInput)).toEqual(issued);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/contextdb/users/${userId}/keys`);
  });
  it.each([200, 202, 204])("rejects another Key creation success status (%s)", async (status) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(status === 204 ? null : JSON.stringify(issued), { status }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createContextDBKey(userId, keyInput)).rejects.toMatchObject({
      code: "response_unknown",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("keeps PATCH without secret and DELETE with an empty 204 valid", async () => {
    const editable = { key_id: issued.key_id, user_id: userId, name: "Agent" };
    const fetchMock = respond(JSON.stringify(editable), 200);
    expect(
      await contextDBRequest(`/users/${userId}/keys/${issued.key_id}`, {
        method: "PATCH",
        version: 1,
        body: { name: "Agent" },
      })
    ).toEqual(editable);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const deleteMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", deleteMock);
    expect(
      await contextDBRequest(`/users/${userId}/keys/${issued.key_id}`, { method: "DELETE" })
    ).toBeUndefined();
    expect(deleteMock).toHaveBeenCalledTimes(1);
  });
});

describe("member creation response identity", () => {
  const member = {
    user_id: "d".repeat(32),
    name: "Alice",
    status: "active",
    version: 1,
    created_at: "2026-10-21T00:00:00Z",
  };
  it.each([
    null,
    {},
    [],
    { ...member, user_id: "invalid" },
    { ...member, name: "Someone else" },
    { ...member, status: "disabled" },
    { ...member, version: 0 },
    { ...member, created_at: "not-a-date" },
  ])("keeps damaged success as unknown without replay: %j", async (body) => {
    const fetchMock = respond(JSON.stringify(body), 201);
    await expect(createContextDBUser({ name: "Alice" })).rejects.toMatchObject({
      code: "response_unknown",
      status: 0,
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([200, 202, 204])("does not accept a different creation status %s", async (status) => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(status === 204 ? null : JSON.stringify(member), { status }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(createContextDBUser({ name: "Alice" })).rejects.toMatchObject({
      code: "response_unknown",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it.each([
    ["\u0085Alice\u0085", "Alice"],
    ["\u001cAlice\u001f", "Alice"],
    ["\ufeffAlice\ufeff", "\ufeffAlice\ufeff"],
  ])("matches backend name normalization for %j", async (name, expected) => {
    const created = { ...member, name: expected };
    const fetchMock = respond(JSON.stringify(created), 201);
    expect(await createContextDBUser({ name })).toEqual(created);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
  it("accepts the submitted normalized name and preserves a request snapshot", async () => {
    let finish!: (value: Response) => void;
    const fetchMock = vi.fn().mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        })
    );
    vi.stubGlobal("fetch", fetchMock);
    const body = { name: " Ａlice " };
    const pending = createContextDBUser(body);
    body.name = "Different";
    finish(new Response(JSON.stringify(member), { status: 201 }));
    expect(await pending).toEqual(member);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
