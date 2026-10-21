// @vitest-environment jsdom
import { openMenuAction } from "./support/menu";
import React from "react";
import { selectOption } from "./support/select";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "@/messages/en.json";
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { ContextDBUserKeysPanel } from "@/components/contextdb/user-keys-panel";
import { ContextDBKeyEditorDialog } from "@/components/contextdb/key-editor-dialog";
import {
  ContextDBError,
  contextDBRequest,
  createContextDBKey,
  type ContextDBKeyMetadata,
  type ContextDBUser,
} from "@/lib/contextdb-api";

vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  contextDBRequest: vi.fn(),
  createContextDBKey: vi.fn(),
}));
const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");
const api = vi.mocked(contextDBRequest);
const create = vi.mocked(createContextDBKey);
const user: ContextDBUser = {
  user_id: "user-a",
  name: "Alice",
  status: "active",
  version: 1,
  created_at: "2026-10-20",
};
const key: ContextDBKeyMetadata = {
  key_id: "key-a",
  user_id: user.user_id,
  name: "Agent",
  display_key: "ctx_live_***tail-a",
  authorization: { mode: "all", permission: "read" },
  version: 2,
  created_at: "2026-10-20",
  last_used_at: null,
};
const page = <T,>(items: T[], total = items.length) => ({ items, total, limit: 20, offset: 0 });
const frame = (child: React.ReactNode) => (
  <NextIntlClientProvider locale="en" messages={withContextdbMessages(en, "en")}>
    {child}
  </NextIntlClientProvider>
);
const panel = (member = user) =>
  frame(<ContextDBUserKeysPanel key={member.user_id} user={member} />);
async function issue() {
  await screen.findByText("Agent");
  fireEvent.click(screen.getByRole("button", { name: "Create API key" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "App" } });
  selectOption(within(dialog).getByLabelText("Workspaces"), "all");
  fireEvent.click(within(dialog).getByRole("button", { name: /^(Save|Save changes|Create)$/ }));
  return dialog;
}
beforeEach(() => {
  api.mockReset();
  create.mockReset();
  api.mockImplementation(async (path) => (path.startsWith("/workspaces") ? page([]) : page([key])));
  create.mockResolvedValue({ ...key, secret: "one-time-secret" });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (originalClipboard) Object.defineProperty(navigator, "clipboard", originalClipboard);
  else Reflect.deleteProperty(navigator, "clipboard");
});

