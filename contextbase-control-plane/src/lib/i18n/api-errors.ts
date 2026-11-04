import { contextDBEnabled } from "@/lib/contextdb";
import { contextdbWorkspaceMessages } from "@/i18n/contextdb-messages";
import { NextResponse } from "next/server";
import { match } from "@formatjs/intl-localematcher";
import Negotiator from "negotiator";
import { defaultLocale, locales, type Locale } from "@/i18n/config";

import en from "@/messages/en.json";
import zhCN from "@/messages/zh-CN.json";

type CookieValue = string | { value?: string } | undefined;
export type RequestLike = {
  headers?: Headers;
  cookies?: {
    get: (name: string) => CookieValue;
  };
};

type ApiErrorPayload = Record<string, unknown> & {
  errorKey: string;
};

const resources = {
  en,
  "zh-CN": zhCN,
} satisfies Record<Locale, Record<string, unknown>>;

const localeSet = new Set<string>(locales);
const localizedErrorFields = ["error", "message", "detail", "details"] as const;

function parseCookieHeader(cookieHeader: string | null | undefined): Map<string, string> {
  const cookies = new Map<string, string>();
  if (!cookieHeader) return cookies;

  for (const cookie of cookieHeader.split(";")) {
    const separatorIndex = cookie.indexOf("=");
    if (separatorIndex === -1) continue;

    const key = cookie.slice(0, separatorIndex).trim();
    const value = cookie.slice(separatorIndex + 1).trim();
    if (!key) continue;

    try {
      cookies.set(key, decodeURIComponent(value));
    } catch {
      cookies.set(key, value);
    }
  }

  return cookies;
}

function getCookieLocale(request: RequestLike | undefined): string | undefined {
  // Page routing reads NEXT_LOCALE; obsolete cookie names must not override it.
  const cookieValue = request?.cookies?.get("NEXT_LOCALE");
  if (typeof cookieValue === "string") return cookieValue;
  if (cookieValue?.value) return cookieValue.value;
  return parseCookieHeader(request?.headers?.get("cookie")).get("NEXT_LOCALE");
}

export function resolveApiErrorLocale(request?: RequestLike): Locale {
  // Match page routing: retired locale cookies are ignored before negotiating
  // Accept-Language, so a previous selection cannot override the current UI.
  const cookieLocale = getCookieLocale(request);
  if (cookieLocale && localeSet.has(cookieLocale)) return cookieLocale as Locale;

  // Use the same parser, best-fit matcher and locale order as next-intl.
  // Prefix matching disagreed for Cantonese and script/region preferences.
  const languages = new Negotiator({
    headers: { "accept-language": request?.headers?.get("accept-language") || undefined },
  }).languages();
  try {
    const orderedLocales = [...locales].sort((a, b) => b.length - a.length);
    const matched = match(languages, orderedLocales, defaultLocale);
    return (
      locales.find((locale) => locale.toLowerCase() === matched.toLowerCase()) ?? defaultLocale
    );
  } catch {
    // next-intl also falls back to the default for invalid language tags.
    return defaultLocale;
  }
}

function getTranslationValue(locale: Locale, key: string): string | undefined {
  let current: unknown = resources[locale];

  for (const part of key.split(".")) {
    if (!current || typeof current !== "object" || !(part in current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[part];
  }

  if (typeof current !== "string") return undefined;
  return contextDBEnabled()
    ? contextdbWorkspaceMessages({ message: current }, locale).message
    : current;
}

function getFallbackMessage(payload: ApiErrorPayload): string | undefined {
  for (const field of localizedErrorFields) {
    const value = payload[field];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }

  return undefined;
}

export function translateApiError(
  errorKey: string,
  fallbackMessage?: string,
  request?: RequestLike
): string {
  const locale = resolveApiErrorLocale(request);

  return (
    getTranslationValue(locale, errorKey) ??
    getTranslationValue(defaultLocale, errorKey) ??
    fallbackMessage ??
    errorKey
  );
}

export function localizeApiErrorPayload<TPayload extends ApiErrorPayload>(
  request: RequestLike | undefined,
  payload: TPayload
): TPayload {
  const message = translateApiError(payload.errorKey, getFallbackMessage(payload), request);
  const localizedPayload: Record<string, unknown> = { ...payload };
  delete localizedPayload.errorKey;
  let updatedExistingField = false;

  for (const field of localizedErrorFields) {
    if (field in localizedPayload && typeof localizedPayload[field] === "string") {
      localizedPayload[field] = message;
      updatedExistingField = true;
    }
  }

  if (!updatedExistingField) {
    localizedPayload.error = message;
  }

  return localizedPayload as TPayload;
}

/** 400 response for a missing required query parameter on a control-plane route. */
export function missingQueryParam(
  request: RequestLike | undefined,
  name: "bank_id" | "document_id" | "chunk_id"
): NextResponse {
  return NextResponse.json(
    localizeApiErrorPayload(request, {
      error: `${name} is required`,
      errorKey:
        name === "bank_id"
          ? "api.errors.validation.bankIdRequired"
          : "api.errors.validation.missingRequestData",
    }),
    { status: 400 }
  );
}
