import { afterEach, expect, it, vi } from "vitest";
import { customerConnection } from "./customer-connection";

afterEach(() => vi.unstubAllEnvs());

it("only exposes public addresses and independently configured packages", () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com/customer-api/");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "https://mcp.example.com/banks/{bank_id}/mcp");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://private-service:8888");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "operator-secret");
  vi.stubEnv(
    "CONTEXTBASE_CP_CODING_AGENTS_PACKAGE_URL",
    "https://downloads.example.com/agents.tgz?sig=a&value=$HOME"
  );
  const bank = "team/%-中文.json";
  const result = customerConnection(bank);
  expect(result.apiUrl).toBe("https://api.example.com/customer-api");
  expect(result.mcpUrl).toBe(`https://mcp.example.com/banks/${encodeURIComponent(bank)}/mcp`);
  expect(result.packages.codingAgents).toBe(
    "https://downloads.example.com/agents.tgz?sig=a&value=$HOME"
  );
  expect(result.packages.openclaw).toBeUndefined();
  expect(JSON.stringify(result)).not.toMatch(/private-service|operator-secret/);
});

it.each([
  "http://localhost:8888",
  "https://admin:secret@service.example",
  "https://api.example.com?token=secret",
  "https://api.example.com/#fragment",
  "https://api.example.com/\npath",
  "not-a-url",
])("rejects invalid public API address %s", (url) => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", url);
  expect(customerConnection("bank").apiUrl).toBeUndefined();
});

const downloads = [
  ["CODING_AGENTS_PACKAGE_URL", "codingAgents", ".tgz"],
  ["OPENCLAW_PACKAGE_URL", "openclaw", ".tgz"],
  ["HERMES_PACKAGE_URL", "hermes", ".zip"],
  ["PYTHON_SDK_PACKAGE_URL", "python", ".whl"],
  ["NODE_SDK_PACKAGE_URL", "node", ".tgz"],
] as const;

it.each(downloads)(
  "validates %s as an install file, allowing signed downloads",
  (env, field, extension) => {
    const valid = `https://downloads.example.com/client${extension}?sig=a%2Fb&expiry=123`;
    vi.stubEnv(`CONTEXTBASE_CP_${env}`, valid);
    expect(customerConnection("bank").packages[field]).toBe(valid);
    for (const url of [
      "http://downloads.example.com/client" + extension,
      "https://downloads.example.com/actions/123",
      `https://user:secret@downloads.example.com/client${extension}`,
      `https://downloads.example.com/client${extension}#fragment`,
      `https://downloads.example.com/cl\nient${extension}`,
    ]) {
      vi.stubEnv(`CONTEXTBASE_CP_${env}`, url);
      expect(customerConnection("bank").packages[field]).toBeUndefined();
    }
  }
);

it("never derives MCP from the REST endpoint or an internal address", () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "");
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_MCP_URL", "https://legacy.example.com/mcp");
  expect(customerConnection("bank").mcpUrl).toBeUndefined();
});
