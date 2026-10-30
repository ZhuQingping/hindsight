import { NextResponse } from "next/server";
import { contextDBHeaders, contextDBUrl, requireContextDBAdmin } from "@/lib/contextdb";

type RouteContext = { params: Promise<{ path: string[] }> };
// The extension issues UUID hex strings without separators for both users and
// keys. Match its wire format so real issued IDs reach the fixed upstream.
const RESOURCE_ID = /^[0-9a-f]{32}$/;
const NO_STORE = { "Cache-Control": "no-store, private", Pragma: "no-cache" };

async function proxy(request: Request, context: RouteContext) {
  const requestId = crypto.randomUUID();
  const failure = (code: string, message: string, status: number) =>
    NextResponse.json(
      { code, message, request_id: requestId },
      { status, headers: { ...NO_STORE, "X-Request-ID": requestId } }
    );
  const denied = await requireContextDBAdmin(request, false);
  if (denied) {
    const data = await denied.json();
    return failure(
      denied.status === 401
        ? "unauthorized"
        : denied.status === 403
          ? "forbidden"
          : "service_unavailable",
      typeof data.message === "string"
        ? data.message
        : typeof data.error === "string"
          ? data.error
          : "Management request denied",
      denied.status
    );
  }
  const { path } = await context.params;
  // This is an explicit management allowlist, never an arbitrary URL proxy.
  const identityRoute =
    path.length === 2 && path[0] === "admin" && path[1] === "identity" && request.method === "GET";
  const usersRoute =
    path[0] === "users" &&
    ((path.length === 1 && ["GET", "POST"].includes(request.method)) ||
      (path.length === 2 &&
        RESOURCE_ID.test(path[1]) &&
        ["PATCH", "DELETE"].includes(request.method)) ||
      (path.length === 3 &&
        RESOURCE_ID.test(path[1]) &&
        path[2] === "keys" &&
        ["GET", "POST"].includes(request.method)) ||
      (path.length === 4 &&
        RESOURCE_ID.test(path[1]) &&
        path[2] === "keys" &&
        RESOURCE_ID.test(path[3]) &&
        ["PATCH", "DELETE"].includes(request.method)));
  const usageRoute =
    path[0] === "workspaces" &&
    path.length === 3 &&
    /^[a-z0-9][a-z0-9_]{0,53}$/.test(path[1]) &&
    path[2] === "usage" &&
    request.method === "GET";
  const workspaceRoute =
    path[0] === "workspaces" &&
    request.method === "GET" &&
    (path.length === 1 || (path.length === 2 && /^[a-z0-9][a-z0-9_]{0,53}$/.test(path[1])));
  if (!usersRoute && !workspaceRoute && !usageRoute && !identityRoute)
    return failure("not_found", "Unknown management route", 404);
  const target = new URL(contextDBUrl(`/${path.map(encodeURIComponent).join("/")}`));
  const incoming = new URL(request.url);
  if (usageRoute) {
    const kind = incoming.searchParams.getAll("object_type");
    const ids = incoming.searchParams.getAll("ids");
    if (
      kind.length !== 1 ||
      !["memory", "knowledge_page"].includes(kind[0]) ||
      ids.length < 1 ||
      ids.length > 100 ||
      ids.some((id) => !id || id.length > 64) ||
      [...incoming.searchParams.keys()].some((key) => !["object_type", "ids"].includes(key))
    ) {
      return failure("invalid_request", "Use one object type and 1 to 100 object IDs", 400);
    }
    target.searchParams.set("object_type", kind[0]);
    ids.forEach((id) => target.searchParams.append("ids", id));
  }
  for (const key of usageRoute || identityRoute ? [] : ["limit", "offset", "q"]) {
    if (incoming.searchParams.getAll(key).length > 1)
      return failure("invalid_request", "Duplicate query parameter", 400);
    const value = incoming.searchParams.get(key);
    if (value !== null) target.searchParams.set(key, value);
  }
  const headers = contextDBHeaders();
  if (request.method === "PATCH") {
    const version = request.headers.get("if-match");
    if (!version || version.length > 24 || !/^"[1-9][0-9]*"$/.test(version)) {
      return failure(
        "invalid_request",
        "If-Match must be a quoted positive version (maximum 24 characters)",
        400
      );
    }
    headers.set("If-Match", version);
  }
  let body: string | undefined;
  if (request.method === "POST" || request.method === "PATCH") {
    try {
      const input: unknown = await request.json();
      if (!input || typeof input !== "object" || Array.isArray(input))
        throw new Error("Invalid body");
      // Python input models reject unknown fields and validate permissions.
      // Keep that contract in one place; route/method/session/CSRF checks stay here.
      body = JSON.stringify(input);
      headers.set("Content-Type", "application/json");
    } catch {
      return failure("invalid_request", "Invalid management request body", 400);
    }
  }
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    const responseHeaders = new Headers(NO_STORE);
    for (const name of ["ETag", "X-Request-ID"]) {
      const value = upstream.headers.get(name);
      if (value) responseHeaders.set(name, value);
    }
    if (upstream.status === 204)
      return new NextResponse(null, { status: 204, headers: responseHeaders });
    if (upstream.status >= 500) {
      const failedRequestId = responseHeaders.get("X-Request-ID") ?? requestId;
      responseHeaders.set("X-Request-ID", failedRequestId);
      return NextResponse.json(
        {
          code: "service_unavailable",
          message: "ContextBase management service is unavailable",
          request_id: failedRequestId,
        },
        { status: upstream.status, headers: responseHeaders }
      );
    }
    const data: unknown = await upstream.json();
    // Never relay secret/digest fields on metadata or error responses. The only
    // exception is successful creation, which displays the secret once in memory.
    const keyCreated =
      upstream.ok && path[0] === "users" && request.method === "POST" && path.length === 3;
    const safe = JSON.parse(
      JSON.stringify(data, (key, value) =>
        /digest|secret/i.test(key) && !(keyCreated && key === "secret") ? undefined : value
      )
    );
    return NextResponse.json(safe, { status: upstream.status, headers: responseHeaders });
  } catch {
    // Fetch exceptions can include headers/URLs. Do not log them with admin keys.
    return failure("service_unavailable", "ContextBase management service is unavailable", 503);
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
