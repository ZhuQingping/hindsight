import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createSessionToken, revokeSessionToken, sessionCookieName } from "@/lib/auth/session";
import {
  contextDBHeaders,
  contextDBUrl,
  contextDBConfigurationError,
  contextDBEnabled,
  isContextDBLifecycleRequest,
  requireContextDBAdmin,
  waitForContextDBAdmin,
  verifyContextDBAdmin,
} from "@/lib/contextdb";
import { GET, POST, PATCH, DELETE } from "@/app/api/contextdb/[...path]/route";
import {
  PUT as bankPUT,
  PATCH as bankPATCH,
  DELETE as bankDELETE,
} from "@/app/api/banks/[bankId]/route";
import { POST as login } from "@/app/api/auth/login/route";
import { contextDBRequest } from "@/lib/contextdb-api";

// Exercise the real Bank route and ContextDB proxy without loading the unused
// native branch's SDK, whose dist is not built before UI tests in CI.
vi.mock("@/lib/contextbase-client", () => ({
  sdk: {},
  lowLevelClient: {},
}));

const USER = "11111111111141118111111111111111";
const KEY = "22222222222242228222222222222222";
const backend = vi.fn();
const admin = () => new Response(JSON.stringify({ role: "admin", user_id: USER }), { status: 200 });
async function request(
  path: string,
  method = "GET",
  body?: unknown,
  extra?: Record<string, string>,
  prefix = "/api/contextdb"
) {
  const token = await createSessionToken("ui-password");
  return new Request(`http://ui.local${prefix}${path}`, {
    method,
    headers: {
      host: "ui.local",
      cookie: `${sessionCookieName()}=${token}`,
      origin: "http://ui.local",
      ...extra,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
const bankRoute = (bankId = "mysql") => ({ params: Promise.resolve({ bankId }) });
const bankRequest = (
  method: string,
  body?: unknown,
  extra?: Record<string, string>,
  bankId = "mysql"
) => request(`/${bankId}`, method, body, extra, "/api/banks");
const route = (...path: string[]) => ({ params: Promise.resolve({ path }) });

let sessionDirectory: string;
beforeEach(async () => {
  sessionDirectory = await mkdtemp(path.join(os.tmpdir(), "ctxdb-session-"));
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", sessionDirectory);
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://ui.local");
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
  vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "true");
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ui-password");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_KEY", "ctx_live_server-only");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://backend.local");
  vi.stubGlobal("fetch", backend);
  backend.mockReset();
  backend.mockImplementation(admin);
});
afterEach(async () => {
  await rm(sessionDirectory, { recursive: true, force: true });
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("hides management server diagnostics while preserving status and request correlation", async () => {
  backend.mockResolvedValue(
    new Response("Hindsight private server trace", {
      status: 503,
      headers: {
        "X-Request-ID": "upstream-request-id",
        ETag: '"metadata-version"',
      },
    })
  );
  const response = await GET(await request("/users"), route("users"));
  expect(response.status).toBe(503);
  expect(response.headers.get("X-Request-ID")).toBe("upstream-request-id");
  expect(response.headers.get("ETag")).toBe('"metadata-version"');
  expect(response.headers.get("Cache-Control")).toContain("no-store");
  expect(await response.json()).toEqual({
    code: "service_unavailable",
    message: "ContextBase management service is unavailable",
    request_id: "upstream-request-id",
  });
});

describe("browser management contract", () => {
  it("sends the quoted If-Match required by the actual extension", async () => {
    backend.mockResolvedValue(new Response(JSON.stringify({ version: 2 })));
    await contextDBRequest(`/users/${USER}`, {
      method: "PATCH",
      version: 1,
      body: { name: "New name" },
    });
    expect(backend.mock.calls[0][1].headers.get("If-Match")).toBe('"1"');
  });
  it("displays sanitized extension errors such as last-administrator protection", async () => {
    backend.mockResolvedValue(
      new Response(
        JSON.stringify({ code: "last_admin_key", message: "Keep one administrator Key" }),
        { status: 409 }
      )
    );
    await expect(
      contextDBRequest(`/users/${USER}/keys/${KEY}`, { method: "DELETE" })
    ).rejects.toThrow("Keep one administrator Key");
  });
});

describe("ContextDB administrator authentication", () => {
  it.each([500, 503])("returns a neutral backend error for status %s", async (status) => {
    backend.mockResolvedValue(new Response("private upstream body", { status }));
    const response = await verifyContextDBAdmin();
    expect(response?.status).toBe(503);
    expect(await response?.json()).toEqual({
      error: "The backend service is unavailable",
    });
  });
  it("returns a neutral network error from the login endpoint", async () => {
    backend.mockRejectedValue(new TypeError("private network diagnostic"));
    const response = await login(
      new NextRequest("http://ui.local/api/auth/login", {
        method: "POST",
        headers: {
          host: "ui.local",
          origin: "http://ui.local",
          "content-type": "application/json",
        },
        body: JSON.stringify({ key: "ui-password" }),
      })
    );
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({
      error: "Unable to connect to the backend service",
    });
  });
  it("honors team-prefixed configuration over conflicting legacy values", async () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "false");
    vi.stubEnv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "true");
    vi.stubEnv("CONTEXTBASE_CP_ACCESS_KEY", "team-password");
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "team-admin");
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://team-api.local");
    expect(contextDBEnabled()).toBe(true);
    expect(contextDBHeaders().get("authorization")).toBe("Bearer team-admin");
    expect(contextDBUrl("/users")).toBe("http://team-api.local/ext/contextdb/v1/users");
    const token = await createSessionToken("team-password");
    expect(
      await requireContextDBAdmin(
        new Request("http://ui.local/api/contextdb/users", {
          headers: { cookie: `${sessionCookieName()}=${token}` },
        })
      )
    ).toBeNull();
  });
  it("denies a revoked UI session before using the server admin credential", async () => {
    const token = await createSessionToken("ui-password");
    const req = new Request("http://ui.local/api/contextdb/users", {
      headers: { cookie: `${sessionCookieName()}=${token}` },
    });
    expect(await requireContextDBAdmin(req)).toBeNull();
    backend.mockClear();
    await revokeSessionToken(token);
    expect((await requireContextDBAdmin(req))?.status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
  });
  it("rejects bootstrap authentication and incomplete team authentication settings", () => {
    vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "bootstrap");
    expect(contextDBConfigurationError()).toContain("local UI authentication");
    vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
    vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://ui.local/path");
    expect(contextDBConfigurationError()).toContain("PUBLIC_ORIGIN");
    vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://ui.local");
    vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", "relative");
    expect(contextDBConfigurationError()).toContain("SESSION_DIR");
  });
  it("rejects a forged same-host origin with a different scheme", async () => {
    const response = await POST(
      await request("/users", "POST", {}, { origin: "https://ui.local" }),
      route("users")
    );
    expect(response.status).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });

  it("retries a temporary startup outage but still rechecks later requests", async () => {
    vi.useFakeTimers();
    backend
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(new Response("{}", { status: 503 }))
      .mockImplementation(admin);
    const started = waitForContextDBAdmin(5000);
    await vi.advanceTimersByTimeAsync(1000);
    await started;
    expect(backend).toHaveBeenCalledTimes(3);
    backend.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    expect((await requireContextDBAdmin(await request("/users")))?.status).toBe(401);
  });
  it.each([401, 403])("does not retry invalid startup credentials (%s)", async (status) => {
    backend.mockResolvedValue(new Response("{}", { status }));
    await expect(waitForContextDBAdmin(5000)).rejects.toThrow("invalid");
    expect(backend).toHaveBeenCalledTimes(1);
  });
  it("bounds startup retries and rejects a malformed identity without retry", async () => {
    vi.useFakeTimers();
    backend.mockRejectedValue(new TypeError("offline"));
    const outcome = expect(waitForContextDBAdmin(500)).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(1000);
    await outcome;
    backend.mockReset();
    backend.mockResolvedValue(new Response("not-json"));
    await expect(waitForContextDBAdmin(5000)).rejects.toThrow("invalid");
    expect(backend).toHaveBeenCalledTimes(1);
  });
  it("requires explicit true and independent credentials", () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "1");
    expect(contextDBEnabled()).toBe(false);
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "");
    expect(contextDBConfigurationError()).toBeTruthy();
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ctx_live_server-only");
    expect(contextDBConfigurationError()).toContain("independent");
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ctx_ctrl_password");
    expect(contextDBConfigurationError()).toContain("independent");
    vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ctx_admin_other-secret");
    expect(contextDBConfigurationError()).toContain("independent");
  });
  it("rejects management without a UI session before contacting the backend", async () => {
    const response = await GET(new Request("http://ui.local/api/contextdb/users"), route("users"));
    expect(response.status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
  });
  it("fails closed when the server key is missing even with a valid UI session", async () => {
    vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_KEY", "");
    const response = await GET(await request("/users"), route("users"));
    expect(response.status).toBe(503);
    expect(backend).not.toHaveBeenCalled();
  });
  it("blocks member server keys and rechecks authorization on every request", async () => {
    const req = await request("/users");
    expect(await requireContextDBAdmin(req)).toBeNull();
    backend.mockResolvedValueOnce(new Response(JSON.stringify({ role: "member" })));
    expect((await requireContextDBAdmin(req))?.status).toBe(403);
    expect(backend).toHaveBeenCalledTimes(2);
    expect(backend.mock.calls[0][1].cache).toBe("no-store");
  });
  it.each([401, 403, 500])("denies backend session status %s", async (status) => {
    backend.mockResolvedValue(new Response("{}", { status }));
    expect((await requireContextDBAdmin(await request("/users")))?.status).toBe(
      status === 500 ? 503 : status
    );
  });
  it("accepts the independent password and never member keys as UI login credentials", async () => {
    const createLogin = (key: string) =>
      new NextRequest("http://ui.local/api/auth/login", {
        method: "POST",
        headers: { host: "ui.local", origin: "http://ui.local" },
        body: JSON.stringify({ key }),
      });
    expect((await login(createLogin("ctx_live_member"))).status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
    const response = await login(createLogin("ui-password"));
    expect(response.status).toBe(200);
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(backend.mock.calls[0][1].headers.get("authorization")).toBe(
      "Bearer ctx_live_server-only"
    );
    backend.mockResolvedValueOnce(new Response("{}", { status: 401 }));
    const rejected = await login(createLogin("ui-password"));
    expect(rejected.status).toBe(401);
    expect(rejected.headers.get("set-cookie")).toBeNull();
  });
  it("preserves native password login when ContextDB mode is off", async () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "false");
    const response = await login(
      new NextRequest("http://ui.local/api/auth/login", {
        method: "POST",
        headers: { host: "ui.local", origin: "http://ui.local" },
        body: JSON.stringify({ key: "ui-password" }),
      })
    );
    expect(response.status).toBe(200);
    expect(backend).not.toHaveBeenCalled();
    expect((await GET(await request("/users"), route("users"))).status).toBe(404);
  });
});

