import "server-only";

import { NextResponse } from "next/server";
import {
  authConfigured,
  publicOrigin,
  sessionCookieName,
  verifySessionToken,
} from "@/lib/auth/session";
import { controlPlaneEnv } from "@/lib/control-plane-env";

export function contextDBEnabled(): boolean {
  return controlPlaneEnv("CONTEXTDB_ENABLED") === "true";
}

export function contextDBConfigurationError(): string | null {
  if (!controlPlaneEnv("ACCESS_KEY") || !controlPlaneEnv("DATAPLANE_API_KEY")) {
    return "ContextDB requires both a UI access password and a server admin API key";
  }
  const password = controlPlaneEnv("ACCESS_KEY")!;
  if (
    password === controlPlaneEnv("DATAPLANE_API_KEY") ||
    /^ctx_(live|ctrl|admin)_/.test(password)
  ) {
    return "The UI password must be independent from ContextDB API keys";
  }
  if (!authConfigured()) {
    return "ContextDB requires local UI authentication, PUBLIC_ORIGIN and an absolute SESSION_DIR";
  }
  return null;
}

function requireSameOrigin(request: Request): NextResponse | null {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return null;
  const origin = request.headers.get("origin");
  const fetchSite = request.headers.get("sec-fetch-site");
  // Share the team's configured-origin contract; forwarded headers never grant trust.
  const configured = publicOrigin();
  const valid = Boolean(
    configured &&
    origin === configured &&
    request.headers.get("host") === new URL(configured).host &&
    (!fetchSite || fetchSite === "same-origin")
  );
  if (!valid) {
    return NextResponse.json({ error: "A same-origin request is required" }, { status: 403 });
  }
  return null;
}

// Only server configuration chooses the host and key; browser headers and bodies
// are never used to configure a shared dataplane client.
export function contextDBHeaders(): Headers {
  return new Headers({ Authorization: `Bearer ${controlPlaneEnv("DATAPLANE_API_KEY")}` });
}

export function contextDBUrl(path: string): string {
  const base = controlPlaneEnv("DATAPLANE_API_URL") || "http://localhost:8888";
  return `${base.replace(/\/$/, "")}/ext/contextdb/v1${path}`;
}

interface AdminFailure {
  status: number;
  error: string;
  retryable: boolean;
}

async function checkContextDBAdmin(timeoutMs = 10000): Promise<AdminFailure | null> {
  const error = contextDBConfigurationError();
  if (error) return { error, status: 503, retryable: false };
  try {
    // Never cache authorization: disabled users and revoked keys must stop the
    // next UI request, including requests made with an existing session cookie.
    const response = await fetch(contextDBUrl("/admin/identity"), {
      headers: contextDBHeaders(),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      const unauthorized = response.status === 401 || response.status === 403;
      return {
        error: unauthorized
          ? "The configured server administrator key is invalid"
          : "The backend service is unavailable",
        status: unauthorized ? response.status : 503,
        retryable: response.status >= 500 || response.status === 429,
      };
    }
    let session: unknown;
    try {
      session = await response.json();
    } catch {
      return {
        error: "The administrator identity response is invalid",
        status: 503,
        retryable: false,
      };
    }
    if (
      !session ||
      typeof session !== "object" ||
      !("role" in session) ||
      session.role !== "admin"
    ) {
      return {
        error: "The configured operator admin key is required",
        status: 403,
        retryable: false,
      };
    }
    return null;
  } catch {
    return { error: "Unable to connect to the backend service", status: 503, retryable: true };
  }
}

export async function verifyContextDBAdmin(): Promise<NextResponse | null> {
  const failure = await checkContextDBAdmin();
  return failure ? NextResponse.json({ error: failure.error }, { status: failure.status }) : null;
}

/** Startup only: dependency retries never cache authority for subsequent requests. */
export async function waitForContextDBAdmin(timeoutMs = 30000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let pause = 250;
  while (true) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error("Timed out waiting for the backend service");
    const failure = await checkContextDBAdmin(Math.min(remaining, 10000));
    if (!failure) return;
    if (!failure.retryable) throw new Error(failure.error);
    const wait = Math.min(pause, deadline - Date.now());
    if (wait <= 0) throw new Error(failure.error);
    await new Promise((resolve) => setTimeout(resolve, wait));
    pause = Math.min(pause * 2, 2000);
  }
}

export async function requireContextDBAdmin(
  request: Request,
  verifyBackend = true
): Promise<NextResponse | null> {
  if (!contextDBEnabled())
    return NextResponse.json({ error: "ContextDB administration is not enabled" }, { status: 404 });
  const configurationError = contextDBConfigurationError();
  if (configurationError) return NextResponse.json({ error: configurationError }, { status: 503 });
  const cookieName = sessionCookieName();
  const cookie = request.headers
    .get("cookie")
    ?.split(";")
    .map((v) => v.trim())
    .find((v) => v.startsWith(`${cookieName}=`))
    ?.slice(cookieName.length + 1);
  if (!(await verifySessionToken(cookie, controlPlaneEnv("ACCESS_KEY")!))) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const originDenied = requireSameOrigin(request);
  if (originDenied) return originDenied;
  // Defense in depth: these routes remain closed even if the proxy is bypassed.
  return verifyBackend ? verifyContextDBAdmin() : null;
}

export function contextDBLifecycleDenied(): NextResponse {
  return NextResponse.json(
    { error: "Use workspace management to create or delete workspaces" },
    { status: 403 }
  );
}

export function isContextDBLifecycleRequest(path: string, method: string): boolean {
  if (method === "GET" || method === "HEAD") return false;
  if (path === "/api/banks") return true;
  if (/^\/api\/banks\/[^/]+$/.test(path)) return method === "PUT" || method === "DELETE";
  return /^\/api\/banks\/[^/]+\/(clone|restore|import|aliases)(\/|$)/.test(path);
}
