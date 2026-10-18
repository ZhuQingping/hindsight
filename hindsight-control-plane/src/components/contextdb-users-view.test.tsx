// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "@/messages/en.json";
import zh from "@/messages/zh-CN.json";
import { ContextDBUsersView } from "@/components/contextdb-users-view";
import {
  contextDBRequest,
  ContextDBError,
  type ContextDBUser,
  type ContextDBKey,
} from "@/lib/contextdb-api";
vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  contextDBRequest: vi.fn(),
}));
const member: ContextDBUser = {
  user_id: "member",
  name: "Alice",
  status: "active",
  version: 7,
  created_at: "2026-01-01",
};
const key: ContextDBKey = {
  key_id: "key",
  user_id: "member",
  name: "Agent",
  display_key: "ctx_live_***abC_-1",
  authorization: {
    mode: "selected",
    workspaces: [
      {
        workspace_id: "space-a",
        bank_id: "space-a",
        permission: "read",
        workspace_name: "Workspace A",
      },
    ],
  },
  version: 3,
  created_at: "2026-01-01",
  last_used_at: null,
};
const api = vi.mocked(contextDBRequest);
const page = <T,>(items: T[], total = items.length) => ({ items, total, limit: 20, offset: 0 });
const mount = (locale = "en") =>
  render(
    <NextIntlClientProvider locale={locale} messages={locale === "en" ? messages : zh}>
      <ContextDBUsersView />
    </NextIntlClientProvider>
  );
