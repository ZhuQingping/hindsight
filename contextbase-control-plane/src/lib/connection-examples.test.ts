import { execFileSync } from "node:child_process";
import { expect, it } from "vitest";
import type { CustomerConnection } from "./customer-connection";
import {
  codingClients,
  connectionExample,
  type ConnectionClient,
  type ConnectionTerminal,
} from "./connection-examples";

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
const terminals: ConnectionTerminal[] = ["bash", "powershell", "cmd"];

it.each(codingClients)(
  "installs only $id with its Bank ID and environment credentials",
  ({ id }) => {
    const bank = "team's bank $(exit 73) `exit 74` $HOME & 中文";
    const apiUrl = "https://api.example.com/team's/$(exit 73)/`exit 74`/$HOME";
    const snippet = connectionExample(id, "bash", bank, { ...connection, apiUrl }, "question");
    // Run the generated shell, recording argv without installing anything.
    const output = execFileSync(
      "bash",
      [
        "-c",
        'npx() { printf "%s\\n" "$CONTEXTBASE_API_URL" "$CONTEXTBASE_API_TOKEN" "$@"; };\n' +
          snippet.install,
      ],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          CONTEXTBASE_API_URL: "https://old.example.com",
          CONTEXTBASE_API_TOKEN: "old-key",
        },
      }
    )
      .trim()
      .split("\n");
    expect(output).toEqual([
      apiUrl,
      "<API_KEY>",
      "--yes",
      connection.codingAgentsNpm,
      "install",
      id,
      "--bank-id",
      bank,
      ...(id === "codearts-agent" ? ["--mcp-config", "<MCP_CONFIG_PATH>"] : []),
    ]);
    expect(snippet.install).not.toContain("--project-path");
    expect(snippet.install!.split("\n")[0]).toContain("CONTEXTBASE_API_URL");
    expect(snippet.install!.split("\n")[1]).toBe("export CONTEXTBASE_API_TOKEN='<API_KEY>'");
    expect(snippet.install).toContain("--bank-id");
  }
);

it.each(terminals)("uses the correct terminal syntax for %s", (terminal) => {
  const install = connectionExample("codex", terminal, "team", connection, "question").install!;
  expect(install).toContain(" install codex --bank-id ");
  expect(install.split("\n")).toHaveLength(3);
  expect(install).not.toContain("install claude-code");
  expect(install).not.toMatch(/--api-url|--api-token/);
  if (terminal === "bash") {
    expect(install.split("\n").slice(0, 2)).toEqual([
      `export CONTEXTBASE_API_URL='${connection.apiUrl}'`,
      "export CONTEXTBASE_API_TOKEN='<API_KEY>'",
    ]);
    expect(install).toContain("npx --yes");
  } else {
    if (terminal === "cmd") {
      expect(install.split("\n").slice(0, 2)).toEqual([
        `set "CONTEXTBASE_API_URL=${connection.apiUrl}"`,
        'set "CONTEXTBASE_API_TOKEN=<API_KEY>"',
      ]);
    }
    expect(install).toContain("npx.cmd --yes");
  }
});

it.each(["%PATH%", "!secret!", 'a"b', "line\nbreak", "null\0byte"])(
  "rejects Bank IDs that CMD would expand: %s",
  (bank) => {
    expect(connectionExample("codex", "cmd", bank, connection, "q").unavailable).toBe(
      "cmdUnavailable"
    );
    expect(connectionExample("codex", "powershell", bank, connection, "q").install).toContain(
      "--bank-id"
    );
    const config = { ...connection, apiUrl: `https://api.example.com/${bank}` };
    expect(connectionExample("codex", "cmd", "team", config, "q").unavailable).toBe(
      "cmdUnavailable"
    );
    expect(connectionExample("codex", "powershell", "team", config, "q").install).toContain(
      "CONTEXTBASE_API_URL"
    );
  }
);

