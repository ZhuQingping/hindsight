// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import ConnectPage from "@/app/[locale]/connect/page";

vi.mock("@/components/connect-bank-chooser", () => ({
  ConnectBankChooser: () => <div>chooser</div>,
}));
vi.mock("next-intl/server", () => ({ getTranslations: async () => (key: string) => key }));
vi.mock("@/i18n/navigation", () => ({ Link: (props: ComponentProps<"a">) => <a {...props} /> }));
vi.mock("@/components/resource-page-shell", () => ({
  ResourcePageShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/components/connection-code", () => ({
  ConnectionCode: ({ code }: { code: string }) => <pre>{code}</pre>,
}));
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

it.each(["contextbase", "contextdb"])(
  "keeps the MCP Endpoint independent and alias fixed under %s",
  async (name) => {
    vi.stubEnv("contextdb_name", name);
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com");
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "https://mcp.example.com/banks/{bank_id}/mcp");
    vi.stubEnv(
      "CONTEXTBASE_CP_CODING_AGENTS_PACKAGE_URL",
      "https://downloads.example.com/agents-0.8.2.tgz"
    );
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://internal-service:8888");
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "operator-secret");
    const bank = "team/%-中文.json";
    render(await ConnectPage({ searchParams: Promise.resolve({ bank_id: bank }) }));
    const snippet = Array.from(document.querySelectorAll("pre")).find((node) =>
      node.textContent?.includes('"mcpServers"')
    )!;
    const configuration = JSON.parse(snippet.textContent!);
    expect(Object.keys(configuration.mcpServers)).toEqual(["contextbase"]);
    expect(configuration.mcpServers.contextbase.url).toBe(
      `https://mcp.example.com/banks/${encodeURIComponent(bank)}/mcp`
    );
    expect(configuration.mcpServers.contextbase.headers["X-Bank-Id"]).toBe(bank);
    expect(snippet.textContent).not.toContain("API_BASE_URL");

    expect(configuration.mcpServers.contextbase.headers.Authorization).toBe("Bearer <API_KEY>");
    expect(screen.getByText("mcpEndpointHelp")).toBeTruthy();
    expect(document.body.textContent).toContain(encodeURIComponent(bank));
    expect(document.body.textContent).toContain("npm.cmd exec --yes");
    expect(document.body.textContent).toContain("--bank-id '" + bank + "'");
    expect(document.body.textContent).toContain("--project-path '.'");
    expect(document.body.textContent).not.toContain("internal-service");
    expect(document.body.textContent).not.toContain("operator-secret");
    expect(document.body.textContent).not.toContain("npx contextbase-coding-agents");
  }
);

it("does not offer localhost or placeholder install commands when customer addresses are missing", async () => {
  for (const key of ["PUBLIC_API_URL", "PUBLIC_MCP_URL", "CODING_AGENTS_PACKAGE_URL"]) {
    vi.stubEnv(`CONTEXTBASE_CP_${key}`, "");
    vi.stubEnv(`HINDSIGHT_CP_${key}`, "");
  }
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://private-api:8888");
  render(await ConnectPage({ searchParams: Promise.resolve({ bank_id: "bank" }) }));
  expect(screen.getAllByText("connectionUnavailable").length).toBeGreaterThan(0);
  expect(document.querySelectorAll("pre")).toHaveLength(0);
  expect(document.body.textContent).not.toContain("localhost");
  expect(document.body.textContent).not.toContain("private-api");
});
