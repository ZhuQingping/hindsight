import type { CustomerConnection } from "./customer-connection";

export const codingClients = [
  { id: "claude-code", name: "Claude Code" },
  { id: "codex", name: "Codex CLI" },
  { id: "cursor-cli", name: "Cursor CLI" },
  { id: "dsh", name: "DSH / DeepSeek Harness" },
  { id: "opencode", name: "OpenCode" },
  { id: "opencode2", name: "OpenCode 2" },
  { id: "pi", name: "pi" },
  { id: "workbuddy", name: "WorkBuddy" },
] as const;

export type CodingClient = (typeof codingClients)[number]["id"];
export type ConnectionClient =
  | CodingClient
  | "openclaw"
  | "hermes"
  | "python"
  | "node"
  | "rest"
  | "mcp";
export type ConnectionTerminal = "powershell" | "cmd" | "bash";

interface ConnectionExample {
  install?: string;
  code?: string;
  run?: string;
  configuration?: string;
  downloadUrl?: string;
  unavailable?:
    | "apiUnavailable"
    | "packageUnavailable"
    | "mcpUnavailable"
    | "cmdUnavailable"
    | "projectPathRequired";
}

function quote(value: string, terminal: ConnectionTerminal): string {
  if (terminal === "cmd") return `"${value}"`;
  return "'" + value.replaceAll("'", terminal === "powershell" ? "''" : "'\"'\"'") + "'";
}

function tokenEnvironment(terminal: ConnectionTerminal): string {
  if (terminal === "powershell") return "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'";
  if (terminal === "cmd") return 'set "CONTEXTBASE_API_TOKEN=<API_KEY>"';
  return "export CONTEXTBASE_API_TOKEN='<API_KEY>'";
}

// CMD expands %variables% even inside quotes, and !variables! under delayed
// expansion. Offer PowerShell for those values rather than emit corrupt commands.
function cmdUnsafe(values: string[], terminal: ConnectionTerminal): boolean {
  return (
    terminal === "cmd" && values.some((value) => value.includes("\0") || /[%!"\r\n]/.test(value))
  );
}

export function connectionExample(
  client: ConnectionClient,
  terminal: ConnectionTerminal,
  bankId: string,
  connection: CustomerConnection,
  query: string,
  projectPath = "."
): ConnectionExample {
  const { apiUrl, mcpUrl, packages } = connection;
  if (client === "mcp") {
    if (!mcpUrl) return { unavailable: "mcpUnavailable" };
    return {
      configuration: JSON.stringify(
        {
          mcpServers: {
            contextbase: {
              type: "http",
              url: mcpUrl,
              headers: { Authorization: "Bearer <API_KEY>", "X-Bank-Id": bankId },
            },
          },
        },
        null,
        2
      ),
    };
  }
  if (!apiUrl) return { unavailable: "apiUnavailable" };
  const q = (value: string) => quote(value, terminal);
  const npm = terminal === "bash" ? "npm" : "npm.cmd";
  const curl = terminal === "bash" ? "curl" : "curl.exe";
  const token = tokenEnvironment(terminal);
  // Pass the key explicitly: an existing installer config otherwise takes
  // precedence over environment variables and could keep an older credential.
  const tokenArgument =
    terminal === "cmd"
      ? '"%CONTEXTBASE_API_TOKEN%"'
      : terminal === "powershell"
        ? '"$env:CONTEXTBASE_API_TOKEN"'
        : '"$CONTEXTBASE_API_TOKEN"';
  if (client === "rest") {
    const url = `${apiUrl}/v1/default/banks/${encodeURIComponent(bankId)}/stats`;
    if (cmdUnsafe([url], terminal)) return { unavailable: "cmdUnavailable" };
    const variable =
      terminal === "cmd"
        ? "%CONTEXTBASE_API_TOKEN%"
        : terminal === "powershell"
          ? "$env:CONTEXTBASE_API_TOKEN"
          : "$CONTEXTBASE_API_TOKEN";
    return {
      code: `${token}\n${curl} --fail --show-error -H "Authorization: Bearer ${variable}" ${q(url)}`,
    };
  }
  const isCoding = codingClients.some((entry) => entry.id === client);
  if (isCoding) {
    if (!projectPath.trim() || /[\0\r\n]/.test(projectPath))
      return { unavailable: "projectPathRequired" };
    if (!connection.codingAgentsNpm) return { unavailable: "packageUnavailable" };
    if (cmdUnsafe([apiUrl, bankId, projectPath], terminal))
      return { unavailable: "cmdUnavailable" };
    const args = `install ${client} --api-url ${q(apiUrl)} --api-token ${tokenArgument} --bank-id ${q(bankId)} --project-path ${q(projectPath)}`;
    const npx = terminal === "bash" ? "npx" : "npx.cmd";
    return { install: `${token}\n${npx} --yes ${q(connection.codingAgentsNpm)} ${args}` };
  }
  const packageUrl = packages[client as keyof typeof packages];
  if (!packageUrl) return { unavailable: "packageUnavailable" };
  if (client !== "hermes" && cmdUnsafe([packageUrl], terminal))
    return { unavailable: "cmdUnavailable" };
  if (client === "openclaw") {
    return {
      downloadUrl: packageUrl,
      install: `${curl} --fail --location --show-error --output contextbase-openclaw.tgz ${q(packageUrl)}\nopenclaw plugins install ./contextbase-openclaw.tgz`,
      configuration: JSON.stringify(
        {
          contextbaseApiUrl: apiUrl,
          contextbaseApiToken: { source: "env", provider: "default", id: "CONTEXTBASE_API_TOKEN" },
          bankId,
          dynamicBankId: false,
          autoRecall: true,
          autoRetain: true,
        },
        null,
        2
      ),
    };
  }
  if (client === "hermes") {
    return {
      downloadUrl: packageUrl,
      install: "hermes plugins enable contextbase\nhermes memory setup",
      configuration: `API Endpoint: ${apiUrl}\nAPI Key: <API_KEY>\nBank ID: ${bankId}`,
    };
  }
  if (client === "python") {
    return {
      downloadUrl: packageUrl,
      install: `python -m pip install ${q(packageUrl)}\n${token}`,
      code: `import os\nfrom contextbase_client import ContextBase\n\nwith ContextBase(\n    base_url=${JSON.stringify(apiUrl)},\n    api_key=os.environ["CONTEXTBASE_API_TOKEN"],\n) as client:\n    result = client.recall(\n        bank_id=${JSON.stringify(bankId)},\n        query=${JSON.stringify(query)},\n    )\n    print(result)`,
      run: "python contextbase-example.py",
    };
  }
  return {
    downloadUrl: packageUrl,
    install: `${npm} install ${q(packageUrl)}\n${token}`,
    code: `import { ContextBaseClient } from "contextbase-client";\n\nconst client = new ContextBaseClient({\n  baseUrl: ${JSON.stringify(apiUrl)},\n  apiKey: process.env.CONTEXTBASE_API_TOKEN,\n});\nconst result = await client.recall(\n  ${JSON.stringify(bankId)},\n  ${JSON.stringify(query)},\n);\nconsole.log(result);`,
    run: "node contextbase-example.mjs",
  };
}