describe("member-local key state", () => {
  it("distinguishes an initial Key GET failure from an empty list and retries only GET", async () => {
    api.mockRejectedValueOnce(new Error("Key directory unavailable"));
    render(panel());
    await screen.findByText("Key directory unavailable");
    expect(screen.queryByText("No API keys.")).toBeNull();
    expect(screen.queryByText("0–0 / 0")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Agent");
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("shows an empty Key list only after a successful GET", async () => {
    api.mockResolvedValueOnce(page([]));
    render(panel());
    await screen.findByText("No API keys.");
    expect(screen.queryByText("0–0 / 0")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("hides stale Key records after a failed refresh and retries without writing", async () => {
    render(panel());
    await screen.findByText("Agent");
    api.mockRejectedValueOnce(new Error("Key refresh unavailable"));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Key refresh unavailable");
    expect(screen.getByText(/Previously loaded data is not current/)).toBeTruthy();
    expect(screen.queryByText("Agent")).toBeNull();
    expect(screen.queryByText("No API keys.")).toBeNull();
    expect(screen.queryByText("1–1 / 1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Agent");
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("clears stale picker choices after a failed search and retries the same GET query", async () => {
    const workspace = {
      workspace_id: "original",
      bank_id: "original",
      name: "Original choice",
      state: "active",
    };
    api.mockResolvedValueOnce(page([workspace]));
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={null}
          onClose={vi.fn()}
          onSaved={vi.fn()}
          onCheckResult={vi.fn()}
        />
      )
    );
    await screen.findByText("Original choice");
    api.mockRejectedValueOnce(new Error("Picker search unavailable"));
    fireEvent.change(screen.getByLabelText("Search workspaces"), { target: { value: "new" } });
    await screen.findByText("Picker search unavailable");
    expect(screen.queryByText("Original choice")).toBeNull();
    expect(screen.queryByText("No matches. Clear the search to see all results.")).toBeNull();
    expect(screen.queryByText("No workspaces yet. Create a workspace to get started.")).toBeNull();
    api.mockResolvedValueOnce(page([{ ...workspace, name: "New choice" }]));
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("New choice");
    expect(api.mock.calls.at(-1)?.[0]).toBe("/workspaces?limit=50&offset=0&q=new");
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
    expect(create).not.toHaveBeenCalled();
  });

  it("opens a hundred existing grants without per-workspace identity probes", async () => {
    const grants = Array.from({ length: 100 }, (_, index) => ({
      workspace_id: `original-${index}`,
      bank_id: `space_${index}`,
      workspace_name: `Workspace ${index}`,
      permission: "read" as const,
    }));
    const saved = vi.fn();
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={{ ...key, authorization: { mode: "selected", workspaces: grants } }}
          onClose={vi.fn()}
          onSaved={saved}
          onCheckResult={vi.fn()}
        />
      )
    );
    await screen.findByLabelText("Workspace 99 Permission");
    await waitFor(() =>
      expect(api.mock.calls.some(([path]) => path.startsWith("/workspaces?"))).toBe(true)
    );
    expect(api.mock.calls.filter(([path]) => path.startsWith("/workspaces/"))).toHaveLength(0);
    selectOption(screen.getByLabelText("Workspace 99 Permission"), "read_write");
    fireEvent.click(screen.getByRole("button", { name: /^(Save|Save changes|Create)$/ }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    const write = api.mock.calls.find(([, options]) => options?.method === "PATCH")!;
    expect(write[1]?.version).toBe(key.version);
    expect(write[1]?.body).toMatchObject({
      authorization: {
        mode: "selected",
        workspaces: [
          ...grants.slice(0, 99).map(({ workspace_name: _label, ...grant }) => grant),
          { workspace_id: "original-99", bank_id: "space_99", permission: "read_write" },
        ],
      },
    });
  });

  it.each(["visibilitychange", "pagehide"])(
    "allows a fresh issuance after returning from %s without restoring an older secret",
    async (eventName) => {
      let hidden = false;
      vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
      render(panel());
      await screen.findByText("Agent");
      hidden = true;
      act(() => (eventName === "pagehide" ? window : document).dispatchEvent(new Event(eventName)));
      hidden = false;
      act(() => document.dispatchEvent(new Event("visibilitychange")));
      await issue();
      expect((await screen.findByTestId("issued-secret")).textContent).toBe("one-time-secret");
    }
  );

  it("locks an unknown issuance, checks metadata without replay, and requires an explicit new attempt", async () => {
    create.mockRejectedValueOnce(
      new ContextDBError("Result unknown", 503, "service_unavailable", null)
    );
    render(panel());
    const dialog = await issue();
    await within(dialog).findByText("Result unknown");
    expect(
      within(dialog).queryByRole("button", { name: /^(Save|Save changes|Create)$/ })
    ).toBeNull();
    expect(within(dialog).getByText(/secret cannot be retrieved/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Check current API keys" }));
    await screen.findByText("Key ID: key-a");
    expect(screen.queryByTestId("issued-secret")).toBeNull();
    expect(screen.getByRole("button", { name: "Create API key" })).toHaveProperty("disabled", true);
    expect(create).toHaveBeenCalledTimes(1);
    expect(api.mock.calls.filter(([, options]) => options?.method)).toHaveLength(0);
    fireEvent.click(
      screen.getByRole("button", { name: "I checked the keys — start a new issuance" })
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(create).toHaveBeenCalledTimes(1);
  });
  it("keeps explicit validation failures editable", async () => {
    create.mockRejectedValueOnce(new ContextDBError("Fix name", 400, "invalid", null));
    render(panel());
    const dialog = await issue();
    await within(dialog).findByText("Fix name");
    expect(
      within(dialog).getByRole("button", { name: /^(Save|Save changes|Create)$/ })
    ).toHaveProperty("disabled", false);
    expect(within(dialog).getByLabelText("Name")).toHaveProperty("disabled", false);
    expect(create).toHaveBeenCalledTimes(1);
  });
  it("requires a read-only current-record check after a version conflict", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "PATCH")
        throw new ContextDBError("Refresh first", 412, "version_conflict", null);
      return original(path, options);
    });
    render(panel());
    await screen.findByText("Agent");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Changed" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Refresh first");
    expect(within(dialog).queryByText(/^(Save|Save changes|Create)$/)).toBeNull();
    fireEvent.click(within(dialog).getByText("Check current API keys"));
    await screen.findByText("Agent");
    expect(api.mock.calls.filter(([, options]) => options?.method === "PATCH")).toHaveLength(1);
  });
  it("does not automatically repeat an uncertain revocation", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "DELETE")
        throw new ContextDBError("Result unknown", 503, "service_unavailable", null);
      return original(path, options);
    });
    render(panel());
    await screen.findByText("Agent");
    await openMenuAction(screen.getByRole("button", { name: /^More:/ }), "Revoke");
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByText("Revoke"));
    await within(dialog).findByText("Result unknown");
    expect(within(dialog).queryByRole("button", { name: "Revoke" })).toBeNull();
    fireEvent.click(within(dialog).getByText("Check current API keys"));
    await screen.findByText("Key ID: key-a");
    expect(api.mock.calls.filter(([, options]) => options?.method === "DELETE")).toHaveLength(1);
  });
  it("retains the revocation target ID and refreshes without scanning or replay", async () => {
    api.mockImplementation(async (path, options) => {
      if (options?.method === "DELETE")
        throw new ContextDBError("Result unknown", 503, "unknown", null);
      if (path.includes("limit=100&offset=0"))
        return page(
          Array.from({ length: 100 }, (_, index) => ({ ...key, key_id: `other-${index}` })),
          101
        );
      if (path.includes("limit=100&offset=100")) return page([key], 101);
      return path.startsWith("/workspaces") ? page([]) : page([key]);
    });
    render(panel());
    await screen.findByText("Agent");
    await openMenuAction(screen.getByRole("button", { name: /^More:/ }), "Revoke");
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByText("Revoke"));
    await within(dialog).findByText("Result unknown");
    fireEvent.click(within(dialog).getByText("Check current API keys"));
    await screen.findByText(/No write is replayed. Key ID: key-a/);
    expect(
      api.mock.calls.some(([path]) => path.includes("limit=100") || path.includes("offset=100"))
    ).toBe(false);
    expect(api.mock.calls.filter(([, options]) => options?.method === "DELETE")).toHaveLength(1);
  });
  it("discards an old member's delayed key response after switching the mounted identity", async () => {
    let resolve!: (value: unknown) => void;
    api.mockImplementation(async (path) =>
      path.includes("user-a")
        ? new Promise((done) => {
            resolve = done;
          })
        : page([{ ...key, key_id: "key-b", name: "Other agent" }])
    );
    const view = render(panel());
    view.rerender(panel({ ...user, user_id: "user-b", name: "Bob" }));
    await screen.findByText("Other agent");
    await act(async () => resolve(page([key])));
    expect(screen.queryByText("Agent")).toBeNull();
    expect(screen.getByText("Other agent")).toBeTruthy();
  });
  it("drops an issuance response after its member panel unmounts", async () => {
    let resolve!: (value: { secret: string } & typeof key) => void;
    create.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    const view = render(panel());
    await issue();
    const signal = create.mock.calls[0][2]!;
    view.rerender(panel({ ...user, user_id: "user-b", name: "Bob" }));
    await act(async () => resolve({ ...key, secret: "late-secret" }));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByTestId("issued-secret")).toBeNull();
    expect(screen.queryByText("late-secret")).toBeNull();
  });
  it("allows a pending issuance to finish while the tab is hidden", async () => {
    let resolve!: (value: { secret: string } & typeof key) => void;
    create.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    render(panel());
    await issue();
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    await act(async () => resolve({ ...key, secret: "hidden-secret" }));
    expect(screen.getByTestId("issued-secret").textContent).toBe("hidden-secret");
    expect(create).toHaveBeenCalledOnce();
  });
  it("does not reintroduce a late issuance secret after pagehide", async () => {
    let resolve!: (value: { secret: string } & typeof key) => void;
    create.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    render(panel());
    await issue();
    act(() => window.dispatchEvent(new Event("pagehide")));
    await act(async () => resolve({ ...key, secret: "departed-secret" }));
    expect(screen.queryByTestId("issued-secret")).toBeNull();
    expect(screen.queryByText("departed-secret")).toBeNull();
    expect(screen.getByText(/Key key-a was created after you left this page/)).toBeTruthy();
  });
  it("keeps the one-time secret beyond60 seconds until explicitly closed", async () => {
    render(panel());
    await screen.findByText("Agent");
    fireEvent.click(screen.getByText("Create API key"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "App" } });
    selectOption(within(dialog).getByLabelText("Workspaces"), "all");
    vi.useFakeTimers();
    await act(async () =>
      fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/))
    );
    expect(screen.getByTestId("issued-secret").textContent).toBe("one-time-secret");
    act(() => vi.advanceTimersByTime(120000));
    expect(screen.getByTestId("issued-secret").textContent).toBe("one-time-secret");
    fireEvent.click(screen.getByText("I saved it — close"));
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("preserves the secret when switching to a hidden tab", async () => {
    render(panel());
    await issue();
    await screen.findByTestId("issued-secret");
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(screen.getByTestId("issued-secret").textContent).toBe("one-time-secret");
  });
  it("keeps original grants and permits name-only edits when the directory is unavailable", async () => {
    const saved = vi.fn();
    api.mockImplementation(async (path) => {
      if (path.startsWith("/workspaces?"))
        throw new ContextDBError("Lookup unavailable", 503, "unavailable", null);
      return key;
    });
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={{
            ...key,
            authorization: {
              mode: "selected",
              workspaces: [
                {
                  workspace_id: "original-uuid",
                  bank_id: "old",
                  workspace_name: "Old space",
                  permission: "read",
                },
              ],
            },
          }}
          onClose={vi.fn()}
          onSaved={saved}
          onCheckResult={vi.fn()}
        />
      )
    );
    await screen.findByText("Lookup unavailable");
    expect(screen.getByLabelText("Old space Permission")).toHaveProperty(
      "textContent",
      "Read only"
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByText(/^(Save|Save changes|Create)$/));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    const write = api.mock.calls.find(([, options]) => options?.method === "PATCH")!;
    expect(write[1]).toMatchObject({ version: key.version, body: { name: "Renamed" } });
    expect(api.mock.calls.some(([path]) => path.startsWith("/workspaces/"))).toBe(false);
  });

  it("ignores a failed picker request from an editor that has already closed", async () => {
    let reject!: (reason: Error) => void;
    let reads = 0;
    api.mockImplementation(async (path) => {
      if (path.startsWith("/workspaces")) {
        if (++reads === 1)
          return new Promise((_, fail) => {
            reject = fail;
          });
        return page([
          { workspace_id: "new-uuid", bank_id: "new", name: "Fresh workspace", state: "active" },
        ]);
      }
      return page([key]);
    });
    render(panel());
    await screen.findByText("Agent");
    fireEvent.click(screen.getByText("Create API key"));
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Cancel"));
    fireEvent.click(screen.getByText("Create API key"));
    await screen.findByText("Fresh workspace");
    await act(async () => reject(new Error("Stale failure")));
    expect(screen.queryByText("Stale failure")).toBeNull();
    expect(screen.getByText("Fresh workspace")).toBeTruthy();
  });
});

