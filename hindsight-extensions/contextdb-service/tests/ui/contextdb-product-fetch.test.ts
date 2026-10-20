// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { contextDBRequest } from "@/lib/contextdb-api";

afterEach(() => {
  delete document.documentElement.dataset.contextdbName;
  vi.unstubAllGlobals();
});
it("binds management requests to the product identity rendered in the current tab", async () => {
  document.documentElement.dataset.contextdbName = "ContextBase";
  const upstream = vi.fn().mockResolvedValue(new Response('{"items":[]}'));
  vi.stubGlobal("fetch", upstream);
  await contextDBRequest("/users");
  expect(upstream).toHaveBeenCalledOnce();
  expect(upstream.mock.calls[0][1].headers.get("X-Product-Name")).toBe("ContextBase");
  expect(upstream.mock.calls[0][1].headers.has("Authorization")).toBe(false);
});
