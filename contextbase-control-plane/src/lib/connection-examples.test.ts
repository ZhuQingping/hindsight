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
    node: "https://downloads.example.com/contextbase-client-1.0.0.tgz",
  },
};
const terminals: ConnectionTerminal[] = ["bash", "powershell", "cmd"];

it.each(codingClients)(
  "installs only $id with its Bank ID and without endpoint or project flags",
  ({ id }) => {
    const bank = "team's bank $(exit 73) `exit 74` $HOME & 中文";
    const snippet = connectionExample(id, "bash", bank, connection, "question");
    // Run the generated shell, recording argv without installing anything.
    const output = execFileSync(
      "bash",
      ["-c", 'npx() { printf "%s\\n" "$@"; };\n' + snippet.install],
      { encoding: "utf8" }
    )
      .trim()
      .split("\n");
    expect(output).toEqual([
      "--yes",
      connection.codingAgentsNpm,
      "install",
      id,
      "--api-token",
      "<API_KEY>",
      "--bank-id",
      bank,
    ]);
    expect(snippet.install).not.toMatch(/--api-url|--project-path/);
    expect(snippet.install).toContain("--bank-id");
  }
);

it.each(terminals)("uses the correct terminal syntax for %s", (terminal) => {
  const install = connectionExample("codex", terminal, "team", connection, "question").install!;
  expect(install).toContain(" install codex --api-token ");
  expect(install).not.toContain("install claude-code");
  if (terminal === "bash") {
    expect(install).toContain("export CONTEXTBASE_API_TOKEN=");
    expect(install).toContain("npx --yes");
  } else {
    expect(install).toContain("npx.cmd --yes");
    expect(install).toContain(
      terminal === "cmd"
        ? 'set "CONTEXTBASE_API_TOKEN=<API_KEY>"'
        : "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'"
    );
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
  }
);

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
      expect(config.dynamicBankId).toBe(false);
      expect(config.contextbaseApiToken.id).toBe("CONTEXTBASE_API_TOKEN");
    } else {
      expect(example.install).toBe("hermes plugins enable contextbase\nhermes memory setup");
      expect(example.configuration).toContain("Bank ID: team");
    }
  }
);

it.each(["python", "node"] as const)(
  "generates branded, read-only %s SDK code using the configured download",
  (client) => {
    const { install, code } = connectionExample(
      client,
      "powershell",
      'team"/中文',
      connection,
      'question "quoted"'
    );
    expect(install).toContain(connection.packages[client]);
    expect(install).not.toMatch(
      /pip install contextbase-client|npm.cmd install contextbase-client$/
    );
    expect(code).toContain(connection.apiUrl);
    expect(code).toContain('team\\"/中文');
    expect(code).toContain("CONTEXTBASE_API_TOKEN");
    expect(code).not.toMatch(/hindsight|\.retain\(/i);
    expect(code).toContain(client === "python" ? "base_url=" : "baseUrl:");
  }
);

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
  "node",
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
    codingAgentsNpm: "@huaweicloud/contextbase-coding-agents@1.0.0",
    packages: {},
  };
  const snippet = connectionExample("codex", terminal, "team", config, "q");
  expect(snippet.unavailable).toBeUndefined();
  expect(snippet.install).toContain(terminal === "bash" ? "npx --yes" : "npx.cmd --yes");
  expect(snippet.install).toContain("@huaweicloud/contextbase-coding-agents@1.0.0");
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
    expect(result.install).toContain(`install ${id} --api-token`);
    expect(result.install).not.toMatch(/--api-url|--project-path/);
  }
);

it.each(["latest", "1.0.0"])(
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
