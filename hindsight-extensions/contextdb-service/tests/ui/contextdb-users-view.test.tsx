// @vitest-environment jsdom
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { openMenuAction } from "./support/menu";
import React from "react";
import { selectOption } from "./support/select";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, fireEvent, waitFor, cleanup, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "@/messages/en.json";
import zh from "@/messages/zh-CN.json";
import { ContextDBUsersView } from "@/components/contextdb/users-view";
import {
  contextDBRequest,
  createContextDBUser,
  createContextDBKey,
  ContextDBError,
  type ContextDBUser,
  type ContextDBKeyMetadata,
  type ContextDBKeyIssued,
} from "@/lib/contextdb-api";
vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  contextDBRequest: vi.fn(),
  createContextDBUser: vi.fn(),
  createContextDBKey: vi.fn(),
}));
const member: ContextDBUser = {
  user_id: "member",
  name: "Alice",
  status: "active",
  version: 7,
  created_at: "2026-01-01",
};
const key: ContextDBKeyMetadata = {
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
    <NextIntlClientProvider
      locale={locale}
      messages={withContextdbMessages(locale === "en" ? messages : zh, locale)}
    >
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
  selectOption(within(dialog).getByLabelText("Workspaces"), "all");
}
beforeEach(() => {
  api.mockReset();
  vi.mocked(createContextDBUser).mockImplementation((body, signal) =>
    contextDBRequest<ContextDBUser>("/users", { method: "POST", body, signal })
  );
  vi.mocked(createContextDBKey).mockImplementation((userId, body) =>
    contextDBRequest<ContextDBKeyIssued>(`/users/${userId}/keys`, { method: "POST", body })
  );
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
  vi.unstubAllGlobals();
});
describe("member and key management", () => {
  it("refreshes an uncertain member creation without scanning or replay", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (path === "/users" && options?.method === "POST")
        throw new ContextDBError("Result unknown", 503, "unknown", null);
      if (path.includes("q=Bob"))
        return page([{ ...member, user_id: "observed-bob", name: "Bob" }]);
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Create member"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Result unknown");
    expect(within(dialog).queryByText(/^(Save|Save changes|Create)$/)).toBeNull();
    fireEvent.click(within(dialog).getByText("Check current members"));
    await screen.findByText("Bob");
    expect(api.mock.calls.some(([path]) => path.includes("limit=100"))).toBe(false);
    expect(screen.getByText(/matching name does not prove this creation succeeded/)).toBeTruthy();
    expect(api.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  });
  it("leaves a member validation error editable instead of treating it as unknown", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (path === "/users" && options?.method === "POST")
        throw new ContextDBError("Invalid member name", 400, "invalid", null);
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Create member"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Invalid member name");
    expect(within(dialog).getByText(/^(Save|Save changes|Create)$/)).toHaveProperty(
      "disabled",
      false
    );
    expect(within(dialog).getByLabelText("Name")).toHaveProperty("disabled", false);
    expect(within(dialog).queryByText("Check current members")).toBeNull();
  });
  it("inspects the original member after a conflict without applying a newer version to its draft", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "PATCH")
        throw new ContextDBError("Version changed", 412, "version_conflict", null);
      if (path === "/users?limit=100&offset=0")
        return page([{ ...member, version: 9, name: "Current Alice" }]);
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.keyDown(screen.getByRole("button", { name: "More" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Rename member" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Old draft" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Version changed");
    expect(within(dialog).queryByText(/^(Save|Save changes|Create)$/)).toBeNull();
    fireEvent.click(within(dialog).getByText("Check current members"));
    await screen.findByText(/Original member ID: member/);
    expect(api.mock.calls.some(([path]) => path.includes("limit=100"))).toBe(false);
    const writes = api.mock.calls.filter(([, options]) => options?.method === "PATCH");
    expect(writes).toHaveLength(1);
    expect(writes[0][1]?.version).toBe(7);
  });
  it("refreshes uncertain member deletion while retaining its original ID without scanning", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "DELETE")
        throw new ContextDBError("Result unknown", 503, "unknown", null);
      if (path === "/users?limit=100&offset=0")
        return page(
          Array.from({ length: 100 }, (_, index) => ({
            ...member,
            user_id: `other-${index}`,
            name: `Other ${index}`,
          })),
          101
        );
      if (path === "/users?limit=100&offset=100")
        return page([{ ...member, name: "Renamed Alice" }], 101);
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.keyDown(screen.getByRole("button", { name: "More" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByText("Delete"));
    await within(dialog).findByText("Result unknown");
    expect(within(dialog).queryByRole("button", { name: "Delete" })).toBeNull();
    fireEvent.click(within(dialog).getByText("Check current members"));
    await screen.findByText(/Original member ID: member/);
    expect(api.mock.calls.some(([path]) => path.includes("limit=100"))).toBe(false);
    expect(api.mock.calls.filter(([, options]) => options?.method === "DELETE")).toHaveLength(1);
  });

  it("keeps Key creation open when a success response loses the one-time secret", async () => {
    const actual =
      await vi.importActual<typeof import("@/lib/contextdb-api")>("@/lib/contextdb-api");
    vi.mocked(createContextDBKey).mockImplementation(actual.createContextDBKey);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          key_id: "c".repeat(32),
          user_id: member.user_id,
        }),
        { status: 201 }
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "new agent" } });
    selectAll(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: /^(Save|Save changes|Create)$/ }));
    await within(dialog).findByText(/Result unknown/);
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(screen.queryByTestId("issued-secret")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("creates a member with only its name and shows the returned identity", async () => {
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
    expect(await screen.findByText("成员 Bob 创建成功，ID：bob")).toBeTruthy();
    expect(screen.queryByText("Bob 的 Key")).toBeNull();
    expect(api.mock.calls.some(([path]) => path.includes("limit=100"))).toBe(false);
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
    expect(screen.getByText("Agent").closest("td")?.colSpan).toBe(4);
    expect(screen.getByText(/^Created:/)).toBeTruthy();
    expect(screen.getByText(/^Last used:/)).toBeTruthy();
  });
  it("creates mixed permissions, defaults newly selected workspaces to read/write", async () => {
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Application" } });
    fireEvent.click(await within(dialog).findByText("Workspace A"));
    fireEvent.click(within(dialog).getByText("Workspace B"));
    expect(await within(dialog).findByLabelText("Workspace A Permission")).toHaveProperty(
      "textContent",
      "Read and write"
    );
    selectOption(within(dialog).getByLabelText("Workspace A Permission"), "read");
    expect(within(dialog).queryByText("Deleted workspace")).toBeNull();
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
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
    expect(within(dialog).getByText(/^(Save|Save changes|Create)$/)).toHaveProperty(
      "disabled",
      true
    );
    selectAll(dialog);
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
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
      "textContent",
      "Read only"
    );
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Renamed" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys/key",
        expect.objectContaining({ method: "PATCH", version: 3, body: { name: "Renamed" } })
      )
    );
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
  it("keeps off-page grants from the Key response without a per-workspace lookup", async () => {
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
      "textContent",
      "Read only"
    );
    fireEvent.click(within(dialog).getByText("Workspace B"));
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
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
    await within(dialog).findByLabelText("missing Permission");
    expect(api.mock.calls.some(([path]) => path === "/workspaces/missing")).toBe(false);
    fireEvent.change(within(dialog).getByLabelText("Name"), {
      target: { value: "Still editable" },
    });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member/keys/key",
        expect.objectContaining({ body: { name: "Still editable" } })
      )
    );
  });
  it("submits the original UUID and version and leaves backend conflicts visible", async () => {
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) => {
      if (options?.method === "PATCH")
        throw new ContextDBError(
          "Workspace changed. Refresh first.",
          412,
          "version_conflict",
          null
        );
      if (path.startsWith("/workspaces?"))
        return page([
          {
            workspace_id: "successor-id",
            bank_id: "space-a",
            name: "New workspace A",
            state: "active",
          },
        ]);
      return original(path, options);
    });
    mount();
    await openKeys();
    fireEvent.click(screen.getByText("Edit"));
    const dialog = screen.getByRole("dialog");
    await within(dialog).findByText("New workspace A");
    selectOption(within(dialog).getByLabelText("Workspace A Permission"), "read_write");
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Workspace changed. Refresh first.");
    const writes = api.mock.calls.filter(([, options]) => options?.method === "PATCH");
    expect(writes).toHaveLength(1);
    expect(writes[0][1]).toMatchObject({
      version: 3,
      body: {
        authorization: {
          mode: "selected",
          workspaces: [{ bank_id: "space-a", workspace_id: "space-a", permission: "read_write" }],
        },
      },
    });
    expect(within(dialog).queryByText(/^(Save|Save changes|Create)$/)).toBeNull();
    expect(api.mock.calls.some(([path]) => path.startsWith("/workspaces/"))).toBe(false);
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
    fireEvent.click(await within(dialog).findByText("Workspace A"));
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
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
    await openMenuAction(screen.getByRole("button", { name: /^More:/ }), "Revoke");
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
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await within(dialog).findByText("Refresh before retrying");
    expect(api.mock.calls.filter(([, options]) => options?.method === "PATCH").length).toBe(1);
  });
  it("clears issued secrets when the page hides and never persists them", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "App" } });
    selectAll(dialog);
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
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
    expect(within(dialog).getByLabelText("Permission")).toHaveProperty("textContent", "Read only");
    selectOption(within(dialog).getByLabelText("Workspaces"), "selected");
    expect(await within(dialog).findByLabelText("Workspace A Permission")).toHaveProperty(
      "textContent",
      "Read only"
    );
  });
  it("does not scan or auto-expand a directory after successful member creation", async () => {
    const original = api.getMockImplementation()!;
    const bob = { ...member, user_id: "new-bob", name: "Bob" };
    api.mockImplementation(async (path, options) => {
      if (path === "/users" && options?.method === "POST") return bob;
      if (path.startsWith("/users?") && path.includes("q=Bob"))
        return page(
          Array.from({ length: 20 }, (_, index) => ({
            ...bob,
            user_id: `other-${index}`,
            name: `Bob ${index}`,
          })),
          101
        );
      return original(path, options);
    });
    mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Create member"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await screen.findByText("Member Bob created. ID: new-bob");
    expect(screen.queryByText("Keys for Bob")).toBeNull();
    expect(
      api.mock.calls.some(([path]) => path.includes("limit=100") || path.includes("offset=100"))
    ).toBe(false);
    expect(api.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  });

  it("disables a member through the More menu with its current version", async () => {
    mount();
    await screen.findByText("Alice");
    fireEvent.keyDown(screen.getByRole("button", { name: "More" }), { key: "Enter" });
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
    fireEvent.keyDown(screen.getByRole("button", { name: "More" }), { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    expect(api.mock.calls.some(([, options]) => options?.method === "DELETE")).toBe(false);
    const original = api.getMockImplementation()!;
    api.mockImplementation(async (path, options) =>
      path.startsWith("/users?") ? page([]) : original(path, options)
    );
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(api).toHaveBeenCalledWith(
        "/users/member",
        expect.objectContaining({ method: "DELETE", signal: expect.any(AbortSignal) })
      )
    );
    await screen.findByText("No users yet.");
    expect(screen.queryByText("Keys for Alice")).toBeNull();
  });
  it("aborts a member write on unmount and ignores its delayed success", async () => {
    const original = api.getMockImplementation()!;
    let resolve!: (value: ContextDBUser) => void;
    let signal!: AbortSignal;
    api.mockImplementation(async (path, options) => {
      if (path === "/users" && options?.method === "POST") {
        signal = options.signal!;
        return new Promise((done) => {
          resolve = done;
        });
      }
      return original(path, options);
    });
    const view = mount();
    await screen.findByText("Alice");
    fireEvent.click(screen.getByText("Create member"));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Bob" } });
    fireEvent.click(within(dialog).getByText(/^(Save|Save changes|Create)$/));
    await waitFor(() => expect(signal).toBeDefined());
    const reads = api.mock.calls.filter(([, options]) => !options?.method).length;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ ...member, user_id: "new-bob", name: "Bob" }));
    expect(api.mock.calls.filter(([, options]) => !options?.method)).toHaveLength(reads);
  });
});

