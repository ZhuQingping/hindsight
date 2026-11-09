import "server-only";
import { controlPlaneEnv } from "./control-plane-env";

export const EXTERNAL_ORIGIN_HEADER = "X-ContextDB-External-Origin";

export function normalizedHttpOrigin(value: string | null | undefined): string | undefined {
  // URL() repairs malformed authorities and backslashes. Reject those before
  // parsing so only an actual HTTP origin can become a public example address.
  if (!value || /[\s\\,]/.test(value) || !/^https?:\/\/[^/?#]+\/?$/i.test(value)) return undefined;
  try {
    const url = new URL(value);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      !url.hostname ||
      /^\.+$/.test(url.hostname) ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      value.includes("?") ||
      value.includes("#")
    )
      return undefined;
    return url.origin;
  } catch {
    return undefined;
  }
}

export function derivedApiUrl(uiOrigin: string | undefined): string | undefined {
  const origin = normalizedHttpOrigin(uiOrigin);
  const port = controlPlaneEnv("PUBLIC_API_PORT");
  if (!origin || !port || !/^\d{1,5}$/.test(port) || Number(port) < 1 || Number(port) > 65535)
    return undefined;
  const url = new URL(origin);
  url.port = port;
  return url.origin;
}

export function requestUiOrigin(requestHeaders: Pick<Headers, "get">): string | undefined {
  // Only the loopback Node child behind our gateway receives this marker.
  // Missing/invalid gateway data must never expose its internal PUBLIC_ORIGIN.
  return normalizedHttpOrigin(
    controlPlaneEnv("TRUST_EXTERNAL_ORIGIN") === "1"
      ? requestHeaders.get(EXTERNAL_ORIGIN_HEADER)
      : controlPlaneEnv("PUBLIC_ORIGIN")
  );
}