describe("management proxy boundaries", () => {
  it.each(["PUT", "DELETE"])(
    "waits beyond the former 15 second workspace %s limit without an automatic retry",
    async (method) => {
      vi.useFakeTimers();
      backend.mockImplementationOnce(
        (_url: unknown, options: RequestInit) =>
          new Promise((resolve, reject) => {
            const timer = setTimeout(
              () =>
                resolve(
                  method === "PUT"
                    ? new Response('{"workspace_id":"space","bank_id":"mysql","state":"active"}', {
                        status: 200,
                      })
                    : new Response('{"success":true,"message":"Deleted","deleted_count":0}', {
                        status: 200,
                      })
                ),
              16000
            );
            options.signal?.addEventListener("abort", () => {
              clearTimeout(timer);
              reject(new Error("Timed out"));
            });
          })
      );
      const result =
        method === "PUT"
          ? bankPUT(await bankRequest("PUT", { name: "mysql" }), bankRoute())
          : bankDELETE(
              await bankRequest("DELETE", undefined, {
                "if-match": `"${USER}:1"`,
              }),
              bankRoute()
            );
      await vi.waitFor(() => expect(backend).toHaveBeenCalledTimes(1));
      await vi.advanceTimersByTimeAsync(16000);
      expect((await result).status).toBe(200);
      expect(backend).toHaveBeenCalledTimes(1);
      expect(backend.mock.calls[0][1].signal).toBeUndefined();
    }
  );
  it("keeps the existing timeout for metadata reads and user management writes", async () => {
    backend.mockResolvedValue(new Response("{}"));
    await GET(await request("/workspaces"), route("workspaces"));
    expect(backend.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    await POST(await request("/users", "POST", { name: "Member" }), route("users"));
    expect(backend.mock.calls[1][1].signal).toBeInstanceOf(AbortSignal);
  });
  it("returns the native Bank deletion result without an operation location", async () => {
    backend.mockResolvedValueOnce(
      new Response('{"success":true,"message":"Deleted","deleted_count":0}', { status: 200 })
    );
    const response = await bankDELETE(
      await bankRequest("DELETE", undefined, { "if-match": `"${USER}:1"` }),
      bankRoute()
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ success: true });
    expect(response.headers.get("Location")).toBeNull();
  });

  it.each(["嘉木", "../jiamu", "MySQL", "a".repeat(55)])(
    "rejects unsupported workspace addresses %s before contacting data routes",
    async (name) => {
      expect(
        (
          await GET(
            await request("/workspaces/" + encodeURIComponent(name)),
            route("workspaces", name)
          )
        ).status
      ).toBe(404);
      expect(backend).toHaveBeenCalledTimes(0);
    }
  );
  it("accepts valid readable identifiers that happen to have UUID format", async () => {
    backend.mockResolvedValueOnce(new Response("{}"));
    const response = await GET(await request(`/workspaces/${USER}`), route("workspaces", USER));
    expect(response.status).toBe(200);
    expect(String(backend.mock.calls[0][0])).toBe(
      `http://backend.local/ext/contextdb/v1/workspaces/${USER}`
    );
  });
  it("requires an identity-bound delete precondition and forwards it unchanged", async () => {
    const etag = `"${USER}:1"`;
    expect(
      (
        await bankDELETE(
          await bankRequest("DELETE", undefined, { "idempotency-key": "delete-old" }),
          bankRoute()
        )
      ).status
    ).toBe(428);
    expect(backend).toHaveBeenCalledTimes(0);
    backend.mockClear();
    expect(
      (
        await bankDELETE(
          await bankRequest("DELETE", undefined, {
            "idempotency-key": "delete-old",
            "if-match": '"1"',
          }),
          bankRoute()
        )
      ).status
    ).toBe(400);
    expect(backend).toHaveBeenCalledTimes(0);
    backend.mockReset();
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: "version_conflict", message: "stale" }), {
        status: 412,
      })
    );
    const response = await bankDELETE(
      await bankRequest("DELETE", undefined, {
        "idempotency-key": "delete-old",
        "if-match": etag,
      }),
      bankRoute()
    );
    expect(response.status).toBe(412);
    expect(backend.mock.calls[0][1].headers.get("if-match")).toBe(etag);
    expect(backend.mock.calls[0][1].headers.has("idempotency-key")).toBe(false);
    expect(String(backend.mock.calls[0][0])).toBe("http://backend.local/v1/default/banks/mysql");
    expect(backend).toHaveBeenCalledTimes(1);
  });
  it("forwards pagination and filters using only the fixed server host and key", async () => {
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [], total: 0, limit: 20, offset: 40 }))
    );
    const response = await GET(
      await request(`/users?limit=20&offset=40&url=http://evil.local`, "GET", undefined, {
        authorization: "Bearer browser-key",
        "x-dataplane-url": "http://evil.local",
      }),
      route("users")
    );
    expect(response.status).toBe(200);
    const [url, options] = backend.mock.calls[0];
    expect(String(url)).toBe(`http://backend.local/ext/contextdb/v1/users?limit=20&offset=40`);
    expect(options.headers.get("authorization")).toBe("Bearer ctx_live_server-only");
    expect(response.headers.get("cache-control")).toContain("no-store");
  });
  it.each(["http://evil.local", "null", ""])(
    "rejects mutation Origin %s before side effects",
    async (origin) => {
      const response = await POST(
        await request("/users", "POST", { name: "A" }, { origin }),
        route("users")
      );
      expect(response.status).toBe(403);
      expect(backend).not.toHaveBeenCalled();
    }
  );
  it("uses the actual Host with TLS termination instead of Next's internal URL", async () => {
    vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "https://admin.example.test");
    const token = await createSessionToken("ui-password");
    const req = new Request("http://localhost:39777/api/contextdb/users", {
      method: "POST",
      headers: {
        host: "admin.example.test",
        "x-forwarded-proto": "http",
        "x-forwarded-host": "evil.local",
        "sec-fetch-site": "same-origin",
        origin: "https://admin.example.test",
        cookie: `${sessionCookieName()}=${token}`,
      },
      body: "{}",
    });
    expect(await requireContextDBAdmin(req)).toBeNull();
  });
  it("rejects cross-site fetch metadata even if untrusted forwarded headers are spoofed", async () => {
    const response = await POST(
      await request(
        "/users",
        "POST",
        {},
        {
          "sec-fetch-site": "cross-site",
          "x-forwarded-host": "ui.local",
          "x-forwarded-proto": "http",
        }
      ),
      route("users")
    );
    expect(response.status).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });
  it("requires optimistic concurrency and passes conflicts back without retry", async () => {
    expect(
      (
        await PATCH(
          await request(`/users/${USER}`, "PATCH", { name: "Changed" }),
          route("users", USER)
        )
      ).status
    ).toBe(400);
    backend.mockReset();
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Version changed" }), { status: 412 })
    );
    const response = await PATCH(
      await request(
        `/users/${USER}/keys/${KEY}`,
        "PATCH",
        {
          authorization: {
            mode: "selected",
            workspaces: [{ bank_id: "mysql", permission: "read" }],
          },
        },
        { "if-match": '"7"' }
      ),
      route("users", USER, "keys", KEY)
    );
    expect(response.status).toBe(412);
    expect(backend.mock.calls[0][1].headers.get("if-match")).toBe('"7"');
    expect(backend).toHaveBeenCalledTimes(1);
  });
  it.each(["0", '"0"', "1", '"01"'])(
    "rejects invalid If-Match %s before mutation",
    async (version) => {
      const response = await PATCH(
        await request(`/users/${USER}`, "PATCH", { name: "Changed" }, { "if-match": version }),
        route("users", USER)
      );
      expect(response.status).toBe(400);
      expect(backend).toHaveBeenCalledTimes(0);
    }
  );
  it("passes resource versions and request tracing while allowing workspace status reads", async () => {
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ workspace_id: USER, state: "active" }), {
        headers: { ETag: '"3"', "X-Request-ID": "trace-request" },
      })
    );
    const response = await GET(await request("/workspaces/mysql"), route("workspaces", "mysql"));
    expect(response.status).toBe(200);
    expect(response.headers.get("etag")).toBe('"3"');
    expect(response.headers.get("x-request-id")).toBe("trace-request");
  });
  it("does not expose secret fields in lists or errors; only successful key creation", async () => {
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ items: [{ key_id: KEY, secret: "hidden", digest: "hidden" }] }))
    );
    const metadata = await GET(await request(`/users/${USER}/keys`), route("users", USER, "keys"));
    expect(await metadata.text()).not.toContain("hidden");
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ key_id: KEY, secret: "one-time", digest: "hidden" }), {
        status: 201,
      })
    );
    const created = await POST(
      await request(`/users/${USER}/keys`, "POST", {
        name: "K",
        authorization: {
          mode: "selected",
          workspaces: [{ bank_id: "mysql", permission: "read" }],
        },
      }),
      route("users", USER, "keys")
    );
    expect(await created.json()).toEqual({ key_id: KEY, secret: "one-time" });
    expect(created.headers.get("cache-control")).toContain("no-store");
  });
  it("proxies synchronous workspace creation with only the configured admin key", async () => {
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ workspace_id: USER, bank_id: "mysql", state: "active" }), {
        status: 200,
      })
    );
    const response = await bankPUT(
      await bankRequest(
        "PUT",
        { name: "MySQL" },
        { "idempotency-key": "stable-uuid", authorization: "Bearer member" }
      ),
      bankRoute()
    );
    expect(response.status).toBe(200);
    expect(String(backend.mock.calls[0][0])).toBe("http://backend.local/v1/default/banks/mysql");
    expect(backend.mock.calls[0][1].headers.has("idempotency-key")).toBe(false);
    expect(backend.mock.calls[0][1].headers.get("authorization")).toBe(
      "Bearer ctx_live_server-only"
    );
    expect(JSON.parse(backend.mock.calls[0][1].body)).toEqual({ name: "MySQL" });
  });
  it("rejects obsolete operation polling and does not expose instance provisioning", async () => {
    expect((await GET(await request(`/operations/${KEY}`), route("operations", KEY))).status).toBe(
      404
    );
    expect((await POST(await request("/instances", "POST", {}), route("instances"))).status).toBe(
      404
    );
  });
  it("delegates business fields to backend validation and preserves 204 revocation", async () => {
    for (const [path, body] of [["users", { name: "X", role: "admin" }]] as const) {
      backend.mockResolvedValueOnce(
        new Response(JSON.stringify({ code: "validation_error", error: "Invalid request" }), {
          status: 400,
        })
      );
      const response = await POST(await request(`/${path}`, "POST", body), route(path));
      expect(response.status).toBe(400);
      expect(JSON.parse(backend.mock.calls.at(-1)![1].body)).toEqual(body);
      expect(backend.mock.calls.at(-1)![1].headers.get("authorization")).toBe(
        "Bearer ctx_live_server-only"
      );
    }
    backend.mockResolvedValueOnce(new Response(null, { status: 204 }));
    expect(
      (
        await DELETE(
          await request(`/users/${USER}/keys/${KEY}`, "DELETE"),
          route("users", USER, "keys", KEY)
        )
      ).status
    ).toBe(204);
  });

  it.each([
    "/api/banks",
    `/api/banks/${USER}`,
    `/api/banks/${USER}/clone`,
    `/api/banks/${USER}/restore`,
    `/api/banks/${USER}/aliases/a`,
    `/api/banks/${USER}/import`,
  ])("blocks workspace lifecycle mutation %s", (path) => {
    expect(isContextDBLifecycleRequest(path, "DELETE")).toBe(true);
    expect(isContextDBLifecycleRequest(path, "GET")).toBe(false);
    expect(isContextDBLifecycleRequest(`/api/banks/${USER}/config`, "PATCH")).toBe(false);
  });
  it("forwards description and never forwards obsolete operation locations", async () => {
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ workspace_id: USER, bank_id: "mysql", state: "active" }), {
        status: 200,
        headers: { Location: `/ext/contextdb/v1/operations/${KEY}` },
      })
    );
    const response = await bankPUT(
      await bankRequest(
        "PUT",
        { name: "MySQL", description: "demo" },
        { "idempotency-key": "same-id" }
      ),
      bankRoute()
    );
    expect(response.status).toBe(200);
    expect(JSON.parse(backend.mock.calls[0][1].body)).toEqual({
      name: "MySQL",
      description: "demo",
    });
    expect(response.headers.get("Location")).toBeNull();
  });
  it("keeps local errors traceable and rejects repeated list query values", async () => {
    const response = await GET(await request("/users?limit=10&limit=20"), route("users"));
    expect(response.status).toBe(400);
    expect(await response.json()).toMatchObject({
      code: "invalid_request",
      message: "Duplicate query parameter",
      request_id: expect.any(String),
    });
    expect(backend).toHaveBeenCalledTimes(0);
  });
  it("normalizes failed UI authentication into the management error envelope", async () => {
    const response = await GET(new Request("http://ui.local/api/contextdb/users"), route("users"));
    expect(response.status).toBe(401);
    expect(await response.json()).toMatchObject({
      code: "unauthorized",
      message: "Unauthorized",
      request_id: expect.any(String),
    });
  });
});

