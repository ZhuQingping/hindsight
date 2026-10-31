// @vitest-environment jsdom
import type { ComponentProps } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { BankSelector } from "@/components/bank-selector";

const route = vi.hoisted(() => ({ pathname: "/", view: "home" }));
vi.mock("next/navigation", () => ({
  usePathname: () => route.pathname,
  useSearchParams: () => new URLSearchParams({ view: route.view }),
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("@/i18n/navigation", () => ({ Link: (props: ComponentProps<"a">) => <a {...props} /> }));
vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { rich: (key: string) => key }),
  useLocale: () => "en",
}));
vi.mock("@/lib/bank-context", () => ({
  BANKS_PAGE_SIZE: 50,
  useBank: () => ({ currentBank: "guide", bankInfos: [], bankSearch: "", banksLoading: false }),
}));
vi.mock("@/lib/theme-context", () => ({
  useTheme: () => ({ theme: "light", toggleTheme: vi.fn() }),
}));
vi.mock("@/lib/features-context", () => ({ useFeatures: () => ({ features: null }) }));
vi.mock("@/components/brand", () => ({ Brand: () => <span>contextbase</span> }));
vi.mock("@/components/language-switcher", () => ({ LanguageSwitcher: () => null }));
vi.mock("@/lib/api", () => ({
  client: { getVersion: async () => ({ features: { file_upload_api: false } }) },
}));
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

it.each(["", "/brand-ui"])(
  "distinguishes exact resource routes from native Workspace IDs under %s",
  (basePath) => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", basePath);
    for (const path of ["/banks/guide", "/banks/connect", "/banks/ordinary"]) {
      route.pathname = basePath + path;
      render(<BankSelector />);
      expect(screen.getByRole("button", { name: "addDocumentButton" })).toBeTruthy();
      cleanup();
    }
    for (const path of ["/guide", "/connect"]) {
      route.pathname = basePath + path;
      render(<BankSelector />);
      expect(screen.queryByRole("button", { name: "addDocumentButton" })).toBeNull();
      cleanup();
    }
  }
);

it("does not offer global storage settings", () => {
  render(<BankSelector />);
  expect(screen.queryByRole("link", { name: "settings" })).toBeNull();
});
