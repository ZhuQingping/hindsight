import { controlPlaneEnv } from "@/lib/control-plane-env";
import { contextDBEnabled, verifyContextDBAdmin } from "@/lib/contextdb";
import { NextRequest, NextResponse } from "next/server";
import { localizeApiErrorPayload } from "@/lib/i18n/api-errors";

import {
  sessionCookieName,
  SESSION_MAX_AGE_SECONDS,
  createSessionToken,
  sessionCookieOptions,
  authConfigured,
  trustedMutation,
} from "@/lib/auth/session";

export async function POST(request: NextRequest) {
  const accessKey = controlPlaneEnv("ACCESS_KEY");

  if (!authConfigured())
    return NextResponse.json({ error: "Protected UI is not configured" }, { status: 503 });
  if (!trustedMutation(request))
    return NextResponse.json({ error: "Untrusted request origin" }, { status: 403 });

  // If no access key is configured, return 503
  if (!accessKey) {
    return NextResponse.json(
      localizeApiErrorPayload(request, {
        error: "Access key not configured",
        errorKey: "api.errors.auth.accessKeyNotConfigured",
      }),
      { status: 503 }
    );
  }

  let body: { key?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      localizeApiErrorPayload(request, {
        error: "Invalid request body",
        errorKey: "api.errors.auth.invalidRequestBody",
      }),
      { status: 400 }
    );
  }

  const providedKey = body && typeof body.key === "string" ? body.key : undefined;

  // Constant-time comparison to prevent timing attacks
  const isValid = typeof providedKey === "string" && constantTimeCompare(providedKey, accessKey);

  if (!isValid) {
    return NextResponse.json(
      localizeApiErrorPayload(request, {
        error: "Invalid access key",
        errorKey: "api.errors.auth.invalidAccessKey",
      }),
      { status: 401 }
    );
  }

  if (contextDBEnabled()) {
    const denied = await verifyContextDBAdmin();
    if (denied) return denied;
  }

  let token: string;
  try {
    token = await createSessionToken(accessKey);
  } catch {
    return NextResponse.json({ error: "Session storage unavailable" }, { status: 503 });
  }
  const response = NextResponse.json({ success: true });
  response.headers.set("Cache-Control", "no-store");

  response.cookies.set({
    name: sessionCookieName(),
    value: token,
    ...sessionCookieOptions(request),
    maxAge: SESSION_MAX_AGE_SECONDS,
  });

  return response;
}

/**
 * Constant-time string comparison to prevent timing attacks.
 */
function constantTimeCompare(a: string, b: string): boolean {
  if (a.length !== b.length) {
    return false;
  }

  let result = 0;
  for (let i = 0; i < a.length; i++) {
    result |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }

  return result === 0;
}
