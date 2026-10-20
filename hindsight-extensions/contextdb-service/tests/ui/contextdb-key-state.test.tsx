// @vitest-environment jsdom
import React from "react";
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
  fireEvent.change(within(dialog).getByLabelText("Workspaces"), { target: { value: "all" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
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
});

describe("member-local key state", () => {
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
    fireEvent.change(screen.getByLabelText("Workspace 99 Permission"), {
      target: { value: "read_write" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
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
    expect(within(dialog).queryByRole("button", { name: "Save" })).toBeNull();
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
    expect(within(dialog).getByRole("button", { name: "Save" })).toHaveProperty("disabled", false);
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
    fireEvent.click(within(dialog).getByText("Save"));
    await within(dialog).findByText("Refresh first");
    expect(within(dialog).queryByText("Save")).toBeNull();
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
    fireEvent.click(screen.getByText("Revoke"));
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
    fireEvent.click(screen.getByText("Revoke"));
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
  it("does not reveal a delayed issuance secret when its tab has become hidden", async () => {
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
    expect(screen.queryByTestId("issued-secret")).toBeNull();
    expect(screen.queryByText("hidden-secret")).toBeNull();
    expect(screen.getByText(/Key key-a was created after this tab/)).toBeTruthy();
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
    expect(screen.getByText(/Key key-a was created after this tab/)).toBeTruthy();
  });
  it("clears the one-time secret at the 60-second deadline", async () => {
    render(panel());
    await screen.findByText("Agent");
    fireEvent.click(screen.getByText("Create API key"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "App" } });
    fireEvent.change(within(dialog).getByLabelText("Workspaces"), { target: { value: "all" } });
    vi.useFakeTimers();
    await act(async () => fireEvent.click(within(dialog).getByText("Save")));
    expect(screen.getByTestId("issued-secret").textContent).toBe("one-time-secret");
    act(() => vi.advanceTimersByTime(60000));
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("clears the secret when the document becomes hidden", async () => {
    render(panel());
    await issue();
    await screen.findByTestId("issued-secret");
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(screen.queryByTestId("issued-secret")).toBeNull();
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
    expect(screen.getByLabelText("Old space Permission")).toHaveProperty("value", "read");
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByText("Save"));
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