describe("read-only recall usage proxy", () => {
  it("reads the explicit admin capability once with the existing session and server key", async () => {
    backend.mockResolvedValue(
      new Response(JSON.stringify({ role: "admin", capabilities: { recall_usage: true } }))
    );
    const response = await GET(await request("/admin/identity"), route("admin", "identity"));
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ role: "admin", capabilities: { recall_usage: true } });
    expect(backend).toHaveBeenCalledOnce();
    expect(String(backend.mock.calls[0][0])).toBe(
      "http://backend.local/ext/contextdb/v1/admin/identity"
    );
    expect(backend.mock.calls[0][1].cache).toBe("no-store");
    expect(response.headers.get("cache-control")).toContain("no-store");
  });
  it("forwards a bounded repeated-ID batch with the server key and no cache", async () => {
    const ids = ["page/a", "page%20b"];
    const query = new URLSearchParams({ object_type: "knowledge_page" });
    ids.forEach((id) => query.append("ids", id));
    const response = await GET(
      await request(`/workspaces/mysql/usage?${query}`),
      route("workspaces", "mysql", "usage")
    );
    expect(response.status).toBe(200);
    const call = backend.mock.calls.find(([url]) =>
      String(url).includes("/workspaces/mysql/usage")
    );
    expect(call).toBeTruthy();
    const target = new URL(String(call![0]));
    expect(target.origin).toBe("http://backend.local");
    expect(target.searchParams.getAll("ids")).toEqual(ids);
    expect(target.searchParams.get("object_type")).toBe("knowledge_page");
    expect(call![1].headers.get("Authorization")).toBe("Bearer ctx_live_server-only");
    expect(call![1].cache).toBe("no-store");
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(await response.text()).not.toContain("ctx_live_server-only");
  });
  it.each([
    "object_type=memory",
    "object_type=invalid&ids=a",
    "object_type=memory&object_type=memory&ids=a",
    "object_type=knowledge_page&ids=",
    "object_type=knowledge_page&ids=a&url=http://evil.local",
    `object_type=memory&${Array.from({ length: 101 }, () => "ids=a").join("&")}`,
  ])("rejects malformed queries before the data request: %s", async (query) => {
    expect(
      (
        await GET(
          await request(`/workspaces/mysql/usage?${query}`),
          route("workspaces", "mysql", "usage")
        )
      ).status
    ).toBe(400);
    expect(backend.mock.calls.every(([url]) => String(url).endsWith("/admin/identity"))).toBe(true);
  });
  it("does not expose usage through anonymous requests or mutation methods", async () => {
    const denied = await GET(
      new Request("http://ui.local/api/contextdb/workspaces/mysql/usage?object_type=memory&ids=a"),
      route("workspaces", "mysql", "usage")
    );
    expect(denied.status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
    for (const method of [POST, PATCH, DELETE]) {
      const r = await method(
        await request(
          "/workspaces/mysql/usage?object_type=memory&ids=a",
          method === POST ? "POST" : method === PATCH ? "PATCH" : "DELETE"
        ),
        route("workspaces", "mysql", "usage")
      );
      expect(r.status).toBe(404);
    }
    expect(backend.mock.calls.every(([url]) => String(url).endsWith("/admin/identity"))).toBe(true);
  });
  it("rechecks configured admin authority for usage", async () => {
    backend.mockResolvedValue(new Response('{"code":"admin_required"}', { status: 403 }));
    const r = await GET(
      await request("/workspaces/mysql/usage?object_type=knowledge_page&ids=a"),
      route("workspaces", "mysql", "usage")
    );
    expect(r.status).toBe(403);
    expect(backend).toHaveBeenCalledOnce();
  });
});

