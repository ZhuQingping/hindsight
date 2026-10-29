// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { ClientConnectionSetup } from "@/components/client-connection-setup";
import type { CustomerConnection } from "@/lib/customer-connection";
import messages from "@/messages/en.json";
import zhMessages from "@/messages/zh-CN.json";
import { codingClients } from "@/lib/connection-examples";

vi.mock("@/components/connection-code", () => ({
  ConnectionCode: ({ code }: { code: string }) => <pre>{code}</pre>,
}));
afterEach(cleanup);
const connection: CustomerConnection = {
  apiUrl: "https://api.example.com/customer-api",
  mcpUrl: "https://mcp.example.com/team/mcp",
  codingAgentsNpm: "contextbase-coding-agents@1.0.0",
  packages: {
    codingAgents: "https://downloads.example.com/agents.tgz",
    openclaw: "https://downloads.example.com/openclaw.tgz",
    hermes: "https://downloads.example.com/hermes.zip",
    python: "https://downloads.example.com/contextbase_client-1.0.0-py3-none-any.whl",
    node: "https://downloads.example.com/contextbase-client-1.0.0.tgz",
  },
};
function show(config = connection) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ClientConnectionSetup bankId="team" connection={config} />
    </NextIntlClientProvider>
  );
}
function select(value: string) {
  fireEvent.change(screen.getByLabelText("Client"), { target: { value } });
}

it.each(codingClients)(
  "shows a separate install and truthful local diagnosis for $name",
  ({ id }) => {
    show();
    select(id);
    expect(document.body.textContent).toContain(`install ${id} --api-url`);
    expect(document.body.textContent).toContain(`harness = ${id}`);
    expect(document.body.textContent).toContain("config.api_url");
    expect(document.body.textContent).toContain("not cloud permissions");
    expect(document.body.textContent).not.toMatch(/ContextBaseClient|from contextbase_client/);
    const primary = Array.from(document.querySelectorAll("pre")).find((pre) =>
      pre.textContent?.includes("npx.cmd --yes")
    );
    expect(primary?.textContent).toContain(`contextbase-coding-agents@1.0.0' install ${id}`);
    expect(primary?.textContent).not.toContain("downloads.example.com");
  }
);

it("switches terminal syntax without showing other terminal commands", () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "CMD" }));
  expect(document.body.textContent).toContain('set "CONTEXTBASE_API_TOKEN=<API_KEY>"');
  expect(document.body.textContent).not.toContain("$env:");
  fireEvent.click(screen.getByRole("button", { name: "macOS / Linux" }));
  expect(document.body.textContent).toContain("export CONTEXTBASE_API_TOKEN=");
  expect(document.body.textContent).not.toContain("npm.cmd");
});

it.each(["openclaw", "hermes"])(
  "shows the independent %s plugin and configured download",
  (client) => {
    show();
    select(client);
    expect(document.body.textContent).not.toContain("contextbase-coding-agents install");
    expect(
      screen.getByRole("link", { name: "Download installation package ↗" }).getAttribute("href")
    ).toBe(connection.packages[client as "openclaw" | "hermes"]);
    if (client === "hermes") {
      expect(document.body.textContent).toContain("HERMES_HOME");
      expect(document.body.textContent).toContain("hermes memory setup");
    } else {
      expect(document.body.textContent).toContain("Gateway process environment");
      expect(document.body.textContent).toContain('"dynamicBankId": false');
    }
  }
);

