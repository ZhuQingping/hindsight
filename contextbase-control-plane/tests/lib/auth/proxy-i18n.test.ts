vi.mock("server-only", () => ({}));
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import { resolveApiErrorLocale } from "@/lib/i18n/api-errors";

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

it.each([
  ["en", "zh-CN", "en"],
  ["zh-CN", "en-US", "zh-CN"],
  ["ja", "zh-CN, en;q=0.8", "zh-CN"],
  ["zh-TW", "en-US", "en"],
  ["yue-Hant", "ja", "en"],
  ["", "zh-SG", "zh-CN"],
  ["", "de, en-GB;q=0.8", "en"],
  ["", "ja", "en"],
  ["", "yue-Hant", "zh-CN"],
  ["", "yue-HK", "zh-CN"],
  ["", "zh-TW", "zh-CN"],
  ["", "zh-TW,en;q=0.8", "en"],
  ["", "zh-CN;q=0,en-US;q=0", "en"],
  ["", "invalid_tag,zh-CN;q=0.8", "en"],
])(
  "negotiates the same supported page and API locale for cookie %s and header %s",
  async (cookie, language, expected) => {
    const req = new NextRequest("http://127.0.0.1:28901/login", {
      headers: {
        host: "127.0.0.1:28901",
        cookie: `NEXT_LOCALE=${cookie}`,
        "accept-language": language,
      },
    });
    const response = await proxy(req);
    expect(response.headers.get("x-middleware-rewrite")).toBe(
      `http://127.0.0.1:28901/${expected}/login`
    );
    expect(resolveApiErrorLocale(req)).toBe(expected);
  }
);

it("ignores obsolete cookie names that page routing does not read", async () => {
  const req = new NextRequest("http://127.0.0.1:28901/login", {
    headers: {
      host: "127.0.0.1:28901",
      cookie: "contextbase_cp_locale=zh-CN",
      "accept-language": "en",
    },
  });
  const response = await proxy(req);
  expect(response.headers.get("x-middleware-rewrite")).toBe("http://127.0.0.1:28901/en/login");
  expect(resolveApiErrorLocale(req)).toBe("en");
});
