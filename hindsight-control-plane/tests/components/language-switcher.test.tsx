// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LanguageSwitcher } from "@/components/language-switcher";

const navigation = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: navigation.refresh }),
}));
vi.mock("next-intl", () => ({
  useLocale: () => "zh-CN",
  useTranslations: () => (key: string) => key,
}));
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: (props: ComponentProps<"button">) => <button {...props} />,
}));

afterEach(() => {
  cleanup();
  navigation.refresh.mockClear();
  document.cookie = "NEXT_LOCALE=; path=/; max-age=0";
  document.cookie = "NEXT_LOCALE=; path=/brand-ui; max-age=0";
  vi.unstubAllEnvs();
  window.history.replaceState(null, "", "/");
});

it.each([
  "/banks/A?view=profile&bankConfigTab=general&tag=x&tag=y#security",
  "/banks/A",
])("changes the locale while refreshing the exact current URL %s", (url) => {
  window.history.replaceState(null, "", url);
  render(<LanguageSwitcher />);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(document.cookie).toContain("NEXT_LOCALE=en");
  expect(navigation.refresh).toHaveBeenCalledOnce();
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(url);
});

it("scopes the locale cookie to the UI base path without changing encoded IDs or fragments", () => {
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/brand-ui");
  const url = "/brand-ui/connect?bank_id=team%2Fmemory&tag=x&tag=y#credentials";
  window.history.replaceState(null, "", url);
  render(<LanguageSwitcher />);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(document.cookie).toContain("NEXT_LOCALE=en");
  expect(window.location.pathname + window.location.search + window.location.hash).toBe(url);
  expect(navigation.refresh).toHaveBeenCalledOnce();
  window.history.replaceState(null, "", "/another-instance");
  expect(document.cookie).not.toContain("NEXT_LOCALE");
});
