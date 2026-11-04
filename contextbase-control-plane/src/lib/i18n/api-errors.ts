import { contextDBEnabled } from "@/lib/contextdb";
import { contextdbWorkspaceMessages } from "@/i18n/contextdb-messages";
import { NextResponse } from "next/server";
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
const localeCookieNames = ["NEXT_LOCALE", "contextbase_cp_locale"] as const;

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
  const parsedCookies = parseCookieHeader(request?.headers?.get("cookie"));

  for (const cookieName of localeCookieNames) {
    const cookieValue = request?.cookies?.get(cookieName);
    if (typeof cookieValue === "string") return cookieValue;
    if (cookieValue?.value) return cookieValue.value;

    const parsedValue = parsedCookies.get(cookieName);
    if (parsedValue) return parsedValue;
  }

  return undefined;
}

function parseAcceptLanguage(header: string | null | undefined): string[] {
  if (!header) return [];

  return header
    .split(",")
    .map((entry) => {
      const [tag, ...parameters] = entry.trim().split(";");
      const quality = parameters
        .map((parameter) => parameter.trim())
        .find((parameter) => parameter.startsWith("q="));
      const parsedQuality = quality ? Number.parseFloat(quality.slice(2)) : 1;

      return {
        tag,
        quality: Number.isFinite(parsedQuality) ? parsedQuality : 0,
      };
    })
    .filter(({ tag }) => tag.length > 0)
    .sort((a, b) => b.quality - a.quality)
    .map(({ tag }) => tag);
}

function resolveLocaleTag(value: string | undefined): Locale | undefined {
  if (!value) return undefined;
  if (localeSet.has(value)) return value as Locale;

  const normalized = value.toLowerCase();
  const exact = locales.find((locale) => locale.toLowerCase() === normalized);
  if (exact) return exact;

  const language = normalized.split("-")[0];
  return locales.find((locale) => locale.split("-")[0] === language);
}

export function resolveApiErrorLocale(request?: RequestLike): Locale {
  // Match page routing: retired locale cookies are ignored before negotiating
  // Accept-Language, so a previous selection cannot override the current UI.
  const cookieLocale = getCookieLocale(request);
  if (cookieLocale && localeSet.has(cookieLocale)) return cookieLocale as Locale;

  const candidates = parseAcceptLanguage(request?.headers?.get("accept-language"));

  for (const candidate of candidates) {
    const locale = resolveLocaleTag(candidate);
    if (locale) return locale;
  }

  return defaultLocale;
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
