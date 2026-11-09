import { afterEach, expect, it, vi } from "vitest";
import { customerConnection } from "./customer-connection";

afterEach(() => vi.unstubAllEnvs());

it("derives the public API from the browser origin and published port when unset", () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", undefined);
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_API_URL", undefined);
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", "8888");
  expect(customerConnection("bank", { uiOrigin: "http://192.0.2.10:9999" }).apiUrl).toBe(
    "http://192.0.2.10:8888"
  );
});

it("only exposes public addresses and independently configured packages", () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com/customer-api/");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "https://mcp.example.com/banks/{bank_id}/mcp");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://private-service:8888");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "operator-secret");
  const bank = "team/%-中文.json";
  const result = customerConnection(bank);
  expect(result.apiUrl).toBe("https://api.example.com/customer-api");
  expect(result.mcpUrl).toBe(`https://mcp.example.com/banks/${encodeURIComponent(bank)}/mcp`);
  expect(result.codingAgentsNpm).toBe("@huaweicloud/contextbase-coding-agents@latest");
  expect(result.packages.openclaw).toBeUndefined();
  expect(JSON.stringify(result)).not.toMatch(/private-service|operator-secret/);
});

it.each([
  "https://admin:secret@service.example",
  "https://api.example.com?token=secret",
  "https://api.example.com/#fragment",
  "https://api.example.com/\npath",
  "not-a-url",
])("rejects invalid public API address %s", (url) => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", url);
  expect(customerConnection("bank").apiUrl).toBeUndefined();
});

it("allows http for the public API address in development, rejects it in production", () => {
  const url = "http://localhost:8888";
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", url);
  vi.stubEnv("NODE_ENV", "development");
  expect(customerConnection("bank").apiUrl).toBe(url);
  vi.stubEnv("NODE_ENV", "production");
  expect(customerConnection("bank").apiUrl).toBeUndefined();
});

const downloads = [
  ["OPENCLAW_PACKAGE_URL", "openclaw", ".tgz"],
  ["HERMES_PACKAGE_URL", "hermes", ".zip"],
  ["PYTHON_SDK_PACKAGE_URL", "python", ".whl"],
] as const;

it.each(downloads)(
  "validates %s as an install file, allowing signed downloads",
  (env, field, extension) => {
    // Package distribution always requires HTTPS, even in development.
    vi.stubEnv("NODE_ENV", "production");
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

it("does not invent package download URLs when deployment settings are unset", () => {
  vi.stubEnv("NODE_ENV", "development");
  const development = customerConnection("bank");
  expect(development.packages.openclaw).toBeUndefined();
  expect(development.packages.hermes).toBeUndefined();
  expect(development.packages.python).toBeUndefined();

  vi.stubEnv("NODE_ENV", "production");
  const production = customerConnection("bank");
  expect(production.packages.openclaw).toBeUndefined();
  expect(production.packages.hermes).toBeUndefined();
  expect(production.packages.python).toBeUndefined();
});

it.each([
  "@huaweicloud/contextbase-coding-agents@latest",
  "@contextbase/contextbase-coding-agents@latest",
  "@huaweicloud/contextbase-coding-agents@1.0.0",
  "@contextbase/contextbase-coding-agents@2.1.0-rc.1",
])("exposes a configured latest or fixed-version registry package: %s", (spec) => {
  vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE", spec);
  expect(customerConnection("bank").codingAgentsNpm).toBe(spec);
});

it.each([
  "@huaweicloud/contextbase-coding-agents@beta",
  "contextbase-coding-agents",
  "https://example.com/client.tgz",
  "file:../client",
  "pkg@npm:other@1.0.0",
  "client@1.0.0\n--ignore-scripts",
  "client@1.0.0;echo secret",
])("does not expose an unsupported npm reference: %s", (spec) => {
  vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE", spec);
  expect(customerConnection("bank").codingAgentsNpm).toBeUndefined();
});

it.each([undefined, "", "  "])("defaults to latest when the npm setting is %s", (setting) => {
  vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE", setting);
  vi.stubEnv("HINDSIGHT_CP_CODING_AGENTS_NPM_PACKAGE", undefined);
  const config = customerConnection("bank");
  expect(config.codingAgentsNpm).toBe("@huaweicloud/contextbase-coding-agents@latest");
  expect(Object.keys(config.packages)).toEqual(["openclaw", "hermes", "python"]);
});

it.each(["", "invalid", "https://admin:secret@api.example"])(
  "never derives or falls back to a legacy alias when explicit URL is %s",
  (value) => {
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", value);
    vi.stubEnv("HINDSIGHT_CP_PUBLIC_API_URL", "https://legacy.example.com");
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", "8888");
    expect(
      customerConnection("bank", { uiOrigin: "http://public.test:9999" }).apiUrl
    ).toBeUndefined();
  }
);

it.each([
  ["http://public.test:9999", "http://public.test:8888", true],
  ["http://public.test:9999", "http://other.test:8888", false],
  ["https://public.test:9999", "http://public.test:8888", false],
  ["http://public.test:9999", "https://api.test", true],
])("production endpoint %s -> %s respects same-host HTTP", (uiOrigin, endpoint, valid) => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", endpoint);
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", endpoint + "/mcp");
  const result = customerConnection("bank", { uiOrigin });
  expect(result.apiUrl).toBe(valid ? endpoint : undefined);
  expect(result.mcpUrl).toBe(valid ? endpoint + "/mcp" : undefined);
});

it("explicit public API wins and derived examples never expose private endpoints or packages", () => {
  vi.stubEnv("NODE_ENV", "production");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://explicit.test/api/");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", "8888");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://private-service:8888");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "operator-secret");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "");
  vi.stubEnv("CONTEXTBASE_CP_OPENCLAW_PACKAGE_URL", "http://public.test/client.tgz");
  const context = { uiOrigin: "http://public.test:9999" };
  expect(customerConnection("bank", context).apiUrl).toBe("https://explicit.test/api");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", undefined);
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_API_URL", undefined);
  const result = customerConnection("bank", context);
  expect(result.apiUrl).toBe("http://public.test:8888");
  expect(result.mcpUrl).toBeUndefined();
  expect(result.packages.openclaw).toBeUndefined();
  expect(JSON.stringify(result)).not.toMatch(/private-service|operator-secret/);
});
