// @vitest-environment jsdom
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "@/messages/en.json";
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { ContextDBWorkspaceResultCheck } from "@/components/contextdb/workspace-result-check";
import { ContextDBError, contextDBRequest } from "@/lib/contextdb-api";
vi.mock("@/lib/contextdb-api", async (original) => ({
  ...(await original<typeof import("@/lib/contextdb-api")>()),
  contextDBRequest: vi.fn(),
}));
const api = vi.mocked(contextDBRequest);
const target = { bank_id: "shared", workspace_id: "a".repeat(32), etag: `"${"a".repeat(32)}:1"` };
const mount = (reason?: "unknown" | "conflict") =>
  render(
    <NextIntlClientProvider locale="en" messages={withContextdbMessages(en, "en")}>
      <ContextDBWorkspaceResultCheck target={{ ...target, reason }} onClose={vi.fn()} />
    </NextIntlClientProvider>
  );
afterEach(() => {
  cleanup();
  api.mockReset();
});
describe("identity-bound workspace observations", () => {
  it("shows a successor without acquiring or replaying a delete condition", async () => {
    api.mockResolvedValue({
      bank_id: "shared",
      workspace_id: "b".repeat(32),
      etag: `"${"b".repeat(32)}:1"`,
      state: "active",
    });
    mount();
    await screen.findByText(/name now refers to a different workspace/);
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText(/name now refers to a different workspace/);
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(
      api.mock.calls.every(
        ([path, options]) =>
          path === "/workspaces/shared" && !options?.method && options?.etag === undefined
      )
    ).toBe(true);
    expect(target.etag).toBe(`"${"a".repeat(32)}:1"`);
  });
  it("keeps the original UUID and current state visible without claiming work stopped", async () => {
    api.mockResolvedValue({ ...target, state: "deleting" });
    mount();
    await screen.findByText(/original workspace is currently deleting/);
    expect(
      screen.getByText(/does not prove that accepted requests or background work stopped/)
    ).toBeTruthy();
  });
  it("describes a rejected delete condition as conflict rather than an uncertain write", async () => {
    api.mockResolvedValue({ ...target, state: "active" });
    mount("conflict");
    await screen.findByText(/original deletion condition was rejected/);
    expect(screen.queryByText(/deletion result is unknown/)).toBeNull();
    expect(api.mock.calls.every(([, options]) => !options?.method)).toBe(true);
  });
  it("treats 404 as current absence rather than proof of rollback or completion", async () => {
    api.mockRejectedValue(new ContextDBError("Missing", 404, "not_found", null));
    mount();
    await screen.findByText(/original request may still be running/);
    expect(api).toHaveBeenCalledOnce();
    expect(screen.queryByText(/deletion succeeded/i)).toBeNull();
  });
  it("shows a lookup outage as an error and allows another read", async () => {
    api.mockRejectedValueOnce(new ContextDBError("Lookup unavailable", 503, "unavailable", null));
    api.mockResolvedValueOnce({ ...target, state: "active" });
    mount();
    await screen.findByRole("alert");
    expect(screen.queryByText(/No workspace is currently visible/)).toBeNull();
    fireEvent.click(screen.getByText("Refresh"));
    await screen.findByText(/original workspace is currently active/);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
