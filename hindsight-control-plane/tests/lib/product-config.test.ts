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

it.each(["", "AgentStratum", "x y", "a\n", "a/b", "元壤", "a".repeat(41)])(
  "rejects invalid name %j",
  (name) => {
    expect(() => parseProductConfig({ product_config_version: 1, contextdb_name: name })).toThrow();
  }
);

it("reads runtime names and checks only the native API, including a configured path prefix", async () => {
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://localhost:8888/native/");
  // An unrelated management service must never be required by this product branch.
  vi.stubEnv("HINDSIGHT_CP_MANAGEMENT_API_URL", "http://localhost:1/unavailable");
  for (const name of ["agentstratum", "contextdb"]) {
    vi.stubEnv("contextdb_name", name);
    const fetch = vi.fn(async () => Response.json({ product_config_version: 1, contextdb_name: name }));
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
  const fetch = vi.fn(async () => Response.json({ product_config_version: 1, contextdb_name: "agentstratum" }));
  vi.stubGlobal("fetch", fetch);
  const result = await productGuard(new Request("http://localhost/api/banks", { method: "POST" }));
  expect(result?.status).toBe(503);
  expect(await result?.json()).toEqual({ code: "PRODUCT_CONFIG_MISMATCH", error: "PRODUCT_CONFIG_MISMATCH" });
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["GET", "POST"])("rejects a stale tab's %s before contacting the API", async (method) => {
  vi.stubEnv("contextdb_name", "contextdb");
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const result = await productGuard(new Request("http://localhost/api/banks", {
    method,
    headers: { "X-Product-Name": "agentstratum" },
  }));
  expect(result?.status).toBe(409);
  expect(await result?.json()).toEqual({ code: "PRODUCT_NAME_STALE", error: "PRODUCT_NAME_STALE" });
  expect(fetch).not.toHaveBeenCalled();
});

it("fails closed on unavailable or malformed API configuration without retrying", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response(null, { status: 503 }))
    .mockResolvedValueOnce(Response.json({ contextdb_name: "agentstratum" }));
  vi.stubGlobal("fetch", fetch);
  for (let i = 0; i < 2; i++) {
    const result = await productGuard(new Request("http://localhost/api/banks"));
    expect(result?.status).toBe(503);
    expect(await result?.json()).toEqual({ code: "PRODUCT_CONFIG_UNAVAILABLE", error: "PRODUCT_CONFIG_UNAVAILABLE" });
  }
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("returns non-secret current configuration without caching", async () => {
  vi.stubEnv("contextdb_name", "contextdb");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ product_config_version: 1, contextdb_name: "contextdb" })));
  const response = await productConfigRoute();
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(await response.json()).toEqual({ product_config_version: 1, contextdb_name: "contextdb" });
});