describe("Key picker search and credential saving", () => {
  it("searches beyond the first50 workspaces without dropping selected read-only grants", async () => {
    const spaces = Array.from({ length: 60 }, (_, i) => ({
      workspace_id: `id-${i}`,
      bank_id: `bank_${i}`,
      name: `Workspace ${i}`,
      state: "active",
    }));
    api.mockImplementation(async (path) => {
      const params = new URL(path, "http://test").searchParams;
      const found = spaces.filter((s) => !params.get("q") || s.name.includes(params.get("q")!));
      const offset = Number(params.get("offset"));
      return { ...page(found.slice(offset, offset + 50), found.length), limit: 50 };
    });
    const saved = vi.fn();
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={null}
          onSaved={saved}
          onClose={vi.fn()}
          onCheckResult={vi.fn()}
        />
      )
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "App" } });
    await screen.findByLabelText("Workspace 0");
    fireEvent.click(screen.getByLabelText("Workspace 0"));
    selectOption(screen.getByLabelText("Workspace 0 Permission"), "read");
    fireEvent.change(screen.getByLabelText("Search workspaces"), {
      target: { value: "Workspace 59" },
    });
    await screen.findByLabelText("Workspace 59");
    expect(
      api.mock.calls.some(
        ([path]) => path.includes("q=Workspace%2059") && path.includes("offset=0")
      )
    ).toBe(true);
    fireEvent.click(screen.getByLabelText("Workspace 59"));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(saved).toHaveBeenCalledOnce());
    expect(create.mock.calls[0][1].authorization).toEqual({
      mode: "selected",
      workspaces: [
        { workspace_id: "id-0", bank_id: "bank_0", permission: "read" },
        { workspace_id: "id-59", bank_id: "bank_59", permission: "read_write" },
      ],
    });
  });
  it("ignores an older search and restarts pagination when search is cleared", async () => {
    let finishOld!: (value: unknown) => void;
    const space = (id: number) => ({
      workspace_id: `id-${id}`,
      bank_id: `bank_${id}`,
      name: `Workspace ${id}`,
      state: "active",
    });
    api.mockImplementation(async (path) => {
      const params = new URL(path, "http://test").searchParams;
      if (params.get("q") === "old")
        return new Promise((resolve) => {
          finishOld = resolve;
        });
      if (params.get("q") === "new") return { ...page([space(59)]), limit: 50 };
      return { ...page([space(Number(params.get("offset")) || 0)], 60), limit: 50 };
    });
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={null}
          onSaved={vi.fn()}
          onClose={vi.fn()}
          onCheckResult={vi.fn()}
        />
      )
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "App" } });
    await screen.findByLabelText("Workspace 0");
    fireEvent.click(screen.getByLabelText("Workspace 0"));
    selectOption(screen.getByLabelText("Workspace 0 Permission"), "read");
    fireEvent.click(screen.getByRole("button", { name: "Load more workspaces" }));
    await screen.findByLabelText("Workspace 1");
    const search = screen.getByLabelText("Search workspaces");
    fireEvent.change(search, { target: { value: "old" } });
    await waitFor(() => expect(finishOld).toBeTypeOf("function"));
    fireEvent.change(search, { target: { value: "new" } });
    await screen.findByLabelText("Workspace 59");
    await act(async () => finishOld(page([space(58)])));
    expect(screen.queryByLabelText("Workspace 58")).toBeNull();
    expect(screen.getByLabelText("Workspace 59")).toBeTruthy();
    fireEvent.change(search, { target: { value: "" } });
    await screen.findByRole("button", { name: "Load more workspaces" });
    expect(api.mock.calls.at(-1)?.[0]).toBe("/workspaces?limit=50&offset=0");
    expect(screen.getByLabelText("Workspace 0 Permission")).toBeTruthy();
    expect(screen.queryByLabelText("Workspace 59")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    expect(create.mock.calls[0][1].authorization).toEqual({
      mode: "selected",
      workspaces: [{ workspace_id: "id-0", bank_id: "bank_0", permission: "read" }],
    });
  });
  it("a failed picker read offers retry and does not claim there are no workspaces", async () => {
    api.mockRejectedValueOnce(new Error("Picker unavailable"));
    render(
      frame(
        <ContextDBKeyEditorDialog
          userId={user.user_id}
          userName={user.name}
          editingKey={null}
          onSaved={vi.fn()}
          onClose={vi.fn()}
          onCheckResult={vi.fn()}
        />
      )
    );
    await screen.findByText("Picker unavailable");
    expect(screen.queryByText("No workspaces yet. Create a workspace to get started.")).toBeNull();
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText("No workspaces yet. Create a workspace to get started.");
  });
  it("reports copy success, keeps the Secret visible, and clears it only on confirmation", async () => {
    const copy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: copy },
      configurable: true,
    });
    render(panel());
    await issue();
    await screen.findByTestId("issued-secret");
    fireEvent.click(screen.getByText("Copy API key"));
    await screen.findByText("Copied");
    expect(copy).toHaveBeenCalledWith("one-time-secret");
    expect(screen.getByTestId("issued-secret")).toBeTruthy();
    fireEvent.click(screen.getByText("I saved it — close"));
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("a failed copy keeps the Secret available for retry", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("Denied")) },
      configurable: true,
    });
    render(panel());
    await issue();
    await screen.findByTestId("issued-secret");
    fireEvent.click(screen.getByText("Copy API key"));
    await screen.findByText("Copy failed. Select and save the key manually.");
    expect(screen.getByTestId("issued-secret").textContent).toBe("one-time-secret");
  });
});

