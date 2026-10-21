// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ContextDBCreateWorkspaceDialog } from "@/components/contextdb/create-workspace-dialog";
import { BankSelector } from "@/components/bank-selector";
import BankPage from "@/app/[locale]/banks/[bankId]/page";
import { contextDBRequest, workspaceMutation } from "@/lib/contextdb-api";
const state = vi.hoisted(() => ({
  contextDB: true,
  pathname: "/banks/jiamu",
  push: vi.fn(),
  setCurrentBank: vi.fn(),
  loadBanks: vi.fn().mockResolvedValue(undefined),
  bankId: "jiamu" as string | null,
}));
vi.mock("next/navigation", () => ({
  usePathname: () => state.pathname,
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
  state.pathname = "/banks/jiamu";
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
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

it("hands focus from the selector popover to the workspace creation dialog", async () => {
  // cmdk observes its list height; jsdom has no layout observer.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  render(<BankSelector />);
  fireEvent.click(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByRole("button", { name: /^create$/ }));
  const dialog = await screen.findByRole("dialog");
  await waitFor(() =>
    expect(document.activeElement).toBe(within(dialog).getByLabelText("workspaceName"))
  );
  fireEvent.click(within(dialog).getByRole("button", { name: /^cancel$/ }));
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("combobox")));
});

it.each(["/users", "/users/", "/zh-CN/users", "/console/users", "/console/zh-CN/users"])(
  "uses management context on %s and preserves the last workspace",
  (pathname) => {
    vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/console");
    state.pathname = pathname;
    const view = render(<BankSelector />);
    expect(screen.getByRole("button", { name: "title" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByText("addDocumentButton")).toBeNull();
    expect(state.setCurrentBank).not.toHaveBeenCalled();
    state.pathname = "/console/banks/jiamu";
    view.rerender(<BankSelector />);
    expect(screen.getByText("addDocumentButton")).toBeTruthy();
  }
);

it.each([
  "/banks/users",
  "/zh-CN/banks/users",
  "/console/banks/users",
  "/console/zh-CN/banks/users",
  "/other/users",
])("keeps content actions outside the complete management route: %s", (pathname) => {
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/console");
  state.bankId = "users";
  state.pathname = pathname;
  render(<BankSelector />);
  expect(screen.getByText("addDocumentButton")).toBeTruthy();
  expect(screen.getByRole("button", { name: "title" }).getAttribute("aria-current")).toBeNull();
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

it("does not navigate when a workspace creation succeeds after the selector unmounts", async () => {
  let finish!: (value: Awaited<ReturnType<typeof workspaceMutation<"POST">>>) => void;
  mutation.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  const view = render(<BankSelector />);
  act(() => window.dispatchEvent(new Event("hindsight:create-bank")));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("workspaceName"), { target: { value: "mysql" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "createWorkspace" }));
  const signal = mutation.mock.calls[0][3]!;
  view.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () =>
    finish({
      workspace_id: "a".repeat(32),
      bank_id: "mysql",
      name: "mysql",
      description: "",
      state: "active",
      version: 1,
      created_at: "2026-10-21",
      etag,
    })
  );
  expect(state.setCurrentBank).not.toHaveBeenCalled();
  expect(state.push).not.toHaveBeenCalled();
});

it("invalidates a closed create attempt without losing a newer request's cancellation", async () => {
  const finish: ((value: Awaited<ReturnType<typeof workspaceMutation<"POST">>>) => void)[] = [];
  mutation.mockImplementation(() => new Promise((resolve) => finish.push(resolve)));
  const onCreated = vi.fn();
  const onOpenChange = vi.fn();
  const ui = (open: boolean) => (
    <ContextDBCreateWorkspaceDialog
      open={open}
      onOpenChange={onOpenChange}
      onCreated={onCreated}
      onCheckResult={vi.fn()}
    />
  );
  const view = render(ui(true));
  fireEvent.change(screen.getByLabelText("workspaceName"), { target: { value: "first" } });
  fireEvent.click(screen.getByRole("button", { name: "createWorkspace" }));
  const first = mutation.mock.calls[0][3]!;
  view.rerender(ui(false));
  expect(first.aborted).toBe(true);
  view.rerender(ui(true));
  fireEvent.change(screen.getByLabelText("workspaceName"), { target: { value: "second" } });
  fireEvent.click(screen.getByRole("button", { name: "createWorkspace" }));
  expect(mutation).toHaveBeenCalledTimes(2);
  const second = mutation.mock.calls[1][3]!;
  await act(async () =>
    finish[0]({
      workspace_id: "a".repeat(32),
      bank_id: "first",
      name: "first",
      description: "",
      state: "active",
      version: 1,
      created_at: "2026-10-21",
      etag,
    })
  );
  expect(onCreated).not.toHaveBeenCalled();
  expect(onOpenChange).not.toHaveBeenCalled();
  view.unmount();
  expect(second.aborted).toBe(true);
});
