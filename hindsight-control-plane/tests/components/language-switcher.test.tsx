// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LanguageSwitcher } from "@/components/language-switcher";

const navigation = vi.hoisted(() => ({ replace: vi.fn(), pathname: "/banks/A" }));
vi.mock("@/i18n/navigation", () => ({
  useRouter: () => ({ replace: navigation.replace }),
  usePathname: () => navigation.pathname,
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
  navigation.replace.mockClear();
  window.history.replaceState(null, "", "/");
});

it("keeps the Bank configuration view, repeated filters and fragment when changing language", () => {
  window.history.replaceState(null, "", "/banks/A?view=profile&bankConfigTab=general&tag=x&tag=y#security");
  render(<LanguageSwitcher />);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(navigation.replace).toHaveBeenCalledWith(
    "/banks/A?view=profile&bankConfigTab=general&tag=x&tag=y#security",
    { locale: "en" }
  );
});

it("keeps a route without query parameters clean", () => {
  window.history.replaceState(null, "", "/banks/A");
  render(<LanguageSwitcher />);
  fireEvent.click(screen.getByRole("button", { name: "English" }));
  expect(navigation.replace).toHaveBeenCalledWith("/banks/A", { locale: "en" });
});
