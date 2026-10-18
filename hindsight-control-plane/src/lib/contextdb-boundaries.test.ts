import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest, NextResponse } from "next/server";
import { unstable_doesMiddlewareMatch } from "next/experimental/testing/server";
import { config, middleware } from "@/middleware";
import { createSessionToken, ACCESS_KEY_COOKIE } from "@/lib/auth/session";
import { POST as createBank } from "@/app/api/banks/route";
import { PUT, PATCH, DELETE } from "@/app/api/banks/[bankId]/route";
import { POST as clone } from "@/app/api/banks/[bankId]/clone/route";
import { POST as restore } from "@/app/api/banks/[bankId]/import/route";
import { POST as createAlias } from "@/app/api/banks/[bankId]/aliases/route";

const localeMiddleware = vi.hoisted(() => vi.fn());
vi.mock("next-intl/middleware", () => ({ default: () => localeMiddleware }));
vi.mock("@/lib/hindsight-client", () => ({
  sdk: {},
  lowLevelClient: {},
  getDataplaneHeaders: vi.fn(),
  dataplaneBankUrl: vi.fn(),
}));
const backend = vi.fn();
const params = { params: Promise.resolve({ bankId: "workspace" }) };
beforeEach(() => {
  vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "true");
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ui-password");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_KEY", "server-admin");
  vi.stubGlobal("fetch", backend);
  localeMiddleware.mockReset();
  localeMiddleware.mockImplementation(() => NextResponse.next());
  backend.mockReset();
  backend.mockImplementation(() =>
    Promise.resolve(new Response(JSON.stringify({ role: "admin" })))
  );
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});
async function req(path: string, method = "GET", body?: unknown, authenticated = true) {
  return new NextRequest(`http://ui.local${path}`, {
    method,
    headers: {
      origin: "http://ui.local",
      ...(authenticated
        ? { cookie: `${ACCESS_KEY_COOKIE}=${await createSessionToken("ui-password")}` }
        : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

describe("actual middleware and bank handlers", () => {
  it.each(["json", "txt", "js", "svg", "xml"])(
    "authenticates dynamic API IDs ending in .%s, including under a base path",
    async (suffix) => {
      const path = `/api/banks/workspace/mental-models/notes.${suffix}`;
      expect(unstable_doesMiddlewareMatch({ config, url: path })).toBe(true);
      expect(
        unstable_doesMiddlewareMatch({
          config,
          url: `/memory${path}`,
          nextConfig: { basePath: "/memory" },
        })
      ).toBe(true);
      for (const method of ["GET", "PATCH", "DELETE"]) {
        expect((await middleware(await req(path, method, undefined, false))).status).toBe(401);
      }
      const forged = await req(path, "PATCH", {});
      forged.headers.set("origin", "https://evil.example");
      expect((await middleware(forged)).status).toBe(403);
      expect(backend).not.toHaveBeenCalled();
    }
  );
  it.each(["en", "zh-CN", "zh-TW"])(
    "keeps the internally localized %s login page public",
    async (locale) => {
      const response = await middleware(await req(`/${locale}/login`, "GET", undefined, false));
      expect(response.headers.get("x-middleware-next")).toBe("1");
      expect(response.headers.get("location")).toBeNull();
      expect(backend).not.toHaveBeenCalled();
      expect(localeMiddleware).not.toHaveBeenCalled();
      expect((await middleware(await req("/login", "GET", undefined, false))).status).toBe(200);
      expect(localeMiddleware).toHaveBeenCalledOnce();
    }
  );
  it("canonicalizes only known locale pages, including base paths", async () => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/memory");
    const login = await middleware(await req("/memory/zh-CN/login", "GET", undefined, false));
    expect(login.headers.get("x-middleware-next")).toBe("1");
    const denied = await middleware(await req("/memory/zh-CN/users", "GET", undefined, false));
    const target = new URL(denied.headers.get("location")!);
    expect(target.pathname).toBe("/memory/login");
    expect(target.searchParams.get("returnTo")).toBe("/users");
    const unknown = await middleware(await req("/unknown/login", "GET", undefined, false));
    expect(new URL(unknown.headers.get("location")!).searchParams.get("returnTo")).toBe(
      "/unknown/login"
    );
    expect(backend).not.toHaveBeenCalled();
  });
  it("checks the cookie and backend for localized private pages", async () => {
    expect((await middleware(await req("/en/users", "GET", undefined, false))).status).toBe(307);
    const authenticated = await middleware(await req("/en/users"));
    expect(authenticated.headers.get("x-middleware-next")).toBe("1");
    expect(backend).toHaveBeenCalledOnce();
    backend.mockResolvedValueOnce(new Response("{}", { status: 403 }));
    expect((await middleware(await req("/zh-CN/users"))).status).toBe(403);
  });
  it("does not turn locale-prefixed API-shaped or login-like pages into public routes", async () => {
    for (const path of ["/en/api/auth/login", "/zh-CN/api/health", "/en/login-private"]) {
      const response = await middleware(await req(path, "GET", undefined, false));
      expect(response.status).toBe(307);
      expect(response.headers.get("x-middleware-next")).toBeNull();
    }
    expect(
      (await middleware(await req("/api/contextdb/users", "GET", undefined, false))).status
    ).toBe(401);
    expect(backend).not.toHaveBeenCalled();
  });
  it("preserves native locale routing with and without a UI password", async () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "false");
    expect((await middleware(await req("/en/login", "GET", undefined, false))).status).toBe(307);
    expect(localeMiddleware).not.toHaveBeenCalled();
    expect((await middleware(await req("/en/users"))).status).toBe(200);
    expect(localeMiddleware).toHaveBeenCalledOnce();
    expect(backend).not.toHaveBeenCalled();
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "");
    expect((await middleware(await req("/en/login", "GET", undefined, false))).status).toBe(200);
    expect(localeMiddleware).toHaveBeenCalledTimes(2);
    expect(
      (await middleware(await req("/api/contextdb/users", "GET", undefined, false))).headers.get(
        "x-middleware-next"
      )
    ).toBe("1");
  });
  it("still skips static page assets", () => {
    expect(unstable_doesMiddlewareMatch({ config, url: "/logo.png" })).toBe(false);
    expect(unstable_doesMiddlewareMatch({ config, url: "/_next/static/app.js" })).toBe(false);
  });
  it("does not silently open ContextDB when its UI password is missing", async () => {
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "");
    expect((await middleware(await req("/api/banks", "GET", undefined, false))).status).toBe(503);
    expect(backend).not.toHaveBeenCalled();
  });
  it("requires a session for normal APIs, and an admin backend for authenticated pages", async () => {
    expect((await middleware(await req("/api/banks", "GET", undefined, false))).status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
    backend.mockResolvedValue(new Response("{}", { status: 403 }));
    expect((await middleware(await req("/users"))).status).toBe(403);
  });
  it("blocks lifecycle mutations but preserves memory/config paths", async () => {
    expect((await middleware(await req("/api/banks/workspace/clone", "POST", {}))).status).toBe(
      403
    );
    expect(
      (
        await middleware(
          await req("/api/banks/workspace/config", "PATCH", {
            updates: { reflect_mission: "mission" },
          })
        )
      ).headers.get("x-middleware-next")
    ).toBe("1");
    expect(
      (await middleware(await req("/api/recall", "POST", { bank_id: "workspace" }))).headers.get(
        "x-middleware-next"
      )
    ).toBe("1");
  });
  it("preserves native public APIs when ContextDB and access auth are off", async () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "false");
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "");
    expect(
      (await middleware(await req("/api/banks", "GET", undefined, false))).headers.get(
        "x-middleware-next"
      )
    ).toBe("1");
    expect(backend).not.toHaveBeenCalled();
  });
  it("rejects direct route invocation for create/delete/clone/import/alias/rename", async () => {
    expect((await createBank(await req("/api/banks", "POST", {}))).status).toBe(403);
    expect((await PUT(await req("/api/banks/workspace", "PUT", {}), params)).status).toBe(403);
    expect((await DELETE(await req("/api/banks/workspace", "DELETE"), params)).status).toBe(403);
    expect(
      (await PATCH(await req("/api/banks/workspace", "PATCH", { name: "Renamed" }), params)).status
    ).toBe(403);
    expect((await clone(await req("/api/banks/workspace/clone", "POST", {}), params)).status).toBe(
      403
    );
    expect(
      (await restore(await req("/api/banks/workspace/import", "POST", {}), params)).status
    ).toBe(403);
    expect(
      (await createAlias(await req("/api/banks/workspace/aliases", "POST", {}), params)).status
    ).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });
});
