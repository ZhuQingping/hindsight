import type { Metadata } from "next";
import { connection } from "next/server";
import { localProductName } from "@/lib/product-config-server";
import { ProductRuntime } from "@/components/product-runtime";
import { withBasePath } from "@/lib/base-path";
import { contextDBEnabled } from "@/lib/contextdb";
import { ContextDBModeProvider } from "@/lib/contextdb-mode";
import { NextIntlClientProvider, hasLocale } from "next-intl";
import { setRequestLocale } from "next-intl/server";
import { notFound } from "next/navigation";
import { routing } from "@/i18n/routing";
import { BankProvider } from "@/lib/bank-context";
import { FeaturesProvider } from "@/lib/features-context";
import { ThemeProvider } from "@/lib/theme-context";
import { Toaster } from "@/components/ui/sonner";

// Font stacks are local system fonts in globals.css. Production builds never
// fetch font resources, including in isolated/private deployment environments.

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}): Promise<Metadata> {
  await connection();
  const { locale } = await params;
  const name = localProductName();
  const description = locale === "zh-CN" ? "面向 Agent 的数据底座" : "A data foundation for agents";
  return {
    title: `${name} | ${description}`,
    description,
    icons: { icon: withBasePath("/product-icon.svg") },
  };
}

// Anti-FOUC: apply the theme's `.dark` class before first paint. ThemeProvider
// only reads localStorage/system preference in a useEffect (after paint), so
// without this a dark-mode user gets a light flash on every hard refresh. This
// runs synchronously as the first <body> child, before the content below it
// paints. Keep the logic identical to lib/theme-context.tsx (saved || system).
const THEME_INIT_SCRIPT = `
(function () {
  try {
    var saved = localStorage.getItem('theme');
    var dark = saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.classList.toggle('dark', dark);
  } catch (e) {}
})();
`;

export default async function LocaleLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  await connection();
  const name = localProductName();
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) {
    notFound();
  }

  setRequestLocale(locale);

  return (
    <html
      lang={locale === "zh-CN" ? "zh-CN" : "en"}
      data-contextdb-name={name}
      suppressHydrationWarning
    >
      <body className="bg-background text-foreground">
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        <ProductRuntime name={name} locale={locale}>
          <ContextDBModeProvider enabled={contextDBEnabled()}>
            <ThemeProvider>
              <FeaturesProvider>
                <BankProvider>
                  <NextIntlClientProvider>{children}</NextIntlClientProvider>
                </BankProvider>
              </FeaturesProvider>
            </ThemeProvider>
          </ContextDBModeProvider>
          <Toaster />
        </ProductRuntime>
      </body>
    </html>
  );
}