async function openKeys() {
  await screen.findByText("Alice");
  fireEvent.click(screen.getByRole("button", { name: "Manage API keys", expanded: false }));
  await screen.findByText("Agent");
}
async function openCreate() {
  await openKeys();
  fireEvent.click(screen.getByText("Create API key"));
  return screen.getByRole("dialog");
}
function selectAll(dialog: HTMLElement) {
  fireEvent.change(within(dialog).getByLabelText("Workspaces"), { target: { value: "all" } });
}
beforeEach(() => {
  api.mockReset();
  api.mockImplementation(async (path, options) => {
    if (path.startsWith("/workspaces/"))
      return {
        workspace_id: path.endsWith("space-a") ? "space-a" : "space-b",
        bank_id: path.endsWith("space-a") ? "space-a" : "space-b",
        name: path.endsWith("space-a") ? "Workspace A" : "Workspace B",
        state: "active",
      };
    if (path.startsWith("/workspaces"))
      return page([
        { workspace_id: "space-a", bank_id: "space-a", name: "Workspace A", state: "active" },
        { workspace_id: "space-b", bank_id: "space-b", name: "Workspace B", state: "active" },
        {
          workspace_id: "space-deleted",
          bank_id: "space-deleted",
          name: "Deleted workspace",
          state: "deleted",
        },
      ]);
    if (options?.method === "POST" && path.endsWith("/keys"))
      return { ...key, secret: "one-time-secret" };
    if (options?.method) return path.includes("/keys/") ? key : member;
    if (path.includes("/keys")) return page([key]);
    return page([member], 45);
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
describe("member and key management", () => {
  it("creates members with a name only and locates the exact new ID", async () => {
    const original = api.getMockImplementation()!;
    const bob = { ...member, user_id: "bob", name: "Bob" };
    api.mockImplementation(async (path, options) =>
      options?.method === "POST" && path === "/users"
        ? bob
        : path.includes("q=Bob")
          ? page([bob])
          : original(path, options)
    );
    mount("zh-CN");
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("新建成员"));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("checkbox")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("名称"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText("保存"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users",
        expect.objectContaining({ method: "POST", body: { name: "Bob" } })
      )
    );
    expect(await screen.findByText("Bob 的 Key")).toBeTruthy();
  });
  it("paginates members with server search and no member ACL", async () => {
    mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Next"));
    await waitFor(() =>
      expect(api.mock.calls.some(([path]) => path === "/users?limit=20&offset=20")).toBe(true)
    );
    fireEvent.change(screen.getByLabelText("Search members"), { target: { value: "Alice" } });
    await waitFor(() =>
      expect(api.mock.calls.some(([path]) => path.endsWith("offset=0&q=Alice"))).toBe(true)
    );
  });
  it("expands keys inside the member row and displays masked identifiers and times", async () => {
    mount();
    await openKeys();
    expect(screen.getByText("ctx_live_***abC_-1")).toBeTruthy();
    expect(screen.getByText("Agent").closest("table")?.closest("td")?.colSpan).toBe(5);
    expect(screen.getAllByText("Created").length).toBe(2);
    expect(screen.getByText("Last used")).toBeTruthy();
  });
  it("creates mixed permissions, defaults newly selected workspaces to read/write", async () => {
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Application" } });
    fireEvent.click(within(dialog).getByText("Workspace A"));
    fireEvent.click(within(dialog).getByText("Workspace B"));
    expect(await within(dialog).findByLabelText("Workspace A Permission")).toHaveProperty(
      "value",
      "read_write"
    );
    fireEvent.change(within(dialog).getByLabelText("Workspace A Permission"), {
      target: { value: "read" },
    });
    expect(within(dialog).queryByText("Deleted workspace")).toBeNull();
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys",
        expect.objectContaining({
          body: {
            name: "Application",
            authorization: {
              mode: "selected",
              workspaces: [
                { bank_id: "space-a", workspace_id: "space-a", permission: "read" },
                { bank_id: "space-b", workspace_id: "space-b", permission: "read_write" },
              ],
            },
          },
        })
      )
    );
    await screen.findByTestId("issued-secret");
    fireEvent.click(screen.getByText("I saved it — close"));
    expect(screen.queryByText("one-time-secret")).toBeNull();
  });
  it("requires selection and permits uniform current/future access", async () => {
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "All spaces" } });
    expect(within(dialog).getByText("Save")).toHaveProperty("disabled", true);
    selectAll(dialog);
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys",
        expect.objectContaining({
          body: { name: "All spaces", authorization: { mode: "all", permission: "read_write" } },
        })
      )
    );
  });
  it("renames without sending authorization or resetting an existing read-only grant", async () => {
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByLabelText("Workspace A Permission")).toHaveProperty(
      "value",
      "read"
    );
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys/key",
        expect.objectContaining({ method: "PATCH", version: 3, body: { name: "Renamed" } })
      )
    );
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("keeps post-page grants and resolves their workspace without treating them as missing", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) =>
      path === "/workspaces/space-z"
        ? { workspace_id: "space-z", bank_id: "space-z", name: "Workspace Z", state: "active" }
        : path.includes("/keys") && !options?.method
          ? page([
              {
                ...key,
                authorization: {
                  mode: "selected",
                  workspaces: [
                    {
                      workspace_id: "space-z",
                      bank_id: "space-z",
                      permission: "read",
                      workspace_name: "Workspace Z",
                    },
                  ],
                },
              },
            ])
          : original(path, options)
    );
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByLabelText("Workspace Z Permission")).toHaveProperty(
      "value",
      "read"
    );
    fireEvent.click(within(dialog).getByText("Workspace B"));
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys/key",
        expect.objectContaining({
          body: {
            authorization: {
              mode: "selected",
              workspaces: [
                { bank_id: "space-z", workspace_id: "space-z", permission: "read" },
                { bank_id: "space-b", workspace_id: "space-b", permission: "read_write" },
              ],
            },
          },
        })
      )
    );
  });
  it("allows name-only edits when a previously granted space is gone", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (path === "/workspaces/missing")
        throw new ContextDBError("missing", 404, "not_found", "trace");
      return path.includes("/keys") && !options?.method
        ? page([
            {
              ...key,
              authorization: {
                mode: "selected",
                workspaces: [
                  {
                    workspace_id: "missing",
                    bank_id: "missing",
                    permission: "read",
                    workspace_name: "missing",
                  },
                ],
              },
            },
          ])
        : original(path, options);
    });
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("missing (Unavailable)");
    fireEvent.change(within(dialog).getByLabelText("Name"), {
      target: { value: "Still editable" },
    });
    fireEvent.click(within(dialog).getByText("Save"));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys/key",
        expect.objectContaining({ body: { name: "Still editable" } })
      )
    );
  });
  it("does not silently grant a recreated workspace when editing an older key", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (path === "/workspaces/space-a")
        return {
          workspace_id: "successor-id",
          bank_id: "space-a",
          name: "Workspace A",
          state: "active",
        };
      if (path.startsWith("/workspaces?")) return page([]);
      return original(path, options);
    });
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("space-a (Unavailable)");
    // A name-only edit is allowed, but a permission edit must not retarget the successor.
    fireEvent.change(within(dialog).getByLabelText("space-a Permission"), {
      target: { value: "read_write" },
    });
    expect(within(dialog).getByText("Save")).toHaveProperty("disabled", true);
    expect(api.mock.calls.some(([, options]) => options?.method === "PATCH")).toBe(false);
  });
  it("sends the selected generation on create and keeps a generation conflict visible", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (path === "/users/member/keys" && options?.method === "POST")
        throw new ContextDBError(
          "Workspace changed. Refresh and select again.",
          409,
          "workspace_generation_changed",
          "trace"
        );
      return original(path, options);
    });
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Application" } });
    fireEvent.click(within(dialog).getByText("Workspace A"));
    fireEvent.click(within(dialog).getByText("Save"));
    await within(dialog).findByText("Workspace changed. Refresh and select again.");
    const writes = api.mock.calls.filter(([, options]) => options?.method === "POST");
    expect(writes).toHaveLength(1);
    expect(writes[0][1]?.body).toEqual({
      name: "Application",
      authorization: {
        mode: "selected",
        workspaces: [{ bank_id: "space-a", workspace_id: "space-a", permission: "read_write" }],
      },
    });
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("requires confirmation and refreshes only this key area after revocation", async () => {
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Revoke"));
    expect(api.mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) =>
      path.includes("/keys") && !options?.method ? page([]) : original(path, options)
    );
    const usersBefore = api.mock.calls.filter(([path]) => path.startsWith("/users?")).length;
    fireEvent.click(within(screen.getByRole("dialog")).getByText("Revoke"));
    await screen.findByText("No API keys.");
    expect(screen.queryByText("Agent")).toBeNull();
    expect(api.mock.calls.filter(([path]) => path.startsWith("/users?")).length).toBe(usersBefore);
  });
  it("shows disabled-member context without mislabelling unrevoked keys", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) =>
      path.startsWith("/users?")
        ? page([{ ...member, status: "disabled" }])
        : original(path, options)
    );
    mount();
    await openKeys();
    expect(screen.getByText(/This member is disabled/)).toBeTruthy();
    expect(screen.getByText("Create API key")).toHaveProperty("disabled", true);
    expect(screen.getByText("Edit")).toHaveProperty("disabled", false);
  });
  it("keeps conflicting edits open and never retries with a newer version", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "PATCH")
        throw new ContextDBError("Refresh before retrying", 412, "version_conflict", "trace");
      return original(path, options);
    });
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Rename" } });
    fireEvent.click(within(dialog).getByText("Save"));
    await within(dialog).findByText("Refresh before retrying");
    expect(api.mock.calls.filter(([, options]) => options?.method === "PATCH").length).toBe(1);
  });
  it("clears issued secrets when the page hides and never persists them", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "App" } });
    selectAll(dialog);
    fireEvent.click(within(dialog).getByText("Save"));
    await screen.findByTestId("issued-secret");
    window.dispatchEvent(new Event("pagehide"));
    await waitFor(() => expect(screen.queryByText("one-time-secret")).toBeNull());
    expect(storage).not.toHaveBeenCalled();
  });
  it("preserves read-only choices while switching ranges", async () => {
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    selectAll(dialog);
    expect(within(dialog).getByLabelText("Permission")).toHaveProperty("value", "read");
    fireEvent.change(within(dialog).getByLabelText("Workspaces"), {
      target: { value: "selected" },
    });
    expect(await within(dialog).findByLabelText("Workspace A Permission")).toHaveProperty(
      "value",
      "read"
    );
  });
  it("locates a newly created member beyond the first hundred same-name results", async () => {
    const original = api.getMockImplementation()!;
    const bob = { ...member, user_id: "new-bob", name: "Bob" };
    api.mockImplementation(async (path, options) => {
      if (path === "/users" && options?.method === "POST") return bob;
      if (path.startsWith("/users?") && path.includes("q=Bob")) {
        if (path.includes("limit=100&offset=0"))
          return page(
            Array.from({ length: 100 }, (_, index) => ({ ...bob, user_id: `old-${index}` })),
            101
          );
        return page([bob], 101);
      }
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Create member"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText("Save"));
    await screen.findByText("Keys for Bob");
    expect(api.mock.calls.some(([path]) => path === "/users?limit=20&offset=100&q=Bob")).toBe(true);
    expect(screen.getByRole("button", { name: "Manage API keys", expanded: true })).toBeTruthy();
  });
  it("disables a member through the More menu with its current version", async () => {
    mount();
    await screen.findByText("Alice");
    fireEvent.keyDown(screen.getByText("More"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Disable member" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member",
        expect.objectContaining({ method: "PATCH", version: 7, body: { status: "disabled" } })
      )
    );
  });
  it("confirms member deletion and closes its expanded key area", async () => {
    mount();
    await openKeys();
    fireEvent.keyDown(screen.getByText("More"), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(api.mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) =>
      path.startsWith("/users?") ? page([]) : original(path, options)
    );
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api).toHaveBeenCalledWith("/users/member", { method: "DELETE" }));
    await screen.findByText("No users yet.");
    expect(screen.queryByText("Keys for Alice")).toBeNull();
  });
});
