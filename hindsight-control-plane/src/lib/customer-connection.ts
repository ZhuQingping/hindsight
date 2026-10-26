import { controlPlaneEnv } from "./control-plane-env";

// These are customer-facing addresses, never the console's internal dataplane URL.
function publicUrl(name: string, bankId?: string): string | undefined {
  const configured = controlPlaneEnv(name)?.trim();
  if (!configured) return undefined;
  const value = configured.replaceAll("{bank_id}", encodeURIComponent(bankId ?? ""));
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.hash) return undefined;
    if (name !== "CODING_AGENTS_PACKAGE_URL" && url.search) return undefined;
    if (name === "CODING_AGENTS_PACKAGE_URL" && !url.pathname.endsWith(".tgz")) return undefined;
    return value;
  } catch {
    return undefined;
  }
}

export function customerConnection(bankId: string) {
  const apiUrl = publicUrl("PUBLIC_API_URL")?.replace(/\/+$/, "");
  const mcpUrl = publicUrl("PUBLIC_MCP_URL", bankId);
  const packageUrl = publicUrl("CODING_AGENTS_PACKAGE_URL");
  const command = (powershell: boolean) => {
    if (!apiUrl || !packageUrl) return undefined;
    // Bank names and download URLs are data, including quotes and shell metacharacters.
    const quote = (value: string) =>
      "'" + value.replaceAll("'", powershell ? "''" : "'\"'\"'") + "'";
    const token = powershell
      ? "$env:CONTEXTBASE_API_TOKEN = '<API_KEY>'"
      : "export CONTEXTBASE_API_TOKEN='<API_KEY>'";
    return (
      token +
      "\n" +
      [
        powershell ? "npm.cmd" : "npm",
        "exec",
        "--yes",
        quote(`--package=${packageUrl}`),
        "--",
        "contextbase-coding-agents",
        "install",
        "claude-code",
        "codex",
        "--api-url",
        quote(apiUrl),
        "--bank-id",
        quote(bankId),
        "--project-path",
        quote("."),
      ].join(" ")
    );
  };
  return { apiUrl, mcpUrl, bashInstall: command(false), powershellInstall: command(true) };
}
