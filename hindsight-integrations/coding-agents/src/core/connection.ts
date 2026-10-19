import type { Config } from "./config";

export class RemoteConnectionError extends Error {}

/** Only explicit endpoints are allowed; configuration never discovers a local service. */
export function validateRemoteEndpoint(value: string): string {
  if (!value.trim()) {
    throw new RemoteConnectionError(
      "API Endpoint is required. Copy it from your console and set apiUrl or CONTEXTBASE_API_URL."
    );
  }
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new RemoteConnectionError("API Endpoint must be a valid HTTP or HTTPS URL.");
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    !url.hostname ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new RemoteConnectionError(
      "API Endpoint must use HTTP or HTTPS without credentials, query parameters or fragments."
    );
  }
  return value.trim().replace(/\/+$/, "");
}

/** Shared hook/runtime gate, with no subprocess or network side effects. */
export async function ensureRemoteConnection(cfg: Config): Promise<void> {
  if (cfg.serverMode === "daemon") {
    throw new RemoteConnectionError(
      "Local engines are not distributed. Configure your remote API Endpoint."
    );
  }
  validateRemoteEndpoint(cfg.apiUrl);
}
