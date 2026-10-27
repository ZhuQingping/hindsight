import "server-only";
import { controlPlaneEnv } from "./control-plane-env";

export interface CustomerConnection {
  apiUrl?: string;
  mcpUrl?: string;
  packages: {
    codingAgents?: string;
    openclaw?: string;
    hermes?: string;
    python?: string;
    node?: string;
  };
}

// Only explicitly public settings cross the server/client boundary. Never fall
// back to the console's internal dataplane address or operator credentials.
function publicUrl(name: string, options: { bankId?: string; extension?: string } = {}) {
  const configured = controlPlaneEnv(name)?.trim();
  if (
    !configured ||
    Array.from(configured).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
  )
    return undefined;
  const value = configured.replaceAll("{bank_id}", encodeURIComponent(options.bankId ?? ""));
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.hash) return undefined;
    if (options.extension) {
      // Downloads may use signed query strings; API/MCP endpoints may not.
      if (!url.pathname.endsWith(options.extension)) return undefined;
    } else if (url.search) return undefined;
    return value;
  } catch {
    return undefined;
  }
}

export function customerConnection(bankId: string): CustomerConnection {
  return {
    apiUrl: publicUrl("PUBLIC_API_URL")?.replace(/\/+$/, ""),
    mcpUrl: publicUrl("PUBLIC_MCP_URL", { bankId }),
    packages: {
      codingAgents: publicUrl("CODING_AGENTS_PACKAGE_URL", { extension: ".tgz" }),
      openclaw: publicUrl("OPENCLAW_PACKAGE_URL", { extension: ".tgz" }),
      hermes: publicUrl("HERMES_PACKAGE_URL", { extension: ".zip" }),
      python: publicUrl("PYTHON_SDK_PACKAGE_URL", { extension: ".whl" }),
      node: publicUrl("NODE_SDK_PACKAGE_URL", { extension: ".tgz" }),
    },
  };
}
