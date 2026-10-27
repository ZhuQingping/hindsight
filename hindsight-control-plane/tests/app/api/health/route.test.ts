import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
const { listBanks } = vi.hoisted(() => ({ listBanks: vi.fn() }));
vi.mock("contextbase-client", () => ({
  createClient: (config: unknown) => config,
  createConfig: (config: unknown) => config,
  sdk: { listBanks },
}));
vi.mock("@/lib/contextbase-client", () => ({ getDataplaneHeaders: () => ({}) }));
import { GET } from "@/app/api/health/route";
beforeEach(() => {
  listBanks.mockReset();
  vi.stubEnv("contextdb_name", "contextbase");
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://hindsight-api.internal:8888");
  vi.spyOn(console, "error").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});
it.each(["contextbase", "contextdb"])(
  "exposes deployment %s identity without internal backend URL",
  async (name) => {
    vi.stubEnv("contextdb_name", name);
    listBanks.mockResolvedValue({ data: { banks: [] } });
    const response = await GET();
    expect(await response.json()).toEqual({
      status: "ok",
      service: `${name}-control-plane`,
      dataplane: { status: "connected" },
    });
  }
);
it.each(["sdk error", "exception"])("keeps %s diagnostics internal", async (failure) => {
  if (failure === "sdk error")
    listBanks.mockResolvedValue({ error: { detail: "ContextBase failed" } });
  else listBanks.mockRejectedValue(new Error("connect hindsight-api.internal failed"));
  const response = await GET();
  const body = await response.json();
  expect(body.dataplane).toEqual({ status: "disconnected", error: "Backend unavailable" });
  expect(JSON.stringify(body)).not.toMatch(/hindsight/i);
});
