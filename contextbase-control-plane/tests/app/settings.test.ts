import { expect, it, vi } from "vitest";
const redirect = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ redirect }));
import SettingsPage from "@/app/[locale]/settings/page";
it("redirects the retired storage settings page to the workspace list", () => {
  SettingsPage();
  expect(redirect).toHaveBeenCalledWith("/dashboard");
});
