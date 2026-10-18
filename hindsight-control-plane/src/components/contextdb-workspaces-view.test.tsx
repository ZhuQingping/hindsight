// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en.json";
import { BanksOverview } from "./banks-overview";
import {
  contextDBRequest,
  workspaceMutation,
  waitForWorkspaceOperation,
  saveWorkspaceIntent,
} from "@/lib/contextdb-api";
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/contextdb-mode", () => ({ useContextDBMode: () => true }));
const loadBanks = vi.hoisted(() => vi.fn());
const setCurrentBank = vi.hoisted(() => vi.fn());
vi.mock("@/lib/bank-context", () => ({
  useBank: () => ({ currentBank: null, setCurrentBank, loadBanks }),
}));
vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  workspaceMutation: vi.fn(),
  contextDBRequest: vi.fn(),
  waitForWorkspaceOperation: vi.fn(),
}));
const api = vi.mocked(contextDBRequest);
const workspace = {
  workspace_id: "11111111111111111111111111111111",
  name: "MySQL",
  bank_id: "mysql",
  etag: '"11111111111111111111111111111111:1"',
  description: "Demo",
  state: "active",
  latest_operation_id: null,
};
const mount = () =>
  render(
    <NextIntlClientProvider locale="en" messages={en}>
      <BanksOverview />
    </NextIntlClientProvider>
  );
beforeEach(() => {
  sessionStorage.clear();
  api.mockResolvedValue({ items: [workspace], total: 1, limit: 20, offset: 0 });
  vi.mocked(workspaceMutation).mockResolvedValue({
    operation_id: "operation",
    workspace_id: workspace.workspace_id,
    state: "succeeded",
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
  sessionStorage.clear();
});
describe("workspace management", () => {
  it("polls pending directory state using GET and stops when it becomes active", async () => {
    api
      .mockResolvedValueOnce({
        items: [{ ...workspace, state: "creating" }],
        total: 1,
        limit: 20,
        offset: 0,
      })
      .mockResolvedValue({ items: [workspace], total: 1, limit: 20, offset: 0 });
    vi.useFakeTimers();
    await act(async () => {
      mount();
    });
    expect(screen.getByText("MySQL")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(api).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(api).toHaveBeenCalledTimes(2);
    expect(loadBanks).toHaveBeenCalled();
    expect(workspaceMutation).not.toHaveBeenCalled();
  });
  it("creates a workspace inside the UI with raw name and description", async () => {
    api.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    mount();
    await screen.findByText("Create a workspace first, or choose all workspaces.");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), {
      target: { value: "  MySQL  " },
    });
    fireEvent.change(within(dialog).getByLabelText("Description"), {
      target: { value: "Demo description" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    await waitFor(() =>
      expect(workspaceMutation).toHaveBeenCalledWith(
        "/workspaces",
        "POST",
        expect.any(String),
        { name: "  MySQL  ", description: "Demo description" },
        expect.any(AbortSignal)
      )
    );
  });
  it("deletes using workspace management after explicit confirmation", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Delete"));
    expect(workspaceMutation).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(workspaceMutation).toHaveBeenCalledWith(
        `/workspaces/${workspace.bank_id}`,
        "DELETE",
        expect.any(String),
        undefined,
        expect.any(AbortSignal),
        workspace.etag
      )
    );
  });
  it("opens native workspace content using the readable bank ID", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Open workspace"));
    expect(setCurrentBank).toHaveBeenCalledWith("mysql");
  });
  it("explains identifier rules and rejects unsupported names before submission", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), {
      target: { value: "嘉木" },
    });
    expect(within(dialog).getByRole("button", { name: "Create workspace" })).toHaveProperty(
      "disabled",
      true
    );
    expect(within(dialog).getByText(/converted to lowercase/)).toBeTruthy();
    expect(workspaceMutation).not.toHaveBeenCalled();
  });
  it("lists creating and failed states but allows content only for active spaces", async () => {
    api.mockResolvedValue({
      items: [
        { ...workspace, state: "creating" },
        {
          ...workspace,
          workspace_id: "22222222222222222222222222222222",
          name: "Failed space",
          state: "failed",
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    });
    mount();
    await screen.findByText("MySQL");
    expect(screen.getByText("Failed space")).toBeTruthy();
    expect(
      screen
        .getAllByText("Open workspace")
        .every((button) => (button as HTMLButtonElement).disabled)
    ).toBe(true);
  });
  it("restores known operation reads and never replays a write on mount", async () => {
    saveWorkspaceIntent({
      method: "POST",
      path: "/workspaces",
      raw_body: '{"name":"  ＰＧ  "}',
      idempotency_key: "original",
      operation_id: "33333333333333333333333333333333",
    });
    api.mockImplementation(async (path) =>
      path.startsWith("/operations/")
        ? { state: "running" }
        : { items: [workspace], total: 1, limit: 20, offset: 0 }
    );
    mount();
    await screen.findByText("33333333333333333333333333333333");
    await waitFor(() =>
      expect(
        api.mock.calls.some(([path]) => path === "/operations/33333333333333333333333333333333")
      ).toBe(true)
    );
    expect(workspaceMutation).not.toHaveBeenCalled();
    expect(waitForWorkspaceOperation).not.toHaveBeenCalled();
  });
  it("retains an unknown original request until explicit same-id confirmation", async () => {
    saveWorkspaceIntent({
      method: "POST",
      path: "/workspaces",
      raw_body: '{"name":"  ＰＧ  "}',
      idempotency_key: "original",
    });
    mount();
    await screen.findByText("original");
    expect(workspaceMutation).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Continue confirmation / retry"));
    await waitFor(() =>
      expect(workspaceMutation).toHaveBeenCalledWith(
        "/workspaces",
        "POST",
        "original",
        { name: "  ＰＧ  " },
        expect.any(AbortSignal),
        undefined
      )
    );
  });
  it("reads a failed operation on demand without resubmitting or permanent progress actions", async () => {
    api.mockResolvedValue({
      items: [{ ...workspace, state: "failed", latest_operation_id: "op-server" }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.mocked(waitForWorkspaceOperation).mockResolvedValue({
      operation_id: "op-server",
      workspace_id: workspace.workspace_id,
      state: "succeeded",
    });
    mount();
    await screen.findByText("MySQL");
    expect(screen.queryByText("Check progress")).toBeNull();
    fireEvent.click(screen.getByText("View failure"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith("/operations/op-server", { signal: expect.any(AbortSignal) })
    );
    expect(workspaceMutation).not.toHaveBeenCalled();
  });
});
