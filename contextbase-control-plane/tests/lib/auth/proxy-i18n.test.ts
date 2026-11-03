vi.mock("server-only", () => ({}));
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";

let directory: string;
beforeEach(async () => {
  vi.stubEnv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "false");
  directory = await mkdtemp(path.join(os.tmpdir(), "m2-i18n-"));
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", directory);
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "test-login-password");
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://127.0.0.1:28901");
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
  // Set by the documented skipProxyUrlNormalize Next configuration in builds.
  vi.stubEnv("__NEXT_NO_MIDDLEWARE_URL_NORMALIZE", "true");
});
afterEach(async () => {
  vi.unstubAllEnvs();
  await rm(directory, { recursive: true, force: true });
});
function request(pathname: string, host = "127.0.0.1:28901") {
  return new NextRequest("http://127.0.0.1:28901" + pathname, {
    headers: { host, "accept-language": "zh-CN" },
  });
}
it("keeps the actual next-intl login rewrite on the original internal host", async () => {
  const response = await proxy(request("/login"));
  expect(response.status).toBe(200);
  expect(response.headers.get("x-middleware-rewrite")).toBe("http://127.0.0.1:28901/zh-CN/login");
});
it("redirects an unauthenticated gateway request to its configured HTTPS public origin", async () => {
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "https://127.0.0.1:28904");
  const response = await proxy(request("/dashboard", "127.0.0.1:28904"));
  expect(response.status).toBe(307);
  expect(response.headers.get("location")).toBe(
    "https://127.0.0.1:28904/login?returnTo=%2Fdashboard"
  );
});
it("keeps the selected bank when login follows a direct connection link", async () => {
  const response = await proxy(request("/connect?bank_id=team%2Fmemory"));
  expect(response.status).toBe(307);
  expect(new URL(response.headers.get("location")!).searchParams.get("returnTo")).toBe(
    "/connect?bank_id=team%2Fmemory"
  );
});
it("still rejects an alternate external Host before language routing", async () => {
  expect((await proxy(request("/login", "localhost:28901"))).status).toBe(421);
});
