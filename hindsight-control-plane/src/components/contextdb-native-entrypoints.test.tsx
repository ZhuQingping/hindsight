// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BankSelector } from "./bank-selector";
import BankPage from "@/app/[locale]/banks/[bankId]/page";
import { contextDBRequest, workspaceMutation, ContextDBError } from "@/lib/contextdb-api";
const state = vi.hoisted(() => ({
  push: vi.fn(),
  setCurrentBank: vi.fn(),
  loadBanks: vi.fn().mockResolvedValue(undefined),
  bankId: "jiamu" as string | null,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => new URLSearchParams("view=profile"),
  useParams: () => ({ bankId: state.bankId }),
}));
vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { rich: (key: string) => key }),
}));
vi.mock("@/lib/contextdb-mode", () => ({ useContextDBMode: () => true }));
vi.mock("@/lib/theme-context", () => ({
  useTheme: () => ({ theme: "light", toggleTheme: vi.fn() }),
}));
vi.mock("@/lib/features-context", () => ({ useFeatures: () => ({ features: {} }) }));
vi.mock("@/lib/bank-context", () => ({
  BANKS_PAGE_SIZE: 50,
  useBank: () => ({
    currentBank: state.bankId,
    setCurrentBank: state.setCurrentBank,
    loadBanks: state.loadBanks,
    bankInfos: [],
    banksLoading: false,
    banksLoadingMore: false,
    hasMoreBanks: false,
    bankSearch: "",
    currentBankName: state.bankId,
    searchBanks: vi.fn(),
    loadMoreBanks: vi.fn(),
  }),
}));
vi.mock("@/lib/api", () => ({
  client: { getVersion: vi.fn().mockResolvedValue({ features: { file_upload_api: false } }) },
}));
vi.mock("@/components/language-switcher", () => ({ LanguageSwitcher: () => null }));
vi.mock("@/components/bank-profile-view", () => ({ BankProfileView: () => null }));
vi.mock("@/components/sidebar", () => ({ Sidebar: () => null }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
  DropdownMenuSeparator: () => null,
  DropdownMenuItem: ({
    children,
    onClick,
    disabled,
  }: React.PropsWithChildren<{ onClick?: () => void; disabled?: boolean }>) => (
    <button disabled={disabled} onClick={onClick}>
      {children}
    </button>
  ),
}));
vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  contextDBRequest: vi.fn(),
  workspaceMutation: vi.fn(),
}));
const api = vi.mocked(contextDBRequest);
const mutation = vi.mocked(workspaceMutation);
const etag = '"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:1"';
beforeEach(() => {
  state.bankId = "jiamu";
  api.mockResolvedValue({
    workspace_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    bank_id: "jiamu",
    etag,
    state: "active",
  });
  mutation.mockResolvedValue({
    workspace_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    operation_id: "op",
    state: "succeeded",
  });
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
describe("ContextDB native UI entry points", () => {
  it("creates from the native selector and navigates to canonical bank_id rather than operation UUID", async () => {
    render(<BankSelector />);
    act(() => window.dispatchEvent(new Event("hindsight:create-bank")));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("workspaceName"), {
      target: { value: "MySQL" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "create" }));
    await waitFor(() => expect(state.setCurrentBank).toHaveBeenCalledWith("mysql"));
    expect(state.push).toHaveBeenCalledWith("/banks/mysql?view=data");
    expect(mutation).toHaveBeenCalledWith(
      "/workspaces",
      "POST",
      expect.any(String),
      { name: "MySQL" },
      expect.any(AbortSignal)
    );
  });
  it("rejects hyphenated names in the selector and its Enter shortcut", async () => {
    render(<BankSelector />);
    act(() => window.dispatchEvent(new Event("hindsight:create-bank")));
    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByLabelText("workspaceName");
    fireEvent.change(input, { target: { value: "my-bank" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(within(dialog).getByRole("button", { name: "create" })).toHaveProperty("disabled", true);
    expect(mutation).not.toHaveBeenCalled();
  });
  it("deletes from settings with the page's original generation and keeps it across retries", async () => {
    mutation.mockRejectedValueOnce(new ContextDBError("unknown", 0, "connection_unknown", null));
    render(<BankPage />);
    await waitFor(() => expect(screen.getByText("deleteBank")).toHaveProperty("disabled", false));
    fireEvent.click(screen.getByText("deleteBank"));
    const dialog = screen.getByRole("alertdialog");
    // Name now refers to B: confirmation must never replace the page A snapshot.
    api.mockResolvedValue({
      workspace_id: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      bank_id: "jiamu",
      etag: '"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:1"',
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "deleteBank" }));
    await waitFor(() => expect(mutation).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "deleteBank" })).toHaveProperty(
        "disabled",
        false
      )
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "deleteBank" }));
    await waitFor(() => expect(mutation).toHaveBeenCalledTimes(2));
    expect(mutation.mock.calls.map((args) => args[5])).toEqual([etag, etag]);
    expect(mutation.mock.calls[0][2]).toBe(mutation.mock.calls[1][2]);
    expect(api).toHaveBeenCalledTimes(1);
    expect(mutation.mock.calls[0][0]).toBe("/workspaces/jiamu");
  });
});
