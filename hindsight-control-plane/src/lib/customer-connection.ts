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

// In development, when an operator has not configured a published download
// address yet, fall back to an explicit placeholder so the connect page can
// render example commands for review. Production never falls back: an unset
// package URL stays undefined and the page shows the unavailable notice.
function devFallbackPackage(name: string, extension: string): string | undefined {
  if (process.env.NODE_ENV === "production") return undefined;
  return "https://placeholder.contextbase.local/" + name + "-PACKAGE-URL-NOT-SET" + extension;
}

export function customerConnection(bankId: string): CustomerConnection {
  return {
    apiUrl: publicUrl("PUBLIC_API_URL")?.replace(/\/+$/, ""),
    mcpUrl: publicUrl("PUBLIC_MCP_URL", { bankId }),
    packages: {
      codingAgents: publicUrl("CODING_AGENTS_PACKAGE_URL", { extension: ".tgz" }) ?? devFallbackPackage("contextbase-coding-agents", ".tgz"),
      openclaw: publicUrl("OPENCLAW_PACKAGE_URL", { extension: ".tgz" }) ?? devFallbackPackage("contextbase-openclaw", ".tgz"),
      hermes: publicUrl("HERMES_PACKAGE_URL", { extension: ".zip" }) ?? devFallbackPackage("contextbase-hermes", ".zip"),
      python: publicUrl("PYTHON_SDK_PACKAGE_URL", { extension: ".whl" }) ?? devFallbackPackage("contextbase_client", ".whl"),
      node: publicUrl("NODE_SDK_PACKAGE_URL", { extension: ".tgz" }) ?? devFallbackPackage("contextbase-client", ".tgz"),
    },
  };
}
