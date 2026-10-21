import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { createSessionToken, ACCESS_KEY_COOKIE } from "@/lib/auth/session";
import {
  contextDBConfigurationError,
  contextDBEnabled,
  isContextDBLifecycleRequest,
  requireContextDBAdmin,
  waitForContextDBAdmin,
} from "@/lib/contextdb";
import { GET, POST, PATCH, DELETE } from "@/app/api/contextdb/[...path]/route";
import { POST as login } from "@/app/api/auth/login/route";
import { contextDBRequest } from "@/lib/contextdb-api";

const USER = "11111111111141118111111111111111";
const KEY = "22222222222242228222222222222222";
const backend = vi.fn();
const admin = () => new Response(JSON.stringify({ role: "admin", user_id: USER }), { status: 200 });
async function request(
  path: string,
  method = "GET",
  body?: unknown,
  extra?: Record<string, string>
) {
  const token = await createSessionToken("ui-password");
  return new Request(`http://ui.local/api/contextdb${path}`, {
    method,
    headers: { cookie: `${ACCESS_KEY_COOKIE}=${token}`, origin: "http://ui.local", ...extra },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
const route = (...path: string[]) => ({ params: Promise.resolve({ path }) });

beforeEach(() => {
  vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "true");
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", "ui-password");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_KEY", "ctx_live_server-only");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://backend.local");
  vi.stubGlobal("fetch", backend);
  backend.mockReset();
  backend.mockImplementation(admin);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
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
        headers: { origin: "http://ui.local" },
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
        body: JSON.stringify({ key: "ui-password" }),
      })
    );
    expect(response.status).toBe(200);
    expect(backend).not.toHaveBeenCalled();
    expect((await GET(await request("/users"), route("users"))).status).toBe(404);
  });
});

describe("management proxy boundaries", () => {
  it.each(["POST", "DELETE"])(
    "waits beyond the former 15 second workspace %s limit without an automatic retry",
    async (method) => {
      vi.useFakeTimers();
      backend.mockImplementationOnce(
        (_url: unknown, options: RequestInit) =>
          new Promise((resolve, reject) => {
            const timer = setTimeout(
              () =>
                resolve(
                  method === "POST"
                    ? new Response('{"workspace_id":"space","bank_id":"mysql","state":"active"}', {
                        status: 201,
                      })
                    : new Response(null, { status: 204 })
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
        method === "POST"
          ? POST(await request("/workspaces", "POST", { name: "mysql" }), route("workspaces"))
          : DELETE(
              await request("/workspaces/mysql", "DELETE", undefined, {
                "if-match": `"${USER}:1"`,
              }),
              route("workspaces", "mysql")
            );
      await vi.waitFor(() => expect(backend).toHaveBeenCalledTimes(1));
      await vi.advanceTimersByTimeAsync(16000);
      expect((await result).status).toBe(method === "POST" ? 201 : 204);
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
  it("passes synchronous deletion 204 without a body or management operation location", async () => {
    backend.mockResolvedValueOnce(new Response(null, { status: 204 }));
    const response = await DELETE(
      await request("/workspaces/mysql", "DELETE", undefined, { "if-match": `"${USER}:1"` }),
      route("workspaces", "mysql")
    );
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
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
    const path = "/workspaces/jiamu";
    const etag = `"${USER}:1"`;
    expect(
      (
        await DELETE(
          await request(path, "DELETE", undefined, { "idempotency-key": "delete-old" }),
          route("workspaces", "jiamu")
        )
      ).status
    ).toBe(428);
    expect(backend).toHaveBeenCalledTimes(0);
    backend.mockClear();
    expect(
      (
        await DELETE(
          await request(path, "DELETE", undefined, {
            "idempotency-key": "delete-old",
            "if-match": '"1"',
          }),
          route("workspaces", "jiamu")
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
    const response = await DELETE(
      await request(path, "DELETE", undefined, {
        "idempotency-key": "delete-old",
        "if-match": etag,
      }),
      route("workspaces", "jiamu")
    );
    expect(response.status).toBe(412);
    expect(backend.mock.calls[0][1].headers.get("if-match")).toBe(etag);
    expect(backend.mock.calls[0][1].headers.has("idempotency-key")).toBe(false);
    expect(String(backend.mock.calls[0][0])).toBe(
      "http://backend.local/ext/contextdb/v1/workspaces/jiamu"
    );
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
    const token = await createSessionToken("ui-password");
    const req = new Request("http://localhost:39777/api/contextdb/users", {
      method: "POST",
      headers: {
        host: "admin.example.test",
        "x-forwarded-proto": "http",
        "x-forwarded-host": "evil.local",
        "sec-fetch-site": "same-origin",
        origin: "https://admin.example.test",
        cookie: `${ACCESS_KEY_COOKIE}=${token}`,
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
        status: 201,
      })
    );
    const response = await POST(
      await request(
        "/workspaces",
        "POST",
        { name: "MySQL" },
        { "idempotency-key": "stable-uuid", authorization: "Bearer member" }
      ),
      route("workspaces")
    );
    expect(response.status).toBe(201);
    expect(String(backend.mock.calls[0][0])).toBe(
      "http://backend.local/ext/contextdb/v1/workspaces"
    );
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
    for (const [path, body] of [
      ["workspaces", { unsupported: true }],
      ["users", { name: "X", role: "admin" }],
    ] as const) {
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
        status: 201,
        headers: { Location: `/ext/contextdb/v1/operations/${KEY}` },
      })
    );
    const response = await POST(
      await request(
        "/workspaces",
        "POST",
        { name: "MySQL", description: "demo" },
        { "idempotency-key": "same-id" }
      ),
      route("workspaces")
    );
    expect(response.status).toBe(201);
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
