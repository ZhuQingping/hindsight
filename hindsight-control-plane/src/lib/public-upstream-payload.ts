import "server-only";
import { translateApiError, type RequestLike } from "@/lib/i18n/api-errors";

/** Keep server diagnostics out of browser responses without rewriting customer data. */
export function publicUpstreamPayload<T>(data: T, status: number, request?: RequestLike) {
  // Validation errors may quote customer input and carry fields the UI needs.
  // Successful data and 4xx errors retain their existing wire format.
  return status >= 500
    ? { detail: translateApiError("api.errors.generic.failed", "Request failed", request) }
    : data;
}
