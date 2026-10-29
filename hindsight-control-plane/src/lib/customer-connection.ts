import "server-only";
import defaultPackages from "../../config/client-packages.json";
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
function publicUrl(
  name: string,
  options: { bankId?: string; extension?: string; defaultUrl?: string } = {}
) {
  const configured = controlPlaneEnv(name)?.trim() || options.defaultUrl;
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
      codingAgents: publicUrl("CODING_AGENTS_PACKAGE_URL", {
        extension: ".tgz",
        defaultUrl: defaultPackages.codingAgents,
      }),
      openclaw: publicUrl("OPENCLAW_PACKAGE_URL", {
        extension: ".tgz",
        defaultUrl: defaultPackages.openclaw,
      }),
      hermes: publicUrl("HERMES_PACKAGE_URL", {
        extension: ".zip",
        defaultUrl: defaultPackages.hermes,
      }),
      python: publicUrl("PYTHON_SDK_PACKAGE_URL", {
        extension: ".whl",
        defaultUrl: defaultPackages.python,
      }),
      node: publicUrl("NODE_SDK_PACKAGE_URL", {
        extension: ".tgz",
        defaultUrl: defaultPackages.node,
      }),
    },
  };
}
