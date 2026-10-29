vi.mock("server-only", () => ({}));
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { NextRequest } from "next/server";
import { proxy, config } from "@/proxy";
import { createSessionToken, sessionCookieName } from "@/lib/auth/session";
import { POST as login } from "@/app/api/auth/login/route";
import { GET as sessionInfo } from "@/app/api/auth/session/route";
import { POST as logout } from "@/app/api/auth/logout/route";
vi.mock("next-intl/middleware", () => ({ default: () => () => new Response(null) }));

let directory: string;
const origin = "http://127.0.0.1:28901";
beforeEach(async () => {
  vi.stubEnv("contextdb_name", undefined);
  vi.stubEnv("product_display_name", undefined);
  vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => new Response(JSON.stringify({ product_config_version: 2, contextdb_name: "contextbase", display_name: "ContextBase" }), { status: 200 })));
  directory = await mkdtemp(path.join(os.tmpdir(), "m2-proxy-"));
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", directory);
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "test-login-password");
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", origin);
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
});
afterEach(async () => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  await rm(directory, { recursive: true, force: true });
});
function request(url: string, token?: string, method = "GET", body?: unknown) {
  return new NextRequest(origin + url, {
    method,
    headers: {
      host: "127.0.0.1:28901",
      origin,
      ...(token ? { cookie: `${sessionCookieName()}=${token}` } : {}),
      "content-type": "application/json",
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
}
it.each([
  "/api/banks/plain",
  "/api/banks/probe.json",
  "/api/banks/probe.png",
  "/api/files/download/a.txt",
  "/api/health-other",
  "/api/auth/not-public",
])("protects dynamic route %s", async (url) => {
  expect(config.matcher).toBe("/:path*");
  expect((await proxy(request(url))).status).toBe(401);
  const token = await createSessionToken("test-login-password");
  expect((await proxy(request(url, token))).status).toBe(200);
});
it("rejects missing configuration instead of opening proxy access", async () => {
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "");
  expect((await proxy(request("/api/banks"))).status).toBe(503);
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "bootstrap");
  expect((await proxy(request("/api/banks"))).status).toBe(200);
});
it("rejects cross-origin mutations even with a valid session", async () => {
  const token = await createSessionToken("test-login-password");
  const req = request("/api/banks", token, "POST", {});
  req.headers.set("origin", "https://evil.test");
  expect((await proxy(req)).status).toBe(403);
});
it("login and logout revoke a copied cookie before another API request", async () => {
  const result = await login(
    request("/api/auth/login", undefined, "POST", { key: "test-login-password" })
  );
  expect(result.status).toBe(200);
  const token = result.cookies.get(sessionCookieName())!.value;
  expect((await proxy(request("/api/banks", token))).status).toBe(200);
  expect((await logout(request("/api/auth/logout", token, "POST"))).status).toBe(200);
  expect((await proxy(request("/api/banks", token))).status).toBe(401);
});
it.each([null, { key: 123 }, { key: {} }, { key: "wrong" }])(
  "rejects malformed credential body %j",
  async (body) => {
    expect((await login(request("/api/auth/login", undefined, "POST", body))).status).toBe(401);
  }
);

it.each(["/_next/static/chunk.js", "/product-icon.svg", "/img/harness/codex.svg"])(
  "passes known static asset %s without locale rewrite",
  async (url) => {
    const response = await proxy(request(url));
    expect(response.headers.get("x-middleware-next")).toBe("1");
    expect(response.headers.get("x-middleware-rewrite")).toBeNull();
  }
);

it("exposes only local access metadata independently of the dataplane", async () => {
  expect((await proxy(request("/api/auth/session"))).status).toBe(200);
  const result = await sessionInfo();
  expect(await result.json()).toEqual({ required: true });
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "bootstrap");
  expect(await (await sessionInfo()).json()).toEqual({ required: false });
});

it("rejects a different host even for authenticated reads", async () => {
  const token = await createSessionToken("test-login-password");
  const req = request("/api/banks", token);
  req.headers.set("host", "untrusted.example");
  expect((await proxy(req)).status).toBe(421);
});

it.each(["GET", "HEAD"])(
  "protects export %s which submits a stateful native job",
  async (method) => {
    const token = await createSessionToken("test-login-password");
    const crossSite = request("/api/documents/transfer?bank_id=one", token, method);
    crossSite.headers.set("sec-fetch-site", "cross-site");
    expect((await proxy(crossSite)).status).toBe(403);
    const sameSite = request("/api/documents/transfer?bank_id=one", token, method);
    sameSite.headers.set("sec-fetch-site", "same-origin");
    expect((await proxy(sameSite)).status).toBe(200);
  }
);

it("checks native product configuration only after authenticating the UI session", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  expect((await proxy(request("/api/banks", undefined, "POST", {}))).status).toBe(401);
  expect(fetch).not.toHaveBeenCalled();
});

it("keeps login and logout available when the native API configuration is unavailable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  expect((await proxy(request("/api/auth/session"))).status).toBe(200);
  expect((await proxy(request("/api/auth/logout", undefined, "POST"))).status).toBe(200);
});
