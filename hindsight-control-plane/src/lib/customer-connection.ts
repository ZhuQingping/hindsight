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

const RELEASE_ASSETS =
  "https://github.com/RSIXDB/hindsight/releases/download/contextbase-clients-v0.1.0";

const DEFAULT_PACKAGES = {
  codingAgents: `${RELEASE_ASSETS}/contextbase-coding-agents-0.8.1.tgz`,
  openclaw: `${RELEASE_ASSETS}/contextbase-openclaw-1.0.0.tgz`,
  hermes: `${RELEASE_ASSETS}/hermes-plugin-contextbase-1.2.2.zip`,
  python: `${RELEASE_ASSETS}/contextbase_client-1.0.0-py3-none-any.whl`,
  node: `${RELEASE_ASSETS}/contextbase-client-1.0.0.tgz`,
} as const;

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
    // Production must serve HTTPS. Development may use HTTP (e.g. a local
    // dataplane) so the connect page can show example commands without a
    // published HTTPS address. Internal dataplane/operator credentials still
    // never leak: username/password/hash are always rejected.
    const allowHttp = process.env.NODE_ENV !== "production";
    const allowedProtocol =
      url.protocol === "https:" || (allowHttp && url.protocol === "http:");
    if (!allowedProtocol || url.username || url.password || url.hash) return undefined;
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
      codingAgents:
        publicUrl("CODING_AGENTS_PACKAGE_URL", { extension: ".tgz" }) ?? DEFAULT_PACKAGES.codingAgents,
      openclaw:
        publicUrl("OPENCLAW_PACKAGE_URL", { extension: ".tgz" }) ?? DEFAULT_PACKAGES.openclaw,
      hermes:
        publicUrl("HERMES_PACKAGE_URL", { extension: ".zip" }) ?? DEFAULT_PACKAGES.hermes,
      python:
        publicUrl("PYTHON_SDK_PACKAGE_URL", { extension: ".whl" }) ?? DEFAULT_PACKAGES.python,
      node: publicUrl("NODE_SDK_PACKAGE_URL", { extension: ".tgz" }) ?? DEFAULT_PACKAGES.node,
    },
  };
}
