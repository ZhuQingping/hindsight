// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import ConnectPage from "@/app/[locale]/connect/page";

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

it.each(["agentstratum", "contextdb"])(
  "keeps the MCP Endpoint independent and alias fixed under %s",
  async (name) => {
    vi.stubEnv("contextdb_name", name);
    const bank = "team/%-中文.json";
    render(await ConnectPage({ searchParams: Promise.resolve({ bank_id: bank }) }));
    const snippet = Array.from(document.querySelectorAll("pre")).find((node) =>
      node.textContent?.includes('"mcpServers"')
    )!;
    const configuration = JSON.parse(snippet.textContent!);
    expect(Object.keys(configuration.mcpServers)).toEqual(["agentstratum"]);
    expect(configuration.mcpServers.agentstratum.url).toBe("<MCP_ENDPOINT>");
    expect(snippet.textContent).not.toContain("API_BASE_URL");
    expect(snippet.textContent).not.toContain("/mcp/");
    expect(configuration.mcpServers.agentstratum.headers.Authorization).toBe("Bearer <API_KEY>");
    expect(screen.getByText("mcpEndpointHelp")).toBeTruthy();
    expect(document.body.textContent).toContain(encodeURIComponent(bank));
  }
);