it.each([true, false])(
  "ignores a late clipboard result after a new Secret is displayed (success=%s)",
  async (success) => {
    let done!: () => void;
    let fail!: (reason: Error) => void;
    const pending = new Promise<void>((resolve, reject) => {
      done = resolve;
      fail = reject;
    });
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockReturnValue(pending) },
      configurable: true,
    });
    render(panel());
    await issue();
    await screen.findByTestId("issued-secret");
    fireEvent.click(screen.getByText("Copy API key"));
    fireEvent.click(screen.getByText("I saved it — close"));
    create.mockResolvedValueOnce({ ...key, secret: "new-secret" });
    await issue();
    await screen.findByText("new-secret");
    await act(async () => (success ? done() : fail(new Error("Old copy failed"))));
    expect(screen.queryByText("Copied")).toBeNull();
    expect(screen.queryByText("Copy failed. Select and save the key manually.")).toBeNull();
    expect(screen.getByTestId("issued-secret").textContent).toBe("new-secret");
  }
);

it("reports an unavailable Clipboard API without closing the Secret", async () => {
  Object.defineProperty(navigator, "clipboard", { value: undefined, configurable: true });
  render(panel());
  await issue();
  await screen.findByTestId("issued-secret");
  fireEvent.click(screen.getByText("Copy API key"));
  await screen.findByText("Copy failed. Select and save the key manually.");
  expect(screen.getByTestId("issued-secret")).toBeTruthy();
});

