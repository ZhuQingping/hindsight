import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { resolveApiErrorLocale } from "@/lib/i18n/api-errors";

const { createOrUpdateBank } = vi.hoisted(() => ({ createOrUpdateBank: vi.fn() }));
vi.mock("@/lib/contextbase-client", () => ({
  sdk: { createOrUpdateBank },
  lowLevelClient: {},
}));
import { POST } from "@/app/api/banks/route";

beforeEach(() => {
  vi.stubEnv("CONTEXTBASE_CP_CONTEXTDB_ENABLED", "false");
  vi.spyOn(console, "error").mockImplementation(() => {});
  createOrUpdateBank.mockResolvedValue({
    error: { detail: "synthetic denied" },
    response: new Response(null, { status: 403 }),
  });
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

it.each(["zh-TW", "yue-Hant", "de", "ja", "en"])(
  "uses the same English fallback for %s page copy and a real BFF error",
  async (locale) => {
    expect(
      resolveApiErrorLocale({ headers: new Headers({ Cookie: `NEXT_LOCALE=${locale}` }) })
    ).toBe("en");
    const response = await POST(
      new Request("http://localhost/api/banks", {
        method: "POST",
        headers: { "Content-Type": "application/json", Cookie: `NEXT_LOCALE=${locale}` },
        body: JSON.stringify({ bank_id: "workspace-id" }),
      })
    );
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ error: "Failed to create Workspace" });
  }
);
it("keeps Simplified Chinese workspace errors", async () => {
  const response = await POST(
    new Request("http://localhost/api/banks", {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: "NEXT_LOCALE=zh-CN" },
      body: JSON.stringify({ bank_id: "workspace-id" }),
    })
  );
  expect(await response.json()).toMatchObject({ error: "创建工作空间失败" });
});