describe("management read states and locale", () => {
  it("does not claim there are zero users after a failed initial GET; retry only reads", async () => {
    api.mockRejectedValueOnce(new Error("Directory unavailable"));
    mount();
    await screen.findByText("Directory unavailable");
    expect(screen.queryByText("No users yet.")).toBeNull();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("—");
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText("Alice");
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
  it("distinguishes no search matches from an empty instance", async () => {
    mount();
    await screen.findByText("Alice");
    api.mockResolvedValue(page([]));
    fireEvent.change(screen.getByLabelText("Search members"), { target: { value: "absent" } });
    await screen.findByText("No matches. Clear the search to see all results.");
    expect(screen.queryByText("No users yet.")).toBeNull();
  });
  it("does not present a failed refresh as current data or as an empty instance", async () => {
    mount();
    await screen.findByText("Alice");
    api.mockRejectedValueOnce(new Error("Refresh unavailable"));
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText("Refresh unavailable");
    expect(screen.getByText(/Previously loaded data is not current/)).toBeTruthy();
    expect(screen.queryByText("No users yet.")).toBeNull();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain("—");
  });
  it.each(["en", "zh-CN"])("uses UI locale %s for member and Key dates", async (locale) => {
    const format = vi.spyOn(Date.prototype, "toLocaleString");
    mount(locale);
    await screen.findByText("Alice");
    expect(format.mock.calls.every(([arg]) => arg === locale)).toBe(true);
    const memberCalls = format.mock.calls.length;
    expect(memberCalls).toBeGreaterThan(0);
    fireEvent.click(
      screen.getByRole("button", {
        name: locale === "en" ? "Manage API keys" : "管理 API Key",
        expanded: false,
      })
    );
    await screen.findByText("Agent");
    expect(format.mock.calls.length).toBeGreaterThan(memberCalls);
    expect(format.mock.calls.slice(memberCalls).every(([arg]) => arg === locale)).toBe(true);
    const row = screen.getByText("Agent").closest("tr")!;
    const details = within(row)
      .getByText(locale === "en" ? "Key details" : "密钥详情")
      .closest("details")!;
    fireEvent.click(details.querySelector("summary")!);
    expect(details.textContent).toContain(locale === "en" ? "Last used: —" : "最后使用: —");
    expect(row.textContent).not.toContain("Invalid Date");
  });
  it("uses one Manage API keys action to expand and collapse the panel", async () => {
    mount();
    await openKeys();
    expect(screen.getAllByRole("button", { name: "Manage API keys" })).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Manage API keys", expanded: true }));
    expect(screen.queryByText("Agent")).toBeNull();
  });
});

it("does not report a user created when a parseable success response lacks its identity", async () => {
  const actual = await vi.importActual<typeof import("@/lib/contextdb-api")>("@/lib/contextdb-api");
  vi.mocked(createContextDBUser).mockImplementation(actual.createContextDBUser);
  const initial = api.getMockImplementation()!;
  api.mockImplementation((path, options) =>
    options?.method === "POST" && path === "/users"
      ? actual.contextDBRequest(path, options)
      : initial(path, options)
  );
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 201 })));
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Create member" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "New user" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Result unknown");
  expect(screen.getByRole("button", { name: "Check current members" })).toBeTruthy();
  expect(screen.queryByText(/Member New user created/)).toBeNull();
});