it("matches the complete PowerShell installation command", () => {
  expect(
    connectionExample("claude-code", "powershell", "smoke-bank", connection, "q").install
  ).toBe(
    [
      `$env:CONTEXTBASE_API_URL = '${connection.apiUrl}'`,
      "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'",
      "npx.cmd --yes '@huaweicloud/contextbase-coding-agents@latest' install claude-code --bank-id 'smoke-bank'",
    ].join("\n")
  );
});

it.each(terminals)("offers a separate Bank switch command for %s", (terminal) => {
  const snippet = connectionExample("claude-code", terminal, "smoke-bank", connection, "q");
  expect(snippet.switchBank).toContain(" bank use ");
  expect(snippet.switchBank).not.toContain(" install ");
  expect(snippet.switchBank).toContain(terminal === "bash" ? "npx --yes" : "npx.cmd --yes");
  expect(snippet.switchBank).toContain(terminal === "cmd" ? '"<BANK_ID>"' : "'<BANK_ID>'");
  expect(
    connectionExample("rest", terminal, "smoke-bank", connection, "q").switchBank
  ).toBeUndefined();
});

it("rejects percent expansion in signed CMD URLs and REST paths without changing the URL", () => {
  const signed = {
    ...connection,
    packages: { ...connection.packages, python: connection.packages.python + "?signature=a%2Fb" },
  };
  expect(connectionExample("python", "cmd", "team", signed, "q").unavailable).toBe(
    "cmdUnavailable"
  );
  expect(connectionExample("python", "powershell", "team", signed, "q").install).toContain(
    "?signature=a%2Fb"
  );
  expect(connectionExample("rest", "cmd", "team/a%", connection, "q").unavailable).toBe(
    "cmdUnavailable"
  );
});

it("executes a read-only REST command with the encoded bank and literal auth header", () => {
  const bank = "team/'中文%";
  const { code } = connectionExample("rest", "bash", bank, connection, "q");
  const output = execFileSync("bash", ["-c", 'curl() { printf "%s\\n" "$@"; };\n' + code], {
    encoding: "utf8",
  })
    .trim()
    .split("\n");
  expect(output).toEqual([
    "--fail",
    "--show-error",
    "-H",
    "Authorization: Bearer <API_KEY>",
    `${connection.apiUrl}/v1/default/banks/${encodeURIComponent(bank)}/stats`,
  ]);
  expect(connectionExample("rest", "powershell", bank, connection, "q").code).toContain(
    "Bearer $env:CONTEXTBASE_API_TOKEN"
  );
});

it.each(["openclaw", "hermes"] as const)(
  "uses %s's own plugin instead of a Coding Agents target",
  (client) => {
    const example = connectionExample(client, "bash", "team", connection, "q");
    expect(example.install).not.toContain("contextbase-coding-agents");
    expect(example.downloadUrl).toBe(connection.packages[client]);
    if (client === "openclaw") {
      expect(example.install).toContain("openclaw plugins install ./contextbase-openclaw.tgz");
      const config = JSON.parse(example.configuration!);
      expect(config.bankId).toBe("team");
      expect(config).not.toHaveProperty("dynamicBankId");
      expect(config.contextbaseApiToken.id).toBe("CONTEXTBASE_API_TOKEN");
    } else {
      expect(example.install).toBe("hermes plugins enable contextbase\nhermes memory setup");
      expect(example.configuration).toContain("Bank ID: team");
    }
  }
);