it.each(["python", "node", "rest", "mcp"])(
  "shows only the selected development example: %s",
  (client) => {
    show();
    fireEvent.click(screen.getByRole("button", { name: "Application development" }));
    select(client);
    const text = document.body.textContent!;
    expect(text).not.toContain("contextbase-coding-agents install");
    if (client === "python") expect(text).toContain("from contextbase_client import ContextBase");
    if (client === "node") expect(text).toContain("new ContextBaseClient");
    if (client === "rest") expect(text).toContain("/v1/default/banks/team/stats");
    if (client === "mcp") {
      expect(text).toContain('"mcpServers"');
      expect(screen.queryByRole("button", { name: "CMD" })).toBeNull();
    }
    expect(text).not.toMatch(/\.retain\(|hindsight/i);
  }
);

it("keeps clients selectable when one package is unavailable", () => {
  show({ ...connection, packages: { ...connection.packages, openclaw: undefined } });
  select("openclaw");
  expect(screen.getByRole("status").textContent).toContain("installation package is not available");
  expect(screen.queryByRole("link", { name: "Download installation package ↗" })).toBeNull();
  expect(document.querySelectorAll("pre")).toHaveLength(0);
  select("codex");
  expect(document.body.textContent).toContain("install codex --api-url");
});

it("offers PowerShell when bank data cannot be safely copied into CMD", () => {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ClientConnectionSetup bankId="team%secret%" connection={connection} />
    </NextIntlClientProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "CMD" }));
  expect(screen.getByRole("status").textContent).toContain("Switch to PowerShell");
  fireEvent.click(screen.getByRole("button", { name: "PowerShell" }));
  expect(document.body.textContent).toContain("--bank-id 'team%secret%'");
});

it("renders Chinese instructions and all dynamic translation paths without missing messages", () => {
  const errors: unknown[] = [];
  render(
    <NextIntlClientProvider
      locale="zh-CN"
      messages={zhMessages}
      onError={(error) => errors.push(error)}
    >
      <ClientConnectionSetup bankId="team" connection={connection} />
    </NextIntlClientProvider>
  );
  const picker = screen.getByLabelText("客户端");
  for (const id of [...codingClients.map((client) => client.id), "openclaw", "hermes"])
    fireEvent.change(picker, { target: { value: id } });
  fireEvent.click(screen.getByRole("button", { name: "应用开发" }));
  for (const id of ["python", "node", "rest", "mcp"])
    fireEvent.change(picker, { target: { value: id } });
  expect(errors).toEqual([]);
  expect(document.body.textContent).not.toMatch(/hindsight/i);
});

it("shows the public endpoint and bank and regenerates commands for the customer's path", () => {
  show();
  const endpoint = screen.getByLabelText("API Endpoint") as HTMLInputElement;
  const bank = screen.getByLabelText("Bank ID") as HTMLInputElement;
  expect(endpoint.value).toBe(connection.apiUrl);
  expect(endpoint.readOnly).toBe(true);
  expect(bank.value).toBe("team");
  expect(bank.readOnly).toBe(true);
  const path = "D:\\code\\客户项目";
  fireEvent.change(screen.getByLabelText("Project path"), { target: { value: path } });
  expect(document.body.textContent).toContain(`--project-path '${path}'`);
  fireEvent.click(screen.getByRole("button", { name: "CMD" }));
  expect(document.body.textContent).toContain(`--project-path "${path}"`);
});

it("does not offer a copied install command for an empty project path", () => {
  show();
  fireEvent.change(screen.getByLabelText("Project path"), { target: { value: "" } });
  expect(screen.getByRole("status").textContent).toContain("Enter a project path");
  expect(document.querySelectorAll("pre")).toHaveLength(0);
  fireEvent.change(screen.getByLabelText("Project path"), { target: { value: "." } });
  expect(document.body.textContent).toContain("npx.cmd --yes");
});

it("keeps the archive as a collapsed alternative to the npm command", () => {
  show();
  const summary = screen.getByText("Alternative: install from a downloaded package");
  expect(summary.closest("details")?.open).toBe(false);
  fireEvent.click(summary);
  expect(
    screen.getByRole("link", { name: "Download installation package ↗" }).getAttribute("href")
  ).toBe(connection.packages.codingAgents);
});

it("can connect through npm when no archive download is configured", () => {
  show({ ...connection, packages: {} });
  expect(document.body.textContent).toContain("npx.cmd --yes");
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByText("Alternative: install from a downloaded package")).toBeNull();
});

it("uses the configured archive when npm distribution is disabled", () => {
  show({ ...connection, codingAgentsNpm: undefined });
  expect(document.body.textContent).toContain("npm.cmd exec --yes");
  expect(document.body.textContent).not.toContain("npx.cmd");
  expect(
    screen.getByRole("link", { name: "Download installation package ↗" }).getAttribute("href")
  ).toBe(connection.packages.codingAgents);
});
