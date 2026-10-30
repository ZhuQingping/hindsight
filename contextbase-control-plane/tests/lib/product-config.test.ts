import { afterEach, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { parseProductConfig } from "@/lib/product-config";
import { localProductConfig, verifiedProductConfig } from "@/lib/product-config-server";
import { productGuard } from "@/lib/product-guard";
import { GET as productConfigRoute } from "@/app/api/product-config/route";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("uses the public ContextBase endpoint in the product-config route", async () => {
  vi.stubEnv("contextdb_name", "contextbase");
  vi.stubEnv("product_display_name", undefined);
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "https://memory.example.com/native/");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "https://unused.example.com");
  const fetch = vi.fn(async () =>
    Response.json({ product_config_version: 1, contextdb_name: "contextbase" })
  );
  vi.stubGlobal("fetch", fetch);
  expect((await productConfigRoute()).status).toBe(200);
  expect(fetch).toHaveBeenCalledExactlyOnceWith(
    "https://memory.example.com/native/product-config",
    expect.objectContaining({ redirect: "error", cache: "no-store" })
  );
});

it.each(["", "ContextBase", "x y", "a\n", "a/b", "元壤", "a".repeat(41)])(
  "rejects invalid name %j",
  (name) => {
    expect(() => parseProductConfig({ product_config_version: 1, contextdb_name: name })).toThrow();
  }
);

it("reads runtime names and checks only the native API, including a configured path prefix", async () => {
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://localhost:8888/native/");
  // An unrelated management service must never be required by this product branch.
  vi.stubEnv("HINDSIGHT_CP_MANAGEMENT_API_URL", "http://localhost:1/unavailable");
  for (const name of ["contextbase", "contextdb"]) {
    vi.stubEnv("contextdb_name", name);
    const fetch = vi.fn(async () =>
      Response.json({ product_config_version: 1, contextdb_name: name })
    );
    vi.stubGlobal("fetch", fetch);
    expect(localProductConfig().contextdb_name).toBe(name);
    expect((await verifiedProductConfig()).contextdb_name).toBe(name);
    expect(fetch).toHaveBeenCalledExactlyOnceWith("http://localhost:8888/native/product-config", {
      cache: "no-store",
      redirect: "error",
      signal: expect.any(AbortSignal),
    });
  }
});

it("rejects API/console mismatch before forwarding a native mutation", async () => {
  vi.stubEnv("contextdb_name", "contextdb");
  const fetch = vi.fn(async () =>
    Response.json({ product_config_version: 1, contextdb_name: "contextbase" })
  );
  vi.stubGlobal("fetch", fetch);
  const result = await productGuard(new Request("http://localhost/api/banks", { method: "POST" }));
  expect(result?.status).toBe(503);
  expect(await result?.json()).toEqual({
    code: "PRODUCT_CONFIG_MISMATCH",
    error: "PRODUCT_CONFIG_MISMATCH",
  });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["GET", "POST"])("rejects a stale tab's %s before contacting the API", async (method) => {
  vi.stubEnv("contextdb_name", "contextdb");
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const result = await productGuard(
    new Request("http://localhost/api/banks", {
      method,
      headers: { "X-Product-Name": "contextbase" },
    })
  );
  expect(result?.status).toBe(409);
  expect(await result?.json()).toEqual({ code: "PRODUCT_NAME_STALE", error: "PRODUCT_NAME_STALE" });
  expect(fetch).not.toHaveBeenCalled();
});

it("fails closed on unavailable or malformed API configuration without retrying", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ contextdb_name: "contextbase" }));
  vi.stubGlobal("fetch", fetch);
  for (let i = 0; i < 2; i++) {
    const result = await productGuard(new Request("http://localhost/api/banks"));
    expect(result?.status).toBe(503);
    expect(await result?.json()).toEqual({
      code: "PRODUCT_CONFIG_UNAVAILABLE",
      error: "PRODUCT_CONFIG_UNAVAILABLE",
    });
  }
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("returns non-secret current configuration without caching", async () => {
  vi.stubEnv("contextdb_name", "contextdb");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ product_config_version: 1, contextdb_name: "contextdb" }))
  );
  const response = await productConfigRoute();
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(await response.json()).toEqual({ product_config_version: 1, contextdb_name: "contextdb" });
});

it("preserves case in the default v2 display and requests the explicit v2 native contract", async () => {
  vi.stubEnv("contextdb_name", undefined);
  vi.stubEnv("product_display_name", undefined);
  const expected = {
    product_config_version: 2,
    contextdb_name: "contextbase",
    display_name: "ContextBase",
  };
  const fetch = vi.fn(async (_url: string, _options: RequestInit) => Response.json(expected));
  vi.stubGlobal("fetch", fetch);
  expect(localProductConfig()).toEqual(expected);
  expect(await verifiedProductConfig()).toEqual(expected);
  expect(fetch.mock.calls[0][0]).toContain("/product-config/v2");
});

it.each(["", " a", "a ", "a\n", "a/b", "<script>", "a".repeat(81)])(
  "rejects unsafe display %j",
  (display_name) => {
    expect(() =>
      parseProductConfig({ product_config_version: 2, contextdb_name: "a", display_name })
    ).toThrow();
  }
);

it("does not relax the old key set or downgrade a v2 deployment", async () => {
  expect(() =>
    parseProductConfig({ product_config_version: 1, contextdb_name: "a", display_name: "A" })
  ).toThrow();
  vi.stubEnv("contextdb_name", "a");
  vi.stubEnv("product_display_name", "ContextBase");
  const fetch = vi.fn(async () =>
    Response.json({ product_config_version: 1, contextdb_name: "a" })
  );
  vi.stubGlobal("fetch", fetch);
  await expect(verifiedProductConfig()).rejects.toThrow("PRODUCT_CONFIG_MISMATCH");
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("refuses stale display names before forwarding, even when the slug stays the same", async () => {
  vi.stubEnv("contextdb_name", "contextbase");
  vi.stubEnv("product_display_name", "Atlas Grove");
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const result = await productGuard(
    new Request("http://localhost/api/banks", {
      method: "POST",
      headers: { "X-Product-Name": "ContextBase" },
      body: "preserve input",
    })
  );
  expect(result?.status).toBe(409);
  expect(fetch).not.toHaveBeenCalled();
});

it("detects an API-only display override even for a legacy v1 UI configuration", async () => {
  vi.stubEnv("contextdb_name", "legacy");
  vi.stubEnv("product_display_name", undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json(
        { product_config_version: 1, contextdb_name: "legacy" },
        { headers: { "X-Product-Display-Name": "ContextBase" } }
      )
    )
  );
  await expect(verifiedProductConfig()).rejects.toThrow("PRODUCT_CONFIG_MISMATCH");
});
