import "server-only";
import { controlPlaneEnv } from "./control-plane-env";
import { derivedApiUrl, normalizedHttpOrigin } from "./public-origin";

export interface CustomerConnection {
  apiUrl?: string;
  mcpUrl?: string;
  codingAgentsNpm?: string;
  packages: {
    openclaw?: string;
    hermes?: string;
    python?: string;
  };
}

// Only public configuration and trusted display origins cross this boundary.
// Never fall back to internal dataplane addresses or operator credentials.
interface PublicUrlOptions {
  bankId?: string;
  extension?: string;
  trustedOrigin?: string;
}

function publicUrl(configured: string | undefined, options: PublicUrlOptions = {}) {
  configured = configured?.trim();
  if (
    !configured ||
    Array.from(configured).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)
  )
    return undefined;
  const value = configured.replaceAll("{bank_id}", encodeURIComponent(options.bankId ?? ""));
  try {
    const url = new URL(value);
    // Public endpoints normally require HTTPS in production; direct HTTP UI
    // deployments may use same-host HTTP. Credentials/fragments stay forbidden.
    const trusted = normalizedHttpOrigin(options.trustedOrigin);
    const sameHostHttp =
      trusted &&
      new URL(trusted).protocol === "http:" &&
      url.hostname === new URL(trusted).hostname;
    // Download origins stay HTTPS-only. HTTP endpoint examples are safe only
    // for the same host as a UI already served over direct HTTP.
    const allowHttp = !options.extension && (process.env.NODE_ENV !== "production" || sameHostHttp);
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
    controlPlaneEnv("CODING_AGENTS_NPM_PACKAGE")?.trim() ||
    "@huaweicloud/contextbase-coding-agents@latest";
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

export function customerConnection(
  bankId: string,
  context: { uiOrigin?: string } = {}
): CustomerConnection {
  const explicitApiUrl = controlPlaneEnv("PUBLIC_API_URL");
  // Presence, including empty/invalid values, is an operator override. Never
  // replace it with a derived endpoint or an internal dataplane address.
  const apiUrl = explicitApiUrl !== undefined ? explicitApiUrl : derivedApiUrl(context.uiOrigin);
  return {
    apiUrl: publicUrl(apiUrl, { trustedOrigin: context.uiOrigin })?.replace(/\/+$/, ""),
    mcpUrl: publicUrl(controlPlaneEnv("PUBLIC_MCP_URL"), {
      bankId,
      trustedOrigin: context.uiOrigin,
    }),
    codingAgentsNpm: publicNpmPackage(),
    packages: {
      openclaw: publicUrl(controlPlaneEnv("OPENCLAW_PACKAGE_URL"), { extension: ".tgz" }),
      hermes: publicUrl(controlPlaneEnv("HERMES_PACKAGE_URL"), { extension: ".zip" }),
      python: publicUrl(controlPlaneEnv("PYTHON_SDK_PACKAGE_URL"), { extension: ".whl" }),
    },
  };
}
