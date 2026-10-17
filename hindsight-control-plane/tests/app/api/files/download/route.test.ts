import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
vi.mock("@/lib/hindsight-client", () => ({
  DATAPLANE_URL: "http://dataplane",
  getDataplaneHeaders: () => ({ Authorization: "Bearer fixture-service-key" }),
}));
import { GET } from "@/app/api/files/download/route";
afterEach(() => vi.unstubAllGlobals());

it("rejects traversal before any privileged upstream request", async () => {
  const upstream = vi.fn();
  vi.stubGlobal("fetch", upstream);
  const path = "/v1/default/files/download/%2e%2e/banks";
  const response = await GET(
    new NextRequest("http://ui/api/files/download?path=" + encodeURIComponent(path))
  );
  expect(response.status).toBe(400);
  expect(upstream).not.toHaveBeenCalled();
});

it("passes a native download stream and propagates cancellation", async () => {
  let close!: () => void;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new Uint8Array([1, 2]));
      close = () => controller.close();
    },
  });
  const upstream = vi.fn().mockResolvedValue(new Response(stream));
  vi.stubGlobal("fetch", upstream);
  const path = "/v1/default/files/download/tenants/public/file.bin";
  const request = new NextRequest("http://ui/api/files/download?path=" + encodeURIComponent(path));
  const response = await GET(request);
  expect(response.status).toBe(200);
  expect(upstream.mock.calls[0][1].signal).toBe(request.signal);
  close();
  expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([1, 2]));
});
