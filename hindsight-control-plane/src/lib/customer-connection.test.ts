import { afterEach, expect, it, vi } from "vitest";
import { execFileSync } from "node:child_process";
import { customerConnection } from "./customer-connection";

afterEach(() => vi.unstubAllEnvs());

it("quotes bank names and signed package URLs as single shell arguments", () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com/api/");
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "https://mcp.example.com/mcp/");
  const url = "https://downloads.example.com/client.tgz?sig=a&value=$HOME";
  vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_PACKAGE_URL", url);
  const bank = "team's bank $(exit 73)";
  const result = customerConnection(bank);
  // Exercise the generated Bash command with an argv-recording npm, never a network install.
  const output = execFileSync(
    "bash",
    ["-c", 'npm() { printf "%s\\n" "$@"; };\n' + result.bashInstall],
    { encoding: "utf8" }
  );
  expect(output.split("\n")).toContain(`--package=${url}`);
  expect(output.split("\n")).toContain(bank);
  expect(result.powershellInstall).toContain("'team''s bank $(exit 73)'");
  expect(result.apiUrl).toBe("https://api.example.com/api");
  expect(result.mcpUrl).toBe("https://mcp.example.com/mcp/");
});

it.each([
  "http://localhost:8888",
  "https://admin:secret@service.example",
  "https://api.example.com?token=secret",
  "not-a-url",
])("rejects invalid public API address %s", (url) => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", url);
  expect(customerConnection("bank").apiUrl).toBeUndefined();
  expect(customerConnection("bank").bashInstall).toBeUndefined();
});

it.each(["http://downloads.example.com/client.tgz", "https://downloads.example.com/client.zip"])(
  "does not install an invalid package URL %s",
  (url) => {
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com");
    vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_PACKAGE_URL", url);
    expect(customerConnection("bank").bashInstall).toBeUndefined();
  }
);
