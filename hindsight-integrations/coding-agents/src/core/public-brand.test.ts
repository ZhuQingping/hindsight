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
  expect(injected).toContain("<agentstratum_memory>");
  expect(injected).not.toMatch(/hindsight/i);
  expect(stripInjectedMemory(customerText + injected)).toBe(customerText);
  expect(buildSystemInjection(customerText)).toContain(customerText);
});

it("returns customer content verbatim and sanitizes only dependency diagnostics", async () => {
  const client = {
    getPage: vi.fn().mockResolvedValue({ body: customerText }),
  } as unknown as HindsightClient;
  const tool = buildKnowledgeTools(client, "b").find(
    (t) => t.name === "agentstratum_read_knowledge_page"
  )!;
  expect((await tool.handler({ page_id: "p" })).content[0].text).toContain(customerText);
  vi.mocked(client.getPage).mockRejectedValue(new Error("hindsight_api: invalid configuration"));
  const failed = await tool.handler({ page_id: "p" });
  expect(failed.isError).toBe(true);
  expect(JSON.stringify(failed)).not.toMatch(/hindsight/i);
});

it("does not send credentials to an implicit cloud endpoint", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const client = new HindsightClient({ apiUrl: "", apiToken: "secret", bank: "b" });
  await expect(client.req("GET", "/version")).rejects.toThrow("AGENTSTRATUM_API_URL");
  expect(fetch).not.toHaveBeenCalled();
});

it("does not query a publication namespace until one is configured", async () => {
  vi.stubEnv("AGENTSTRATUM_CODING_AGENTS_PACKAGE", "");
  const npmView = vi.fn();
  try {
    expect(await maybeAutoUpdate({ autoUpdate: true }, { npmView })).toBe("");
    expect(npmView).not.toHaveBeenCalled();
  } finally {
    vi.unstubAllEnvs();
  }
});
