import { productGuard } from "@/lib/product-guard";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { localizeApiErrorPayload } from "@/lib/i18n/api-errors";
import createIntlMiddleware from "next-intl/middleware";

import {
  sessionCookieName,
  verifySessionToken,
  protectedMode,
  authConfigured,
  trustedMutation,
  publicOrigin,
} from "@/lib/auth/session";
import { stripBasePath, withBasePath } from "@/lib/base-path";
import { routing } from "@/i18n/routing";

const PUBLIC_API = new Set([
  "/api/auth/login",
  "/api/auth/logout",
  "/api/auth/session",
  "/api/health",
  "/api/version",
  "/api/product-config",
]);
function staticAsset(pathname: string): boolean {
  return (
    ["/logo.png", "/favicon.ico", "/favicon.png", "/product-icon.svg"].includes(pathname) ||
    ["/_next/", "/fonts/", "/static/", "/img/"].some((prefix) => pathname.startsWith(prefix))
  );
}

const intlMiddleware = createIntlMiddleware(routing);

export async function proxy(request: NextRequest) {
  const accessKey = process.env.HINDSIGHT_CP_ACCESS_KEY;
  const { pathname } = request.nextUrl;
  const appPathname = stripBasePath(pathname);

  if (staticAsset(appPathname)) return NextResponse.next();

  if (protectedMode()) {
    if (!authConfigured())
      return NextResponse.json({ error: "Protected UI is not configured" }, { status: 503 });
    if (request.headers.get("host") !== new URL(publicOrigin()!).host) {
      return NextResponse.json({ error: "Unexpected request host" }, { status: 421 });
    }
    // This legacy GET submits a native asynchronous export, so it has a write
    // side effect. Browser Fetch Metadata guards it without changing its UI URL.
    if (
      ["GET", "HEAD"].includes(request.method) &&
      appPathname === "/api/documents/transfer" &&
      request.headers.get("sec-fetch-site") !== "same-origin"
    ) {
      return NextResponse.json({ error: "Untrusted export request" }, { status: 403 });
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method) && !trustedMutation(request)) {
      return NextResponse.json({ error: "Untrusted request origin" }, { status: 403 });
    }
  }

  // API routes are not locale-prefixed — handle auth directly without i18n routing.
  if (appPathname.startsWith("/api/")) {
    if (!protectedMode()) {
      return PUBLIC_API.has(appPathname)
        ? NextResponse.next()
        : ((await productGuard(request)) ?? NextResponse.next());
    }

    const isPublic = PUBLIC_API.has(appPathname);
    if (isPublic) {
      return NextResponse.next();
    }

    const sessionCookie = request.cookies.get(sessionCookieName())?.value;
    const isAuthenticated = await verifySessionToken(sessionCookie, accessKey!);

    if (!isAuthenticated) {
      return NextResponse.json(
        localizeApiErrorPayload(request, {
          error: "Unauthorized",
          errorKey: "api.errors.auth.unauthorized",
        }),
        { status: 401 }
      );
    }

    const productFailure = await productGuard(request);
    if (productFailure) return productFailure;
    const response = NextResponse.next();
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  }

  // Page routes: enforce auth first, then delegate to the i18n middleware for
  // locale negotiation and rewriting. With localePrefix "never" the locale is
  // never in the path, so appPathname is already the canonical route.
  if (protectedMode()) {
    const isPublic = appPathname === "/login";

    if (!isPublic) {
      const sessionCookie = request.cookies.get(sessionCookieName())?.value;
      const isAuthenticated = await verifySessionToken(sessionCookie, accessKey!);

      if (!isAuthenticated) {
        // Next.js middleware redirects do not automatically inherit next.config basePath.
        // Prefix the target explicitly, but keep returnTo as the app-relative path so
        // client-side router.push() does not double-prefix after login.
        const loginUrl = new URL(withBasePath("/login"), publicOrigin()!);
        loginUrl.searchParams.set("returnTo", appPathname + request.nextUrl.search);
        return NextResponse.redirect(loginUrl);
      }
    }
  }

  const response = intlMiddleware(request);
  // Localized redirects are browser-visible; use the configured public origin
  // even when a trusted gateway reaches Next over a different internal URL.
  const location = response.headers.get("location");
  if (protectedMode() && location) {
    const target = new URL(location, request.url);
    response.headers.set(
      "location",
      new URL(target.pathname + target.search + target.hash, publicOrigin()!).toString()
    );
  }
  return response;
}

// Include ALL dynamic routes: a bank/file named *.json or *.png is not a static asset.
export const config = { matcher: "/:path*" };
