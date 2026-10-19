import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/lib/hindsight-client", () => ({
  DATAPLANE_URL: "http://dataplane",
  getDataplaneHeaders: () => ({ Authorization: "Bearer fixture-service-key" }),
}));
import { GET } from "@/app/api/files/download/route";
afterEach(() => vi.unstubAllGlobals());

it("preserves customer filenames and file bytes containing the upstream brand", async () => {
  const content = "customer hindsight HINDSIGHT bytes";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(content, {
        headers: { "content-disposition": 'attachment; filename="hindsight.txt"' },
      })
    )
  );
  const response = await GET(
    new NextRequest(
      "http://ui/api/files/download?path=" +
        encodeURIComponent("/v1/default/files/download/tenants/public/hindsight.txt")
    )
  );
  expect(response.headers.get("content-disposition")).toContain("hindsight.txt");
  await expect(response.text()).resolves.toBe(content);
});

it("preserves download rejection details and upstream status", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        Response.json({ detail: "Access denied to file hindsight.txt" }, { status: 403 })
      )
  );
  const response = await GET(
    new NextRequest(
      "http://ui/api/files/download?path=" +
        encodeURIComponent("/v1/default/files/download/tenants/public/file.txt")
    )
  );
  expect(response.status).toBe(403);
  await expect(response.json()).resolves.toEqual({ detail: "Access denied to file hindsight.txt" });
});
