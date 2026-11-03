// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import ConnectPage from "@/app/[locale]/connect/page";
import messages from "@/messages/en.json";

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
async function show(bank: string | string[] | undefined) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {await ConnectPage({ searchParams: Promise.resolve({ bank_id: bank }) })}
    </NextIntlClientProvider>
  );
}

it.each(["contextbase", "contextdb"])(
  "keeps public MCP independent and operator credentials private under %s",
  async (name) => {
    vi.stubEnv("contextdb_name", name);
    vi.stubEnv(
      "CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE",
      "@huaweicloud/contextbase-coding-agents@1.1.0"
    );
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com/customer-api");
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_MCP_URL", "https://mcp.example.com/banks/{bank_id}/mcp");
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://internal-service:8888");
    vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "operator-secret");
    const bank = "team/%-中文.json";
    await show(bank);
    expect(document.body.textContent).toContain("install claude-code --bank-id");
    expect(document.body.textContent).toContain("npx.cmd --yes");
    expect(document.body.textContent).toContain(bank);
    const command = Array.from(document.querySelectorAll("pre")).find((node) =>
      node.textContent?.includes("npx.cmd")
    )!;
    expect(command.textContent).toContain("'@huaweicloud/contextbase-coding-agents@1.1.0'");
    expect(command.textContent).not.toMatch(
      /--project-path|--api-url|--api-token|CONTEXTBASE_API_/
    );
    expect(screen.getByText(/^--api-url: API address/).textContent).toContain(
      "https://api.example.com/customer-api"
    );
    expect(document.body.textContent).not.toMatch(/internal-service|operator-secret/);
    expect(command.textContent).toContain("--bank-id '" + bank + "'");
    expect(document.body.textContent).not.toContain("install claude-code codex");
    fireEvent.click(screen.getByRole("button", { name: "Application development" }));
    fireEvent.change(screen.getByLabelText("Client"), { target: { value: "mcp" } });
    const snippet = Array.from(document.querySelectorAll("pre")).find((node) =>
      node.textContent?.includes('"mcpServers"')
    )!;
    const config = JSON.parse(snippet.textContent!);
    expect(Object.keys(config.mcpServers)).toEqual(["contextbase"]);
    expect(config.mcpServers.contextbase.url).toBe(
      `https://mcp.example.com/banks/${encodeURIComponent(bank)}/mcp`
    );
    expect(config.mcpServers.contextbase.headers).toEqual({
      Authorization: "Bearer <API_KEY>",
      "X-Bank-Id": bank,
    });
    expect(document.body.textContent).not.toMatch(
      /internal-service|operator-secret|npm.cmd exec|npx.cmd/
    );
  }
);

it("offers the installer but requires a public endpoint for REST examples", async () => {
  for (const key of ["PUBLIC_API_URL", "PUBLIC_MCP_URL"]) {
    vi.stubEnv(`CONTEXTBASE_CP_${key}`, "");
    vi.stubEnv(`HINDSIGHT_CP_${key}`, "");
  }
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "http://private-api:8888");
  await show("bank");
  expect(document.body.textContent).toContain("npx.cmd --yes");
  fireEvent.click(screen.getByRole("button", { name: "Application development" }));
  fireEvent.change(screen.getByLabelText("Client"), { target: { value: "rest" } });
  expect(screen.getByRole("status").textContent).toContain("API address is not available");
  expect(document.querySelectorAll("pre")).toHaveLength(0);
  expect(document.body.textContent).not.toMatch(/localhost|private-api/);
});

it.each([undefined, ["one", "two"]])(
  "requires an unambiguous bank before providing instructions",
  async (bank) => {
    await show(bank);
    expect(screen.getByText("chooser")).toBeTruthy();
    expect(screen.queryByLabelText("Client")).toBeNull();
  }
);

it("uses latest without npm or download settings when the public API is configured", async () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_URL", "https://api.example.com");
  vi.stubEnv("CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE", undefined);
  vi.stubEnv("HINDSIGHT_CP_CODING_AGENTS_NPM_PACKAGE", undefined);
  await show("team");
  expect(document.body.textContent).toContain("contextbase-coding-agents@latest");
  expect(document.body.textContent).toContain("npx.cmd --yes");
  expect(screen.queryByRole("link", { name: "Download installation package ↗" })).toBeNull();
});