describe("controlled management dialog focus", () => {
  it.each(["Cancel", "Close", "Escape"])("returns member create focus after %s", async (close) => {
    mount();
    await screen.findByText("Alice");
    const trigger = screen.getByRole("button", { name: "Create member" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog");
    if (close === "Escape") fireEvent.keyDown(dialog, { key: "Escape" });
    else fireEvent.click(within(dialog).getByRole("button", { name: close }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(api.mock.calls.some(([, options]) => options?.method)).toBe(false);
  });
  it.each(["Edit", "Revoke"])("returns cancelled %s to its key row", async (action) => {
    mount();
    await openKeys();
    const trigger = screen.getByRole("button", { name: action === "Edit" ? "Edit" : /^More:/ });
    if (action === "Revoke") await openMenuAction(trigger, "Revoke");
    else {
      trigger.focus();
      fireEvent.click(trigger);
    }
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" })
    );
    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(api.mock.calls.some(([, options]) => options?.method)).toBe(false);
  });
  it("keeps the new secret dialog focused, then returns to create key", async () => {
    mount();
    const dialog = await openCreate();
    fireEvent.change(within(dialog).getByLabelText("Name"), { target: { value: "Focus test" } });
    selectAll(dialog);
    fireEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    const secret = await screen.findByRole("dialog", { name: "Save this secret now" });
    await waitFor(() => expect(secret.contains(document.activeElement)).toBe(true));
    fireEvent.click(within(secret).getByRole("button", { name: "I saved it — close" }));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: "Create API key" }))
    );
    expect(screen.queryByTestId("issued-secret")).toBeNull();
  });
});

it.each(["Rename member", "Delete"])(
  "returns %s dialog to the member menu button",
  async (action) => {
    mount();
    await screen.findByText("Alice");
    const more = screen.getByRole("button", { name: "More" });
    more.focus();
    fireEvent.keyDown(more, { key: "Enter" });
    fireEvent.click(await screen.findByRole("menuitem", { name: action }));
    fireEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" })
    );
    await waitFor(() => expect(document.activeElement).toBe(more));
    expect(api.mock.calls.some(([, options]) => options?.method)).toBe(false);
  }
);
