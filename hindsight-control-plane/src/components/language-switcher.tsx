"use client";

import { useLocale } from "next-intl";
import { useRouter } from "next/navigation";
import { normalizeBasePath } from "@/lib/base-path";
import { locales, localeNames, type Locale } from "@/i18n/config";
import { useTranslations } from "next-intl";
import { Globe } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

export function LanguageSwitcher() {
  const locale = useLocale();
  const t = useTranslations("common");
  const router = useRouter();

  function handleLocaleChange(newLocale: Locale) {
    // With localePrefix "never", next-intl's locale replace still forces a
    // prefixed URL and a canonical redirect, which drops fragments in Next's
    // client navigation. Update the locale cookie and refresh the current URL
    // instead, preserving the workspace, repeated filters and fragment.
    document.cookie = `NEXT_LOCALE=${newLocale}; path=${normalizeBasePath() || "/"}; SameSite=Lax`;
    router.refresh();
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" title={t("changeLanguage")}>
          <Globe className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {locales.map((l) => (
          <DropdownMenuItem
            key={l}
            onClick={() => handleLocaleChange(l)}
            className={l === locale ? "bg-accent" : ""}
          >
            {localeNames[l]}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
