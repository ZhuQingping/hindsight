import "server-only";
import { controlPlaneEnv } from "./control-plane-env";

export interface CustomerConnection {
  apiUrl?: string;
  mcpUrl?: string;
  codingAgentsNpm?: string;
  packages: {
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
    // Production must serve HTTPS. Development may use HTTP (e.g. a local
    // dataplane) so the connect page can show example commands without a
    // published HTTPS address. Internal dataplane/operator credentials still
    // never leak: username/password/hash are always rejected.
    const allowHttp = process.env.NODE_ENV !== "production";
    const allowedProtocol = url.protocol === "https:" || (allowHttp && url.protocol === "http:");
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

function publicNpmPackage(): string | undefined {
  const configured =
    controlPlaneEnv("CODING_AGENTS_NPM_PACKAGE")?.trim() || "contextbase-coding-agents@latest";
  // Keep the executable basename matched to the published Coding Agents package.
  // Accept latest or a fixed version. URLs, paths, other tags and npm
  // aliases must not silently turn the public install command into another source.
  return configured &&
    /^(?:@[a-z0-9][a-z0-9._-]*\/)?contextbase-coding-agents@(?:latest|[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?)$/.test(
      configured
    )
    ? configured
    : undefined;
}

export function customerConnection(bankId: string): CustomerConnection {
  return {
    apiUrl: publicUrl("PUBLIC_API_URL")?.replace(/\/+$/, ""),
    mcpUrl: publicUrl("PUBLIC_MCP_URL", { bankId }),
    codingAgentsNpm: publicNpmPackage(),
    packages: {
      openclaw: publicUrl("OPENCLAW_PACKAGE_URL", { extension: ".tgz" }),
      hermes: publicUrl("HERMES_PACKAGE_URL", { extension: ".zip" }),
      python: publicUrl("PYTHON_SDK_PACKAGE_URL", { extension: ".whl" }),
      node: publicUrl("NODE_SDK_PACKAGE_URL", { extension: ".tgz" }),
    },
  };
}
