import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@/lib/contextbase-client", () => ({
  DATAPLANE_URL: "http://dataplane",
  dataplaneBankUrl: (bank: string, suffix: string) =>
    `http://dataplane/v1/default/banks/${encodeURIComponent(bank)}${suffix}`,
  getDataplaneHeaders: () => ({ Authorization: "Bearer server-only-fixture" }),
}));
import { GET } from "@/app/api/documents/transfer/route";
const upstream = vi.fn();
beforeEach(() => {
  upstream.mockReset();
  vi.stubGlobal("fetch", upstream);
});
afterEach(() => {
  vi.unstubAllGlobals();
});

it("downloads a completed S3 export through native storage_key and streams bytes", async () => {
  upstream.mockResolvedValueOnce(Response.json({ operation_id: "op-export" }));
  upstream.mockResolvedValueOnce(
    Response.json({
      status: "completed",
      result_metadata: {
        storage_key: "tenants/public/banks/team%2Fone/exports/file.zip",
        download_url: "https://private-store.invalid/bucket/signed?credential=private",
      },
    })
  );
  let finish!: () => void;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array([80, 75, 3, 4]));
      finish = () => {
        controller.enqueue(new Uint8Array([0, 255]));
        controller.close();
      };
    },
  });
  upstream.mockResolvedValueOnce(
    new Response(stream, { headers: { "content-type": "application/zip" } })
  );
  const request = new NextRequest("http://ui/api/documents/transfer?bank_id=team%2Fone");
  const response = await GET(request);
  // GET must return before the upstream finishes, not wait for arrayBuffer().
  expect(response.status).toBe(200);
  expect(upstream.mock.calls[2]).toEqual([
    "http://dataplane/v1/default/files/download/tenants/public/banks/team%252Fone/exports/file.zip",
    { headers: { Authorization: "Bearer server-only-fixture" }, signal: request.signal },
  ]);
  finish();
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(
    new Uint8Array([80, 75, 3, 4, 0, 255])
  );
});

it("never sends the instance credential to an absolute URL without a native key", async () => {
  upstream.mockResolvedValueOnce(Response.json({ operation_id: "op-export" }));
  upstream.mockResolvedValueOnce(
    Response.json({
      status: "completed",
      result_metadata: { download_url: "https://untrusted.invalid/steal" },
    })
  );
  expect((await GET(new NextRequest("http://ui/api/documents/transfer?bank_id=one"))).status).toBe(
    500
  );
  expect(upstream).toHaveBeenCalledTimes(2);
});
