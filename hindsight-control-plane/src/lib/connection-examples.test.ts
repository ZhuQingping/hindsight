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
  packages: {
    codingAgents: "https://downloads.example.com/agents.tgz?sig=a&value=$HOME",
    openclaw: "https://downloads.example.com/openclaw.tgz",
    hermes: "https://downloads.example.com/hermes.zip",
    python: "https://downloads.example.com/contextbase_client-1.0.0-py3-none-any.whl",
    node: "https://downloads.example.com/contextbase-client-1.0.0.tgz",
  },
};
const terminals: ConnectionTerminal[] = ["bash", "powershell", "cmd"];

it.each(codingClients)("installs only $id and preserves shell arguments", ({ id }) => {
  const bank = "team's bank $(exit 73) `exit 74` $HOME & 中文";
  const snippet = connectionExample(id, "bash", bank, connection, "question");
  // Run the generated shell, recording argv without installing anything.
  const output = execFileSync(
    "bash",
    ["-c", 'npm() { printf "%s\\n" "$@"; };\n' + snippet.install],
    { encoding: "utf8" }
  )
    .trim()
    .split("\n");
  expect(output).toEqual([
    "exec",
    "--yes",
    `--package=${connection.packages.codingAgents}`,
    "--",
    "contextbase-coding-agents",
    "install",
    id,
    "--api-url",
    connection.apiUrl,
    "--api-token",
    "<API_KEY>",
    "--bank-id",
    bank,
    "--project-path",
    ".",
  ]);
  expect(connectionExample(id, "powershell", bank, connection, "question").install).toContain(
    "'team''s bank $(exit 73) `exit 74` $HOME & 中文'"
  );
});

it.each(terminals)("uses the correct terminal syntax for %s", (terminal) => {
  const install = connectionExample("codex", terminal, "team", connection, "question").install!;
  expect(install).toContain(" install codex --api-url ");
  expect(install).not.toContain("install claude-code");
  if (terminal === "bash") {
    expect(install).toContain("export CONTEXTBASE_API_TOKEN=");
    expect(install).toContain("npm exec");
  } else {
    expect(install).toContain("npm.cmd exec");
    expect(install).toContain(
      terminal === "cmd"
        ? 'set "CONTEXTBASE_API_TOKEN=<API_KEY>"'
        : "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'"
    );
  }
});

it.each(["%PATH%", "!secret!", 'a"b', "line\nbreak", "null\0byte"])(
  "does not emit a CMD command with expandable data %s",
  (bank) => {
    expect(connectionExample("codex", "cmd", bank, connection, "question")).toEqual({
      unavailable: "cmdUnavailable",
    });
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
] as ConnectionClient[])(
  "does not invent a registry package when %s's download is missing",
  (client) => {
    expect(
      connectionExample(client, "bash", "team", { apiUrl: connection.apiUrl, packages: {} }, "q")
    ).toEqual({ unavailable: "packageUnavailable" });
  }
);

it("handles missing API and MCP addresses independently", () => {
  expect(connectionExample("rest", "bash", "team", { packages: {} }, "q").unavailable).toBe(
    "apiUnavailable"
  );
  expect(
    connectionExample("mcp", "bash", "team", { apiUrl: connection.apiUrl, packages: {} }, "q")
      .unavailable
  ).toBe("mcpUnavailable");
});

it.each(codingClients)(
  "runs $id through the configured npm version with a literal project path",
  ({ id }) => {
    const npmConnection = { ...connection, codingAgentsNpm: "contextbase-coding-agents@1.0.0" };
    const path = "/home/customer/project's $(exit 73) `exit 74` $HOME & 中文";
    const snippet = connectionExample(id, "bash", "team", npmConnection, "q", path);
    const output = execFileSync(
      "bash",
      ["-c", 'npx() { printf "%s\\n" "$@"; };\n' + snippet.install],
      {
        encoding: "utf8",
      }
    )
      .trim()
      .split("\n");
    expect(output).toEqual([
      "--yes",
      npmConnection.codingAgentsNpm,
      "install",
      id,
      "--api-url",
      connection.apiUrl,
      "--api-token",
      "<API_KEY>",
      "--bank-id",
      "team",
      "--project-path",
      path,
    ]);
    expect(snippet.install).not.toContain(connection.packages.codingAgents);
    expect(snippet.alternateInstall).toContain(connection.packages.codingAgents);
  }
);

it.each(terminals)("installs from npm without an archive URL in %s", (terminal) => {
  const config = {
    apiUrl: connection.apiUrl,
    codingAgentsNpm: "contextbase-coding-agents@1.0.0",
    packages: {},
  };
  const snippet = connectionExample("codex", terminal, "team", config, "q", "customer project");
  expect(snippet.unavailable).toBeUndefined();
  expect(snippet.install).toContain(terminal === "bash" ? "npx --yes" : "npx.cmd --yes");
  expect(snippet.install).toContain("contextbase-coding-agents@1.0.0");
  expect(snippet.install).toContain(" install codex ");
  expect(snippet.downloadUrl).toBeUndefined();
  expect(snippet.alternateInstall).toBeUndefined();
});

it.each(["", "  ", "line\nbreak", "null\0byte"])("requires a usable project path: %s", (path) => {
  expect(connectionExample("codex", "bash", "team", connection, "q", path).unavailable).toBe(
    "projectPathRequired"
  );
});

it("keeps signed archive URLs out of the main CMD npm command", () => {
  const config = {
    ...connection,
    codingAgentsNpm: "contextbase-coding-agents@1.0.0",
    packages: { codingAgents: "https://downloads.example.com/client.tgz?signature=a%2Fb" },
  };
  const snippet = connectionExample("codex", "cmd", "team", config, "q");
  expect(snippet.install).toContain("npx.cmd --yes");
  expect(snippet.alternateInstall).toBeUndefined();
  expect(snippet.downloadUrl).toBe(config.packages.codingAgents);
  expect(
    connectionExample("codex", "cmd", "team", config, "q", "%USERPROFILE%/project").unavailable
  ).toBe("cmdUnavailable");
});
