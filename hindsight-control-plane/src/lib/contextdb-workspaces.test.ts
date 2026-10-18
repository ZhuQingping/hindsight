import { afterEach, describe, expect, it, vi } from "vitest";
import { managementRequestId, workspaceMutation } from "./contextdb-api";
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
describe("workspace lifecycle client", () => {
  it("creates request IDs without requiring a secure browser context", () => {
    expect(managementRequestId()).toMatch(/^[0-9a-f]{32}$/);
    expect(managementRequestId()).not.toBe(managementRequestId());
  });
  it("waits for completion and never creates a native bank", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ operation_id: "op", workspace_id: "space", state: "pending" })
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ operation_id: "op", workspace_id: "space", state: "succeeded" })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    const result = workspaceMutation("/workspaces", "POST", "stable-request", { name: "MySQL" });
    await vi.advanceTimersByTimeAsync(1000);
    expect((await result).workspace_id).toBe("space");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/contextdb/workspaces");
    expect(fetchMock.mock.calls[0][1].headers.get("idempotency-key")).toBe("stable-request");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/contextdb/operations/op");
  });
  it("keeps the caller's request ID when retrying an unknown response", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("connection closed"))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ operation_id: "op", workspace_id: "space", state: "succeeded" })
        )
      );
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      workspaceMutation("/workspaces", "POST", "same-id", { name: "PG" })
    ).rejects.toThrow("Result unknown");
    await workspaceMutation("/workspaces", "POST", "same-id", { name: "PG" });
    expect(
      fetchMock.mock.calls.map(([, options]) => options.headers.get("idempotency-key"))
    ).toEqual(["same-id", "same-id"]);
  });
  it("reports failures rather than treating accepted deletion as completion", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            operation_id: "op",
            workspace_id: "space",
            state: "failed",
            error_code: "busy",
          })
        )
      )
    );
    await expect(
      workspaceMutation(
        "/workspaces/space",
        "DELETE",
        "delete-id",
        undefined,
        undefined,
        '"11111111111111111111111111111111:1"'
      )
    ).rejects.toThrow("busy");
  });
});
