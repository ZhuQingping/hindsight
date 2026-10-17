import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { messageLocale } from "@/i18n/config";

const { createOrUpdateBank } = vi.hoisted(() => ({ createOrUpdateBank: vi.fn() }));
vi.mock("@/lib/hindsight-client", () => ({
  sdk: { createOrUpdateBank },
  lowLevelClient: {},
}));
import { POST } from "@/app/api/banks/route";

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  createOrUpdateBank.mockResolvedValue({
    error: { detail: "synthetic denied" },
    response: new Response(null, { status: 403 }),
  });
});
afterEach(() => vi.restoreAllMocks());

it.each(["zh-TW", "yue-Hant", "de", "ja", "en"])(
  "uses the same English fallback for %s page copy and a real BFF error",
  async (locale) => {
    expect(messageLocale(locale)).toBe("en");
    const response = await POST(new Request("http://localhost/api/banks", {
      method: "POST",
      headers: { "Content-Type": "application/json", Cookie: `NEXT_LOCALE=${locale}` },
      body: JSON.stringify({ bank_id: "workspace-id" }),
    }));
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ error: "Failed to create Workspace" });
  }
);
it("keeps Simplified Chinese workspace errors", async () => {
  expect(messageLocale("zh-CN")).toBe("zh-CN");
  const response = await POST(new Request("http://localhost/api/banks", {
    method: "POST",
    headers: { "Content-Type": "application/json", Cookie: "NEXT_LOCALE=zh-CN" },
    body: JSON.stringify({ bank_id: "workspace-id" }),
  }));
  expect(await response.json()).toMatchObject({ error: "创建工作空间失败" });
});
