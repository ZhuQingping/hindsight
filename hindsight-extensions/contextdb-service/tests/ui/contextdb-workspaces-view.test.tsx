// @vitest-environment jsdom
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { openMenuAction } from "./support/menu";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import en from "@/messages/en.json";
import { BanksOverview } from "@/components/banks-overview";
import { ContextDBError, contextDBRequest, workspaceMutation } from "@/lib/contextdb-api";
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
}));
const api = vi.mocked(contextDBRequest);
const mutation = vi.mocked(workspaceMutation);
const workspace = {
  workspace_id: "11111111111111111111111111111111",
  name: "MySQL",
  bank_id: "mysql",
  etag: '"11111111111111111111111111111111:1"',
  description: "Demo",
  state: "active",
  version: 1,
  created_at: "2026-10-19T00:00:00Z",
};
const mount = () =>
  render(
    <NextIntlClientProvider locale="en" messages={withContextdbMessages(en, "en")}>
      <BanksOverview />
    </NextIntlClientProvider>
  );
beforeEach(() => {
  api.mockImplementation(async (path) =>
    path.startsWith("/workspaces/")
      ? workspace
      : { items: [workspace], total: 1, limit: 20, offset: 0 }
  );
  mutation.mockResolvedValue(workspace);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.resetAllMocks();
  vi.unstubAllGlobals();
});
describe("synchronous workspace management", () => {
  it("checks the normalized submitted name directly despite a searched, multi-page directory", async () => {
    mutation.mockRejectedValueOnce(
      new ContextDBError("Result unknown", 503, "service_unavailable", null)
    );
    api.mockImplementation(async (path) =>
      path === "/workspaces/pg"
        ? { ...workspace, bank_id: "pg", workspace_id: "b".repeat(32) }
        : { items: [workspace], total: 45, limit: 20, offset: 0 }
    );
    mount();
    await screen.findByText("MySQL");
    fireEvent.change(screen.getByRole("textbox", { name: "Search workspaces" }), {
      target: { value: "old_search" },
    });
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), {
      target: { value: " PG " },
    });
    fireEvent.submit(dialog.querySelector("form")!);
    fireEvent.click(await within(dialog).findByText("Check workspaces"));
    const check = screen.getByRole("dialog");
    await within(check).findByText(/Current workspace: pg/);
    expect(
      within(check).getByText(/does not prove that the original creation succeeded/)
    ).toBeTruthy();
    expect(api).toHaveBeenCalledWith(
      "/workspaces/pg",
      expect.objectContaining({ signal: expect.any(AbortSignal) })
    );
    expect(mutation).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("textbox", { name: "Search workspaces", hidden: true })).toHaveProperty(
      "value",
      "old_search"
    );
  });

  it("keeps an incomplete creation response in the result-check flow before success", async () => {
    const actual =
      await vi.importActual<typeof import("@/lib/contextdb-api")>("@/lib/contextdb-api");
    mutation.mockImplementation(actual.workspaceMutation);
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), { target: { value: "pg" } });
    fireEvent.submit(dialog.querySelector("form")!);
    await within(dialog).findByText(/Result unknown/);
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(within(dialog).getByRole("button", { name: "Check workspaces" })).toBeTruthy();
    expect(loadBanks).not.toHaveBeenCalled();
    fireEvent.submit(dialog.querySelector("form")!);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not poll or replay writes for an interrupted creating state", async () => {
    api.mockResolvedValue({
      items: [{ ...workspace, state: "creating" }],
      total: 1,
      limit: 20,
      offset: 0,
    });
    vi.useFakeTimers();
    await act(async () => {
      mount();
    });
    expect(screen.getByText("MySQL")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120000);
    });
    expect(api).toHaveBeenCalledTimes(1);
    expect(mutation).not.toHaveBeenCalled();
  });
  it("creates with optional description and displays processing only after submission", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("status")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), {
      target: { value: "  MySQL  " },
    });
    fireEvent.change(within(dialog).getByLabelText("Description"), {
      target: { value: "Demo description" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    await waitFor(() =>
      expect(mutation).toHaveBeenCalledWith(
        "/workspaces",
        "POST",
        { name: "  MySQL  ", description: "Demo description" },
        expect.any(AbortSignal)
      )
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(loadBanks).toHaveBeenCalledTimes(1);
  });
  it("waits for the synchronous response, prevents duplicate submissions, and supports form submission", async () => {
    let finish: (value: typeof workspace) => void = () => {};
    mutation.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    const name = within(dialog).getByLabelText("Workspace name");
    const description = within(dialog).getByLabelText("Description");
    expect(name).toHaveProperty("maxLength", 54);
    expect(description).toHaveProperty("maxLength", 512);
    fireEvent.change(name, { target: { value: "pg" } });
    fireEvent.submit(dialog.querySelector("form")!);
    expect(within(dialog).getByRole("status").textContent).toBe("Waiting for the server result.");
    expect(within(dialog).getByRole("button", { name: "Create workspace" })).toHaveProperty(
      "disabled",
      true
    );
    expect(loadBanks).not.toHaveBeenCalled();
    fireEvent.submit(dialog.querySelector("form")!);
    expect(mutation).toHaveBeenCalledTimes(1);
    await act(async () => finish(workspace));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(loadBanks).toHaveBeenCalledTimes(1);
  });
  it("clears failed form fields and error when cancelled and reopened", async () => {
    mutation.mockRejectedValueOnce(
      new ContextDBError("Name already exists", 409, "workspace_exists", null)
    );
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    let dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), { target: { value: "pg" } });
    fireEvent.change(within(dialog).getByLabelText("Description"), {
      target: { value: "A rejected description" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    await screen.findByText("Name already exists");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByText("Create workspace"));
    dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(within(dialog).getByLabelText("Workspace name")).toHaveProperty("value", "");
    expect(within(dialog).getByLabelText("Description")).toHaveProperty("value", "");
    expect(within(dialog).queryByRole("status")).toBeNull();
    expect(mutation).toHaveBeenCalledTimes(1);
  });
  it("sends a full512-character multiline description without trimming or truncation", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    const description = "第一行\n" + "界".repeat(508);
    expect(description.length).toBe(512);
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), { target: { value: "pg" } });
    fireEvent.change(within(dialog).getByLabelText("Description"), {
      target: { value: description },
    });
    fireEvent.submit(dialog.querySelector("form")!);
    await waitFor(() =>
      expect(mutation).toHaveBeenCalledWith(
        "/workspaces",
        "POST",
        { name: "pg", description },
        expect.any(AbortSignal)
      )
    );
  });
  it("deletes once after confirmation with the displayed resource identity", async () => {
    mount();
    await screen.findByText("MySQL");
    await openMenuAction(screen.getByRole("button", { name: "More" }), "Delete");
    expect(mutation).not.toHaveBeenCalled();
    expect(screen.getByText(/wait for existing requests and background work/)).toBeTruthy();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(mutation).toHaveBeenCalledWith(
        "/workspaces/mysql",
        "DELETE",
        undefined,
        expect.any(AbortSignal),
        workspace.etag
      )
    );
    expect(mutation).toHaveBeenCalledTimes(1);
  });
  it("offers a read-only result check after uncertain creation without automatic retries", async () => {
    mutation.mockRejectedValueOnce(
      new ContextDBError("Result unknown", 503, "service_unavailable", null)
    );
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Create workspace"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Workspace name"), { target: { value: "pg" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Create workspace" }));
    const check = await screen.findByRole("button", { name: "Check workspaces" });
    expect(within(dialog).queryByRole("button", { name: "Create workspace" })).toBeNull();
    fireEvent.click(check);
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    expect(mutation).toHaveBeenCalledTimes(1);
  });
  it("preserves full names, multiline descriptions, empty placeholders and independent state/action cells", async () => {
    const name = "a".repeat(54),
      description = "First line\n" + "长描述".repeat(165);
    api.mockResolvedValue({
      items: [
        { ...workspace, name, description },
        {
          ...workspace,
          workspace_id: "2".repeat(32),
          name: "failed_space",
          description: "",
          state: "failed",
        },
      ],
      total: 2,
      limit: 20,
      offset: 0,
    });
    mount();
    await screen.findByText(name);
    const region = screen.getByRole("region", { name: "Workspaces" });
    expect(region.tabIndex).toBe(0);
    const row = screen.getByRole("rowheader", { name }).closest("tr")!;
    expect(within(row).getAllByRole("cell")[0].textContent).toBe(description);
    expect(within(row).getByRole("button", { name: "Open workspace" })).toHaveProperty(
      "disabled",
      false
    );
    const failed = screen.getByRole("rowheader", { name: "failed_space" }).closest("tr")!;
    expect(within(failed).getByText("—")).toBeTruthy();
    expect(within(failed).getByRole("button", { name: "Open workspace" })).toHaveProperty(
      "disabled",
      true
    );
    expect(within(failed).getByRole("button", { name: "More" })).toHaveProperty("disabled", false);
  });
  it("opens native workspace content using readable bank_id", async () => {
    mount();
    await screen.findByText("MySQL");
    fireEvent.click(screen.getByText("Open workspace"));
    expect(setCurrentBank).toHaveBeenCalledWith("mysql");
  });
  it.each(["嘉木", "my-bank", "a".repeat(55)])(
    "rejects unsupported identifiers %s",
    async (name) => {
      mount();
      await screen.findByText("MySQL");
      fireEvent.click(screen.getByText("Create workspace"));
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Workspace name"), {
        target: { value: name },
      });
      expect(within(dialog).getByRole("button", { name: "Create workspace" })).toHaveProperty(
        "disabled",
        true
      );
      expect(mutation).not.toHaveBeenCalled();
    }
  );
});

