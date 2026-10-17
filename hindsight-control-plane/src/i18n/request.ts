import { localProductConfig } from "@/lib/product-config-server";
import type { AbstractIntlMessages } from "next-intl";
import { connection } from "next/server";
import { getRequestConfig } from "next-intl/server";
import { hasLocale } from "next-intl";
import { routing } from "./routing";
import { messageLocale } from "./config";

// Static imports keep Turbopack/Webpack happy — dynamic template imports
// don't resolve at build time.
const loaders = {
  en: () => import("../messages/en.json"),
  "zh-CN": () => import("../messages/zh-CN.json"),
} as const;

function brandMessages(messages: AbstractIntlMessages, name: string): AbstractIntlMessages {
  return Object.fromEntries(
    Object.entries(messages).map(([key, value]) => [
      key,
      typeof value === "string"
        ? value.replaceAll("{productName}", name)
        : brandMessages(value, name),
    ])
  );
}

export default getRequestConfig(async ({ requestLocale }) => {
  await connection();
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;

  return {
    locale,
    // Other retained locale choices explicitly fall back to the complete English main flows.
    messages: brandMessages(
      (await loaders[messageLocale(locale)]()).default,
      localProductConfig().contextdb_name
    ),
  };
});
