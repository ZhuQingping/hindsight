import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { localizeApiErrorPayload } from "@/lib/i18n/api-errors";
import createIntlMiddleware from "next-intl/middleware";

import {
  contextDBEnabled,
  contextDBConfigurationError,
  verifyContextDBAdmin,
  isContextDBLifecycleRequest,
  contextDBLifecycleDenied,
  requireSameOrigin,
} from "@/lib/contextdb";
import { ACCESS_KEY_COOKIE, verifySessionToken } from "@/lib/auth/session";
import { stripBasePath, withBasePath } from "@/lib/base-path";
import { routing } from "@/i18n/routing";

// Routes that don't require authentication
const PUBLIC_PATTERNS = [
  "/login",
  "/api/auth/",
  "/api/health",
  "/api/version",
  "/logo.png",
  "/favicon",
  "/_next",
  "/fonts",
  "/static",
];

const intlMiddleware = createIntlMiddleware(routing);

export async function middleware(request: NextRequest) {
  const accessKey = process.env.HINDSIGHT_CP_ACCESS_KEY;
  const { pathname } = request.nextUrl;
  const appPathname = stripBasePath(pathname);
  const contextDB = contextDBEnabled();
  const localePrefix = appPathname.split("/")[1];
  // next-intl rewrites /login to /en/login internally. Authenticate the page's
  // canonical path, but never treat a locale-prefixed path as a public API.
  const pagePathname =
    contextDB &&
    !appPathname.startsWith("/api/") &&
    routing.locales.some((locale) => locale === localePrefix)
      ? appPathname.slice(localePrefix.length + 1) || "/"
      : appPathname;
  const publicPage =
    pagePathname !== appPathname
      ? pagePathname === "/login"
      : PUBLIC_PATTERNS.some((pattern) => appPathname.startsWith(pattern));

  if (contextDB) {
    const error = contextDBConfigurationError();
    if (error) return NextResponse.json({ error }, { status: 503 });
    if (!publicPage) {
      const session = request.cookies.get(ACCESS_KEY_COOKIE)?.value;
      if (await verifySessionToken(session, accessKey!)) {
        const originDenied = requireSameOrigin(request);
        if (originDenied) return originDenied;
        // Management proxies call admin-only endpoints that verify the current Key.
        // Native data endpoints still need this separate role check.
        if (!appPathname.startsWith("/api/contextdb/")) {
          const denied = await verifyContextDBAdmin();
          if (denied) return denied;
        }
        if (isContextDBLifecycleRequest(appPathname, request.method))
          return contextDBLifecycleDenied();
      }
    }
  }

  // API routes are not locale-prefixed — handle auth directly without i18n routing.
  if (appPathname.startsWith("/api/")) {
    if (!accessKey) {
      return NextResponse.next();
    }

    const isPublic = PUBLIC_PATTERNS.some((pattern) => appPathname.startsWith(pattern));
    if (isPublic) {
      return NextResponse.next();
    }

    const sessionCookie = request.cookies.get(ACCESS_KEY_COOKIE)?.value;
    const isAuthenticated = await verifySessionToken(sessionCookie, accessKey);

    if (!isAuthenticated) {
      return NextResponse.json(
        localizeApiErrorPayload(request, {
          error: "Unauthorized",
          errorKey: "api.errors.auth.unauthorized",
        }),
        { status: 401 }
      );
    }

    return NextResponse.next();
  }

  // Page routes: enforce auth first, then delegate to the i18n middleware for
  // locale negotiation and rewriting. ContextDB also sees the internal locale
  // prefix after a rewrite; native Hindsight routing remains unchanged.
  if (accessKey) {
    if (!publicPage) {
      const sessionCookie = request.cookies.get(ACCESS_KEY_COOKIE)?.value;
      const isAuthenticated = await verifySessionToken(sessionCookie, accessKey);

      if (!isAuthenticated) {
        // Next.js middleware redirects do not automatically inherit next.config basePath.
        // Prefix the target explicitly, but keep returnTo as the app-relative path so
        // client-side router.push() does not double-prefix after login.
        const loginUrl = new URL(withBasePath("/login"), request.url);
        loginUrl.searchParams.set("returnTo", pagePathname);
        return NextResponse.redirect(loginUrl);
      }
    }
  }

  // Re-entering next-intl with its already rewritten path redirects back to
  // /login under localePrefix "never". Finish routing to [locale] after auth.
  if (contextDB && pagePathname !== appPathname) return NextResponse.next();
  return intlMiddleware(request);
}

export const config = {
  // Match all paths except Next.js internals and static assets.
  // - Use an explicit file extension allowlist instead of .*\..* so that
  //   dynamic segments containing dots (e.g. bank IDs like
  //   "SX.Products.GovComply.Build") still get the i18n locale rewrite.
  // API resource IDs can end in a static-looking extension. They still inject
  // the server credential, so they must never bypass session/CSRF checks.
  matcher: [
    "/api/:path*",
    "/((?!_next|_vercel|.*\\.(?:png|jpe?g|gif|svg|webp|ico|css|js|map|woff2?|ttf|eot|txt|xml|json)$).*)",
  ],
};
