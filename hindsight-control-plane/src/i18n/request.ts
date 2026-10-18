import { getRequestConfig } from "next-intl/server";
import { hasLocale } from "next-intl";
import { routing } from "./routing";
import { contextdbWorkspaceMessages } from "./contextdb-messages";

// Static imports keep Turbopack/Webpack happy — dynamic template imports
// don't resolve at build time.
const loaders = {
  en: () => import("../messages/en.json"),
  es: () => import("../messages/es.json"),
  fr: () => import("../messages/fr.json"),
  de: () => import("../messages/de.json"),
  pt: () => import("../messages/pt.json"),
  ja: () => import("../messages/ja.json"),
  ko: () => import("../messages/ko.json"),
  "zh-CN": () => import("../messages/zh-CN.json"),
  "zh-TW": () => import("../messages/zh-TW.json"),
  "yue-Hant": () => import("../messages/yue-Hant.json"),
} as const;

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  const messages = (await loaders[locale]()).default;

  return {
    locale,
    messages:
      process.env.HINDSIGHT_CP_CONTEXTDB_ENABLED === "true"
        ? contextdbWorkspaceMessages(messages, locale)
        : messages,
  };
});
