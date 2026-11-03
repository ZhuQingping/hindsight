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
  codingAgentsNpm: "@huaweicloud/contextbase-coding-agents@latest",
  packages: {
    openclaw: "https://downloads.example.com/openclaw.tgz",
    hermes: "https://downloads.example.com/hermes.zip",
    python: "https://downloads.example.com/contextbase_client-1.0.0-py3-none-any.whl",
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
    expect(document.body.textContent).toContain(`install ${id} --bank-id`);
    expect(document.body.textContent).toContain(`harness = ${id}`);
    expect(document.body.textContent).toContain("config.api_url");
    expect(document.body.textContent).toContain("not cloud permissions");
    expect(document.body.textContent).not.toMatch(/ContextBaseClient|from contextbase_client/);
    const primary = Array.from(document.querySelectorAll("pre")).find((pre) =>
      pre.textContent?.includes("npx.cmd --yes")
    );
    expect(primary?.textContent).toContain(`contextbase-coding-agents@latest' install ${id}`);
    expect(primary?.textContent).not.toContain("downloads.example.com");
  }
);

it("switches terminal syntax without showing other terminal commands", () => {
  show();
  fireEvent.click(screen.getByRole("button", { name: "CMD" }));
  expect(document.body.textContent).toContain(
    'npx.cmd --yes "@huaweicloud/contextbase-coding-agents@latest"'
  );
  expect(document.body.textContent).not.toContain("$env:");
  fireEvent.click(screen.getByRole("button", { name: "macOS / Linux" }));
  expect(document.body.textContent).toContain(
    "npx --yes '@huaweicloud/contextbase-coding-agents@latest'"
  );
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
      expect(document.body.textContent).not.toContain("dynamicBankId");
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
  expect(document.body.textContent).toContain("install codex --bank-id");
});

it("offers PowerShell for Bank IDs that CMD would expand", () => {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <ClientConnectionSetup bankId="team%secret%" connection={connection} />
    </NextIntlClientProvider>
  );
  fireEvent.click(screen.getByRole("button", { name: "CMD" }));
  expect(screen.getByRole("status").textContent).toContain("Switch to PowerShell");
  fireEvent.click(screen.getByRole("button", { name: "PowerShell" }));
  const command = Array.from(document.querySelectorAll("pre")).find((node) =>
    node.textContent?.includes("npx.cmd")
  )!;
  expect(command.textContent).toContain("--bank-id 'team%secret%'");
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
  expect(screen.getByRole("heading", { name: "可选参数" })).toBeTruthy();
  expect(document.body.textContent).not.toMatch(
    /首次可按提示输入|覆盖已有地址时请显式指定|仅用于指定项目级客户端注册目录|首次使用需提供密钥|覆盖已有密钥时请显式指定|API 地址（/
  );
  expect(document.body.textContent).toContain("--project-path：可选，默认当前目录。");
  for (const id of [...codingClients.map((client) => client.id), "openclaw", "hermes"])
    fireEvent.change(picker, { target: { value: id } });
  fireEvent.click(screen.getByRole("button", { name: "应用开发" }));
  for (const id of ["python", "node", "rest", "mcp"])
    fireEvent.change(picker, { target: { value: id } });
  expect(errors).toEqual([]);
  expect(document.body.textContent).not.toMatch(/hindsight/i);
});

it("shows connection details after the command without a parameter form and with the selected Bank ID", () => {
  show();
  expect(document.querySelectorAll("input")).toHaveLength(0);
  const command = Array.from(document.querySelectorAll("pre")).find((node) =>
    node.textContent?.includes("npx.cmd")
  )!;
  expect(command.textContent).not.toContain("--project-path");
  expect(command.textContent!.split("\n").slice(0, 2)).toEqual([
    `$env:CONTEXTBASE_API_URL = '${connection.apiUrl}'`,
    "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'",
  ]);
  expect(command.textContent).not.toMatch(/--api-url|--api-token/);
  const text = document.body.textContent!;
  const endpointHelp = screen.getByText(/^--api-url: Omit/);
  expect(command.compareDocumentPosition(endpointHelp) & Node.DOCUMENT_POSITION_FOLLOWING).not.toBe(
    0
  );
  expect(command.textContent).toContain("--bank-id 'team'");
  expect(text).toContain("--project-path: optional");
  expect(screen.getByRole("heading", { name: "Optional parameters" })).toBeTruthy();
  expect(text).not.toMatch(
    /first installation can prompt|replace a saved address|project-specific client registration directory|Supply a key for the first installation|pass explicitly to replace a saved key|API address \(/
  );
  expect(text).toContain("CONTEXTBASE_API_URL");
  expect(text).toContain("CONTEXTBASE_API_TOKEN");
  expect(screen.getByRole("heading", { name: "Switch workspace" })).toBeTruthy();
  expect(text).toContain("bank use '<BANK_ID>'");
});

it("connects through npm without a download link or archive installer", () => {
  show({ ...connection, packages: {} });
  expect(document.body.textContent).toContain("npx.cmd --yes");
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByRole("link", { name: "Download installation package ↗" })).toBeNull();
  expect(document.body.textContent).not.toContain("npm.cmd exec");
});

it("shows the public Node SDK install and import without archive settings", () => {
  show({ ...connection, packages: {} });
  fireEvent.click(screen.getByRole("button", { name: "Application development" }));
  select("node");
  expect(document.body.textContent).toContain(
    "npm.cmd install '@huaweicloud/contextbase-client@latest'"
  );
  expect(document.body.textContent).toContain('from "@huaweicloud/contextbase-client"');
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.queryByRole("link", { name: "Download installation package ↗" })).toBeNull();
});
