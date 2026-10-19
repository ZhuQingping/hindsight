import { afterEach, expect, it, vi } from "vitest";
import { buildSystemInjection } from "./inject";
import { stripInjectedMemory } from "./transcript-util";
import { buildKnowledgeTools } from "./knowledge-tools";
import { HindsightClient } from "./hindsight";
import { maybeAutoUpdate } from "./auto-update";

const customerText = "Customer document: hindsight Hindsight HINDSIGHT must stay unchanged.";
afterEach(() => vi.unstubAllGlobals());

it("strips the generated prompt wrapper without rewriting customer text", () => {
  const injected = buildSystemInjection("retrieved context");
  expect(injected).toContain("<contextbase_memory>");
  expect(injected).not.toMatch(/hindsight/i);
  expect(stripInjectedMemory(customerText + injected)).toBe(customerText);
  expect(buildSystemInjection(customerText)).toContain(customerText);
});

it("preserves customer content and actionable service errors", async () => {
  const client = {
    getPage: vi.fn().mockResolvedValue({ body: customerText }),
  } as unknown as HindsightClient;
  const tool = buildKnowledgeTools(client, "b").find(
    (t) => t.name === "contextbase_read_knowledge_page"
  )!;
  expect((await tool.handler({ page_id: "p" })).content[0].text).toContain(customerText);
  vi.mocked(client.getPage).mockRejectedValue(
    new Error("HTTP 403: access denied to bank hindsight-review")
  );
  const failed = await tool.handler({ page_id: "p" });
  expect(failed.isError).toBe(true);
  expect(failed.content[0].text).toContain("HTTP 403: access denied to bank hindsight-review");
});

it("does not send credentials to an implicit cloud endpoint", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const client = new HindsightClient({ apiUrl: "", apiToken: "secret", bank: "b" });
  await expect(client.req("GET", "/version")).rejects.toThrow("CONTEXTBASE_API_URL");
  expect(fetch).not.toHaveBeenCalled();
});

it("does not query a publication namespace until one is configured", async () => {
  vi.stubEnv("CONTEXTBASE_CODING_AGENTS_PACKAGE", "");
  const npmView = vi.fn();
  try {
    expect(await maybeAutoUpdate({ autoUpdate: true }, { npmView })).toBe("");
    expect(npmView).not.toHaveBeenCalled();
  } finally {
    vi.unstubAllEnvs();
  }
});
