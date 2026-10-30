import "server-only";

import { NextResponse } from "next/server";
import { contextDBBankUrl, contextDBHeaders, requireContextDBAdmin } from "@/lib/contextdb";

const NO_STORE = { "Cache-Control": "no-store, private", Pragma: "no-cache" };

/** Fixed Bank target; browser credentials never select the backend or its key. */
export async function proxyContextDBBank(request: Request, bankId: string): Promise<NextResponse> {
  const requestId = crypto.randomUUID();
  const failure = (
    status: number,
    code: string,
    message: string,
    responseHeaders = new Headers(NO_STORE)
  ) => {
    const responseId = responseHeaders.get("X-Request-ID") || requestId;
    responseHeaders.set("X-Request-ID", responseId);
    return NextResponse.json(
      { code, message, request_id: responseId },
      { status, headers: responseHeaders }
    );
  };
  // The Bank API authenticates the current administrator once. Retain the
  // existing UI session/Host/Origin checks without a duplicate identity query.
  const denied = await requireContextDBAdmin(request, false);
  if (denied) {
    const data = await denied.json();
    return failure(denied.status, "management_denied", data.error || "Management request denied");
  }
  if (!/^[a-z][a-z0-9_]{0,53}$/.test(bankId) || new URL(request.url).search)
    return failure(400, "invalid_request", "Use a canonical Bank ID without query parameters");
  if (!["PUT", "PATCH", "DELETE"].includes(request.method))
    return failure(405, "method_not_allowed", "Unsupported Bank operation");
  const headers = contextDBHeaders();
  const condition = request.headers.get("if-none-match");
  if (condition !== null) {
    if (request.method !== "PUT" || condition !== "*")
      return failure(400, "invalid_condition", "Only PUT If-None-Match: * is supported");
    headers.set("If-None-Match", condition);
  }
  if (request.method === "DELETE") {
    const etag = request.headers.get("if-match");
    if (!etag) return failure(428, "precondition_required", "If-Match is required");
    if (!/^"[0-9a-f]{32}:[1-9][0-9]*"$/.test(etag))
      return failure(400, "invalid_condition", "Use the original workspace identity condition");
    headers.set("If-Match", etag);
  }
  let body: string | undefined;
  if (request.method !== "DELETE") {
    try {
      const input: unknown = await request.json();
      if (!input || typeof input !== "object" || Array.isArray(input))
        throw new Error("Invalid body");
      body = JSON.stringify(input);
      headers.set("Content-Type", "application/json");
    } catch {
      return failure(400, "invalid_request", "Invalid Bank request body");
    }
  }
  let upstream: Response;
  try {
    // Synchronous lifecycle writes have no proxy timeout or automatic replay.
    // A disconnected caller cannot infer that a write was rolled back.
    upstream = await fetch(contextDBBankUrl(bankId), {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
  } catch {
    return failure(503, "service_unavailable", "Unable to connect to the Bank service");
  }
  const responseHeaders = new Headers(NO_STORE);
  for (const name of [
    "X-Request-ID",
    "X-ContextDB-Workspace-ETag",
    "Retry-After",
    "X-Ignored-Params",
  ]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  if (upstream.status >= 500) {
    // Match the existing UI's neutral 5xx policy without parsing diagnostic or
    // gateway bodies. Body failures must not replace a known status or request ID.
    await upstream.body?.cancel().catch(() => undefined);
    return failure(
      upstream.status,
      "service_unavailable",
      "Bank service is temporarily unavailable",
      responseHeaders
    );
  }
  try {
    const data: unknown = await upstream.json();
    const safe = JSON.parse(
      JSON.stringify(data, (key, value) => (/digest|secret/i.test(key) ? undefined : value))
    );
    return NextResponse.json(safe, { status: upstream.status, headers: responseHeaders });
  } catch {
    return failure(
      upstream.ok ? 502 : upstream.status,
      "response_unknown",
      "Bank response could not be read; inspect the workspace before retrying",
      responseHeaders
    );
  }
}