it.each(["python", "node"] as const)("generates branded, read-only %s SDK code", (client) => {
  const { install, code } = connectionExample(
    client,
    "powershell",
    'team"/中文',
    connection,
    'question "quoted"'
  );
  expect(install).toContain(
    client === "python" ? connection.packages.python : "@huaweicloud/contextbase-client@latest"
  );
  expect(install).not.toMatch(/pip install contextbase-client|npm.cmd install contextbase-client$/);
  expect(code).toContain(connection.apiUrl);
  expect(code).toContain('team\\"/中文');
  expect(code).toContain("CONTEXTBASE_API_TOKEN");
  expect(code).not.toMatch(/hindsight|\.retain\(/i);
  expect(code).toContain(client === "python" ? "base_url=" : "baseUrl:");
});

it("keeps remote MCP independent from the API and supplies only placeholder credentials", () => {
  const result = connectionExample(
    "mcp",
    "bash",
    "team",
    { packages: {}, mcpUrl: connection.mcpUrl },
    "q"
  );
  const config = JSON.parse(result.configuration!);
  expect(config.mcpServers.contextbase.url).toBe(connection.mcpUrl);
  expect(config.mcpServers.contextbase.headers).toEqual({
    Authorization: "Bearer <API_KEY>",
    "X-Bank-Id": "team",
  });
});

it.each([
  "claude-code",
  "codex",
  "cursor-cli",
  "dsh",
  "opencode",
  "opencode2",
  "pi",
  "workbuddy",
  "openclaw",
  "hermes",
  "python",
] as ConnectionClient[])("does not invent an unconfigured package for %s", (client) => {
  expect(
    connectionExample(client, "bash", "team", { apiUrl: connection.apiUrl, packages: {} }, "q")
  ).toEqual({ unavailable: "packageUnavailable" });
});

it("handles missing API and MCP addresses independently", () => {
  expect(connectionExample("rest", "bash", "team", { packages: {} }, "q").unavailable).toBe(
    "apiUnavailable"
  );
  expect(
    connectionExample("mcp", "bash", "team", { apiUrl: connection.apiUrl, packages: {} }, "q")
      .unavailable
  ).toBe("mcpUnavailable");
});

it.each(terminals)("installs from npm without an archive URL in %s", (terminal) => {
  const config = {
    apiUrl: connection.apiUrl,
    codingAgentsNpm: "@huaweicloud/contextbase-coding-agents@1.1.0",
    packages: {},
  };
  const snippet = connectionExample("codex", terminal, "team", config, "q");
  expect(snippet.unavailable).toBeUndefined();
  expect(snippet.install).toContain(terminal === "bash" ? "npx --yes" : "npx.cmd --yes");
  expect(snippet.install).toContain("@huaweicloud/contextbase-coding-agents@1.1.0");
  expect(snippet.install).toContain(" install codex ");
  expect(snippet.downloadUrl).toBeUndefined();
});

it.each(codingClients)(
  "offers the $id installer before an API Endpoint is configured",
  ({ id }) => {
    const result = connectionExample(
      id,
      "bash",
      "team",
      { codingAgentsNpm: "@huaweicloud/contextbase-coding-agents@latest", packages: {} },
      "q"
    );
    expect(result.install).toContain(`install ${id} --bank-id 'team'`);
    expect(result.install).toContain("CONTEXTBASE_API_URL='<API_ENDPOINT>'");
    expect(result.install).not.toContain("--project-path");
  }
);

it.each(["latest", "1.1.0"])(
  "preserves the configured npm selector %s in the generated command",
  (selector) => {
    const spec = `@huaweicloud/contextbase-coding-agents@${selector}`;
    const snippet = connectionExample(
      "codex",
      "bash",
      "team",
      { apiUrl: connection.apiUrl, codingAgentsNpm: spec, packages: {} },
      "q"
    );
    const output = execFileSync(
      "bash",
      ["-c", 'npx() { printf "%s\\n" "$@"; };\n' + snippet.install],
      { encoding: "utf8" }
    )
      .trim()
      .split("\n");
    expect(output.slice(0, 4)).toEqual(["--yes", spec, "install", "codex"]);
  }
);

it.each(terminals)("installs the public Node SDK without a download URL in %s", (terminal) => {
  const result = connectionExample(
    "node",
    terminal,
    "team",
    { apiUrl: connection.apiUrl, packages: {} },
    "q"
  );
  expect(result.unavailable).toBeUndefined();
  expect(result.install).toContain(`${terminal === "bash" ? "npm" : "npm.cmd"} install `);
  expect(result.install).toContain("@huaweicloud/contextbase-client@latest");
  expect(result.code).toContain('from "@huaweicloud/contextbase-client"');
  expect(result.code).toContain(connection.apiUrl);
  expect(result.downloadUrl).toBeUndefined();
});