describe("workspace directory GET outcomes", () => {
  it("hides old workspaces after a failed refresh and retries only GET", async () => {
    mount();
    await screen.findByRole("rowheader", { name: "MySQL" });
    api.mockRejectedValueOnce(new Error("Workspace refresh unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Workspace refresh unavailable");
    expect(screen.getByText(/Previously loaded data is not current/)).toBeTruthy();
    expect(screen.queryByRole("rowheader", { name: "MySQL" })).toBeNull();
    expect(screen.queryByText("No workspaces yet. Create a workspace to get started.")).toBeNull();
    expect(screen.queryByText("1–1 / 1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByRole("rowheader", { name: "MySQL" });
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    expect(mutation).not.toHaveBeenCalled();
  });

  it("does not suggest creating a workspace when the first read fails", async () => {
    api.mockRejectedValueOnce(new Error("Workspace directory unavailable"));
    mount();
    await screen.findByText("Workspace directory unavailable");
    expect(screen.queryByText("No workspaces yet. Create a workspace to get started.")).toBeNull();
    expect(screen.queryByText("0–0 / 0")).toBeNull();
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByRole("rowheader", { name: "MySQL" });
    expect(mutation).not.toHaveBeenCalled();
  });
  it("shows no matches after a successful empty search and hides single-page arrows", async () => {
    mount();
    await screen.findByRole("rowheader", { name: "MySQL" });
    expect(screen.queryByRole("button", { name: "Next" })).toBeNull();
    api.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    fireEvent.change(screen.getByLabelText("Search workspaces"), { target: { value: "missing" } });
    await screen.findByText("No matches. Clear the search to see all results.");
    expect(screen.queryByText("No workspaces yet. Create a workspace to get started.")).toBeNull();
  });
});

describe("management dialog focus and workspace identity", () => {
  it.each(["Cancel", "Close", "Escape"])("returns create focus after %s", async (close) => {
    mount();
    await screen.findByRole("rowheader", { name: "MySQL" });
    const trigger = screen.getByRole("button", { name: "Create workspace" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    if (close === "Escape") fireEvent.keyDown(dialog, { key: "Escape" });
    else fireEvent.click(within(dialog).getByRole("button", { name: close }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(mutation).not.toHaveBeenCalled();
  });
  it("returns cancelled delete to the row action and preserves name casing", async () => {
    mount();
    const name = await screen.findByRole("rowheader", { name: "MySQL" });
    expect(name.textContent).toBe("MySQL");
    expect(name.classList.contains("normal-case")).toBe(true);
    expect(name.getAttribute("scope")).toBe("row");
    const trigger = screen.getByRole("button", { name: "More" });
    await openMenuAction(trigger, "Delete");
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" })
    );
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(mutation).not.toHaveBeenCalled();
  });
});

it("uses a secondary menu for workspace deletion and performs no write on cancel", async () => {
  mount();
  await screen.findByText("MySQL");
  expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  const more = screen.getByRole("button", { name: "More" });
  await openMenuAction(more, "Delete");
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(document.activeElement).toBe(more));
  expect(mutation).not.toHaveBeenCalled();
});