describe("compact key directory", () => {
  it("keeps an empty panel free of redundant table headers and pagination", async () => {
    api.mockResolvedValue(page([]));
    render(panel());
    await screen.findByText("No API keys.");
    const region = screen.getByRole("region", { name: "Keys for Alice" });
    expect(within(region).queryByRole("table")).toBeNull();
    expect(within(region).queryByText("0–0 / 0")).toBeNull();
    expect(within(region).getByRole("button", { name: "Create API key" })).toBeTruthy();
  });
  it("shows one key without duplicate owner headings or a single-page footer", async () => {
    render(panel());
    await screen.findByText("Agent");
    const region = screen.getByRole("region", { name: "Keys for Alice" });
    expect(within(region).getByRole("list", { name: "API keys" })).toBeTruthy();
    expect(within(region).queryByText("Keys for Alice")).toBeNull();
    expect(within(region).queryByText("1–1 / 1")).toBeNull();
    expect(within(region).queryByRole("button", { name: "Revoke" })).toBeNull();
    expect(within(region).getByRole("button", { name: "Edit" })).toBeTruthy();
    await openMenuAction(within(region).getByRole("button", { name: /^More:/ }), "Revoke");
    expect(api.mock.calls.some(([, options]) => options?.method)).toBe(false);
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke" })).toBeTruthy();
  });
  it("keeps exact IDs and locale dates accessible with an explicit disclosure icon", async () => {
    render(panel());
    await screen.findByText("Agent");
    const summary = screen.getByText("Key details").closest("summary")!;
    expect(summary.querySelector("svg")?.getAttribute("aria-hidden")).toBe("true");
    expect(summary.className).toContain("list-none");
    expect(screen.getByText("Key ID: key-a").className).toContain("select-all");
    expect(screen.getByText(/Created:/)).toBeTruthy();
    expect(screen.getByText("Last used: —")).toBeTruthy();
  });
  it("keeps service pagination for more than one page", async () => {
    api.mockImplementation(async (path) =>
      path.includes("offset=20")
        ? page([{ ...key, key_id: "last", name: "Last key" }], 21)
        : page([key], 21)
    );
    render(panel());
    await screen.findByText("Agent");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Last key");
    expect(api.mock.calls.some(([path]) => path.includes("limit=20&offset=20"))).toBe(true);
    expect(screen.getByRole("button", { name: "Previous" })).toHaveProperty("disabled", false);
  });
});

it("keeps mixed workspace permissions and both disclosure icons explicit", async () => {
  api.mockResolvedValue(
    page([
      {
        ...key,
        authorization: {
          mode: "selected",
          workspaces: [
            { workspace_id: "a", bank_id: "a", workspace_name: "Workspace A", permission: "read" },
            {
              workspace_id: "b",
              bank_id: "b",
              workspace_name: "Workspace B",
              permission: "read_write",
            },
          ],
        },
      },
    ])
  );
  render(panel());
  await screen.findByText("Agent");
  const scopes = screen.getByText("2 workspaces").closest("summary")!;
  const details = screen.getByText("Key details").closest("summary")!;
  for (const summary of [scopes, details]) {
    expect(summary.className).toContain("list-none");
    expect(summary.querySelector("svg")?.getAttribute("class")).toContain("h-4 w-4");
    expect(summary.querySelector("svg")?.getAttribute("class")).toContain("group-open:rotate-90");
  }
  expect(screen.getByText("Workspace A · Read only")).toBeTruthy();
  expect(screen.getByText("Workspace B · Read and write")).toBeTruthy();
});
