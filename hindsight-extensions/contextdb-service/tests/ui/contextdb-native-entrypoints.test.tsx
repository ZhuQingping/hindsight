// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { BankSelector } from "@/components/bank-selector";
import BankPage from "@/app/[locale]/banks/[bankId]/page";
import { contextDBRequest, workspaceMutation } from "@/lib/contextdb-api";
const state = vi.hoisted(() => ({
  contextDB: true,
  push: vi.fn(),
  setCurrentBank: vi.fn(),
  loadBanks: vi.fn().mockResolvedValue(undefined),
  bankId: "jiamu" as string | null,
}));
vi.mock("@/i18n/navigation", () => ({
  Link: ({ children }: React.PropsWithChildren) => <span>{children}</span>,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/banks/jiamu",
  useRouter: () => ({ push: state.push }),
  useSearchParams: () => new URLSearchParams("view=profile"),
  useParams: () => ({ bankId: state.bankId }),
}));
vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { rich: (key: string) => key }),
}));
vi.mock("@/lib/contextdb-mode", () => ({ useContextDBMode: () => state.contextDB }));
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
  client: {
    createBank: vi.fn().mockResolvedValue(undefined),
    deleteBank: vi.fn().mockResolvedValue(undefined),
    getVersion: vi.fn().mockResolvedValue({ features: { file_upload_api: false } }),
  },
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
  state.contextDB = true;
  api.mockResolvedValue({
    workspace_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    bank_id: "jiamu",
    etag,
    state: "active",
  });
  mutation.mockResolvedValue({
    workspace_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    bank_id: "mysql",
    name: "mysql",
    description: "Demo description",
    state: "active",
    version: 1,
    created_at: "2026-10-19T00:00:00Z",
    etag,
  });
  sessionStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
describe("ContextDB native UI entry points", () => {
  it("centralizes ContextDB deletion in workspace management without an identity probe", async () => {
    render(<BankPage />);
    fireEvent.click(await screen.findByRole("button", { name: "workspaceDirectory" }));
    expect(state.push).toHaveBeenCalledWith("/");
    expect(screen.queryByRole("button", { name: "deleteBank" })).toBeNull();
    expect(api).not.toHaveBeenCalled();
    expect(mutation).not.toHaveBeenCalled();
    const { client } = await import("@/lib/api");
    expect(client.deleteBank).not.toHaveBeenCalled();
  });

  it("creates from the native selector and navigates to canonical bank_id rather than operation UUID", async () => {
    render(<BankSelector />);
    act(() => window.dispatchEvent(new Event("hindsight:create-bank")));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("workspaceName"), {
      target: { value: "MySQL" },
    });
    fireEvent.change(within(dialog).getByLabelText("workspaceDescription"), {
      target: { value: "Demo description" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "createWorkspace" }));
    await waitFor(() => expect(state.setCurrentBank).toHaveBeenCalledWith("mysql"));
    expect(state.push).toHaveBeenCalledWith("/banks/mysql?view=data");
    expect(mutation).toHaveBeenCalledWith(
      "/workspaces",
      "POST",
      { name: "MySQL", description: "Demo description" },
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
    expect(within(dialog).getByRole("button", { name: "createWorkspace" })).toHaveProperty(
      "disabled",
      true
    );
    expect(mutation).not.toHaveBeenCalled();
  });
  it("preserves native Bank deletion when ContextDB mode is disabled", async () => {
    state.contextDB = false;
    const { client } = await import("@/lib/api");
    render(<BankPage />);
    fireEvent.click(screen.getByRole("button", { name: "deleteBank" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "deleteBank" }));
    await waitFor(() => expect(client.deleteBank).toHaveBeenCalledWith("jiamu"));
    expect(api).not.toHaveBeenCalled();
    expect(mutation).not.toHaveBeenCalled();
    expect(state.push).toHaveBeenCalledWith("/");
  });

  it("keeps the native selector create flow without ContextDB fields or management calls", async () => {
    state.contextDB = false;
    const { client } = await import("@/lib/api");
    render(<BankSelector />);
    act(() => window.dispatchEvent(new Event("hindsight:create-bank")));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText("workspaceDescription")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("createBankIdPlaceholder"), {
      target: { value: "Native-bank" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "create" }));
    await waitFor(() => expect(client.createBank).toHaveBeenCalledWith("Native-bank"));
    expect(mutation).not.toHaveBeenCalled();
  });
});