// Bank writes and management reads deliberately use different fixed proxies.
describe("Bank proxy upstream failures", () => {
  const handlers = { PUT: bankPUT, PATCH: bankPATCH, DELETE: bankDELETE };
  const methods = ["PUT", "PATCH", "DELETE"] as const;
  const condition = `"${USER}:2"`;
  const cases = methods.flatMap((method) =>
    [500, 502, 503, 504].flatMap((status) =>
      ["json", "text", "empty"].map((format) => ({ method, status, format }))
    )
  );

  it.each(cases)(
    "preserves $method $status ($format) without exposing diagnostics",
    async ({ method, status, format }) => {
      const upstream = new Response(
        format === "json"
          ? JSON.stringify({
              detail: "private store diagnostic",
              nested: { message: "private server trace" },
            })
          : format === "text"
            ? "<html>private gateway diagnostic</html>"
            : null,
        {
          status,
          headers: { "X-Request-ID": "upstream-id", "Retry-After": "30" },
        }
      );
      const parse = vi.spyOn(upstream, "json");
      backend.mockResolvedValueOnce(upstream);
      const response = await handlers[method](
        await bankRequest(method, method === "DELETE" ? undefined : {}, { "if-match": condition }),
        bankRoute()
      );
      expect(response.status).toBe(status);
      expect(response.headers.get("X-Request-ID")).toBe("upstream-id");
      expect(response.headers.get("Retry-After")).toBe("30");
      expect(response.headers.get("Cache-Control")).toContain("no-store");
      expect(response.headers.get("Pragma")).toBe("no-cache");
      expect(await response.json()).toEqual({
        code: "service_unavailable",
        message: "Bank service is temporarily unavailable",
        request_id: "upstream-id",
      });
      expect(parse).not.toHaveBeenCalled();
      expect(backend).toHaveBeenCalledOnce();
    }
  );

  it("preserves a received 5xx even if its response stream fails", async () => {
    backend.mockResolvedValueOnce(
      new Response(
        new ReadableStream({
          start: (controller) => controller.error(new Error("private stream error")),
        }),
        {
          status: 504,
          headers: { "X-Request-ID": "stream-id", "Retry-After": "30" },
        }
      )
    );
    const response = await bankPATCH(await bankRequest("PATCH", {}), bankRoute());
    expect(response.status).toBe(504);
    expect(response.headers.get("Retry-After")).toBe("30");
    expect(await response.json()).toMatchObject({
      request_id: "stream-id",
      code: "service_unavailable",
    });
    expect(backend).toHaveBeenCalledOnce();
  });

  it.each([null, ""])("generates a correlated ID when the upstream ID is %j", async (id) => {
    const headers = new Headers({ "Retry-After": "Fri, 30 Oct 2026 12:00:00 GMT" });
    if (id !== null) headers.set("X-Request-ID", id);
    backend.mockResolvedValueOnce(new Response(null, { status: 503, headers }));
    const response = await bankPUT(await bankRequest("PUT", {}), bankRoute());
    const data = await response.json();
    expect(response.status).toBe(503);
    expect(data.request_id).toEqual(expect.any(String));
    expect(data.request_id.length).toBeGreaterThan(0);
    expect(response.headers.get("X-Request-ID")).toBe(data.request_id);
    expect(response.headers.get("Retry-After")).toBe("Fri, 30 Oct 2026 12:00:00 GMT");
    expect(backend).toHaveBeenCalledOnce();
  });

  it.each([400, 401, 403, 409, 412, 428, 429])(
    "keeps %s business errors and correlation intact",
    async (status) => {
      const payload = {
        code: "business_error",
        detail: "Inspect the current condition",
        request_id: "business-id",
      };
      backend.mockResolvedValueOnce(
        new Response(JSON.stringify(payload), {
          status,
          headers: { "X-Request-ID": "business-id", "Retry-After": "30" },
        })
      );
      const response = await bankPATCH(await bankRequest("PATCH", {}), bankRoute());
      expect(response.status).toBe(status);
      expect(await response.json()).toEqual(payload);
      expect(response.headers.get("X-Request-ID")).toBe("business-id");
      expect(response.headers.get("Retry-After")).toBe("30");
      expect(backend).toHaveBeenCalledOnce();
    }
  );

  it.each(methods)(
    "reports a local connection failure only when %s receives no response",
    async (method) => {
      backend.mockRejectedValueOnce(new TypeError("private connection diagnostic"));
      const response = await handlers[method](
        await bankRequest(method, method === "DELETE" ? undefined : {}, { "if-match": condition }),
        bankRoute()
      );
      expect(response.status).toBe(503);
      const data = await response.json();
      expect(data).toEqual({
        code: "service_unavailable",
        message: "Unable to connect to the Bank service",
        request_id: expect.any(String),
      });
      expect(response.headers.get("X-Request-ID")).toBe(data.request_id);
      expect(response.headers.get("Retry-After")).toBeNull();
      expect(backend).toHaveBeenCalledOnce();
    }
  );

  it.each([200, 204, 400, 412])(
    "does not mistake an unreadable %s response for a connection failure",
    async (status) => {
      backend.mockResolvedValueOnce(
        new Response(status === 204 ? null : "not JSON", {
          status,
          headers: { "X-Request-ID": "unreadable-id", "Retry-After": "30" },
        })
      );
      const response = await bankPATCH(await bankRequest("PATCH", {}), bankRoute());
      expect(response.status).toBe(status < 300 ? 502 : status);
      expect(response.headers.get("X-Request-ID")).toBe("unreadable-id");
      expect(response.headers.get("Retry-After")).toBe("30");
      expect(await response.json()).toEqual({
        code: "response_unknown",
        message: "Bank response could not be read; inspect the workspace before retrying",
        request_id: "unreadable-id",
      });
      expect(backend).toHaveBeenCalledOnce();
    }
  );
});

