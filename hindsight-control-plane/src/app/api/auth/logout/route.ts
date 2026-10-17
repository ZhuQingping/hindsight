import { NextRequest, NextResponse } from "next/server";

import {
  sessionCookieName,
  sessionCookieOptions,
  revokeSessionToken,
  trustedMutation,
} from "@/lib/auth/session";

export async function POST(request: NextRequest) {
  if (!trustedMutation(request))
    return NextResponse.json({ error: "Untrusted request origin" }, { status: 403 });
  try {
    await revokeSessionToken(request.cookies.get(sessionCookieName())?.value);
  } catch {
    return NextResponse.json({ error: "Session revocation unavailable" }, { status: 503 });
  }
  const response = NextResponse.json({ success: true });

  response.headers.set("Cache-Control", "no-store");
  response.cookies.set({
    name: sessionCookieName(),
    value: "",
    ...sessionCookieOptions(request),
    maxAge: 0,
  });

  return response;
}