describe("Bank migration boundaries", () => {
  it.each(["POST", "DELETE"])(
    "rejects the retired workspace %s without contacting the backend",
    async (method) => {
      const response =
        method === "POST"
          ? await POST(await request("/workspaces", "POST", { name: "mysql" }), route("workspaces"))
          : await DELETE(
              await request("/workspaces/mysql", "DELETE"),
              route("workspaces", "mysql")
            );
      expect(response.status).toBe(404);
      expect(backend).not.toHaveBeenCalled();
    }
  );
  it("forwards strict creation, description and the original identity header with one backend request", async () => {
    const condition = `"${USER}:2"`;
    backend.mockResolvedValueOnce(
      new Response(JSON.stringify({ bank_id: "mysql", name: "mysql", mission: "" }), {
        headers: { "X-ContextDB-Workspace-ETag": condition, Location: "/obsolete" },
      })
    );
    const response = await bankPUT(
      await bankRequest(
        "PUT",
        { name: "mysql", description: "空间说明" },
        {
          "if-none-match": "*",
          authorization: "Bearer browser-key",
        }
      ),
      bankRoute()
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("X-ContextDB-Workspace-ETag")).toBe(condition);
    expect(response.headers.get("ETag")).toBeNull();
    expect(response.headers.get("Location")).toBeNull();
    expect(backend).toHaveBeenCalledTimes(1);
    expect(backend.mock.calls[0][1].headers.get("If-None-Match")).toBe("*");
    expect(backend.mock.calls[0][1].headers.get("Authorization")).toBe(
      "Bearer ctx_live_server-only"
    );
    expect(JSON.parse(backend.mock.calls[0][1].body)).toEqual({
      name: "mysql",
      description: "空间说明",
    });
  });
  it.each(['"old"', "*, *"])(
    "rejects unsupported creation conditions %s before a write",
    async (condition) => {
      const response = await bankPUT(
        await bankRequest("PUT", {}, { "if-none-match": condition }),
        bankRoute()
      );
      expect(response.status).toBe(400);
      expect(backend).not.toHaveBeenCalled();
    }
  );
  it("allows only canonical Bank roots while preserving unsupported lifecycle protection", () => {
    for (const method of ["PUT", "DELETE"])
      expect(isContextDBLifecycleRequest("/api/banks/mysql", method)).toBe(false);
    for (const path of [
      "/api/banks/MySQL",
      "/api/banks/my-bank",
      "/api/banks/mysql/clone",
      "/api/banks/mysql/aliases",
    ])
      expect(isContextDBLifecycleRequest(path, "DELETE")).toBe(true);
  });
});
