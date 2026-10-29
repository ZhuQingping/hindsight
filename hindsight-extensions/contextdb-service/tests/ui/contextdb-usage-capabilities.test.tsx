// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import { ContextDBModeProvider } from "@/lib/contextdb-mode";
import { NextIntlClientProvider } from "next-intl";
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { ContextDBUsageProvider, ContextDBUsageFields } from "@/components/contextdb/recall-usage";
import { contextDBRequest } from "@/lib/contextdb-api";
import {
  ContextDBUsageCapabilities,
  useRecallUsageEnabled,
} from "@/components/contextdb/usage-capabilities";

const runtime = vi.hoisted(() => ({ path: "/dashboard", product: "ContextBase" }));
vi.mock("next/navigation", () => ({ usePathname: () => runtime.path }));
vi.mock("@/components/product-runtime", () => ({ useProductName: () => runtime.product }));
vi.mock("@/lib/contextdb-api", () => ({ contextDBRequest: vi.fn() }));
const api = vi.mocked(contextDBRequest);
function Probe() {
  return <span>{useRecallUsageEnabled() ? "Statistics on" : "Statistics off"}</span>;
}
function view(enabled = true) {
  return (
    <ContextDBModeProvider enabled={enabled}>
      <ContextDBUsageCapabilities>
        <p>Content is visible</p>
        <Probe />
        <Probe />
      </ContextDBUsageCapabilities>
    </ContextDBModeProvider>
  );
}
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  runtime.path = "/dashboard";
  runtime.product = "ContextBase";
});
it("native mode never probes the plugin", () => {
  render(view(false));
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
  expect(api).not.toHaveBeenCalled();
});
it("reads one explicit admin capability for the app without blocking content", async () => {
  let resolve!: (value: unknown) => void;
  api.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      })
  );
  const ui = render(view());
  expect(screen.getByText("Content is visible")).toBeTruthy();
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
  expect(api).toHaveBeenCalledOnce();
  expect(api.mock.calls[0][0]).toBe("/admin/identity");
  await act(async () => resolve({ role: "admin", capabilities: { recall_usage: true } }));
  expect(screen.getAllByText("Statistics on")).toHaveLength(2);
  ui.rerender(view());
  expect(api).toHaveBeenCalledOnce();
});
it.each([
  {},
  { role: "admin" },
  { role: "admin", capabilities: { recall_usage: false } },
  { role: "admin", capabilities: { recall_usage: "true" } },
])("missing, old or disabled capabilities stay hidden %#", async (value) => {
  api.mockResolvedValue(value);
  await act(async () => {
    render(view());
  });
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
  expect(screen.getByText("Content is visible")).toBeTruthy();
});
it.each([{}, { role: "member" }, { role: "admin" }])(
  "feature capability is independent from the caller role %#",
  async (identity) => {
    api.mockResolvedValue({ ...identity, capabilities: { recall_usage: true } });
    render(view());
    await screen.findAllByText("Statistics on");
    expect(api).toHaveBeenCalledOnce();
  }
);
it("failure keeps content; disabling mode aborts and ignores a late capability", async () => {
  api.mockRejectedValueOnce(new Error("404"));
  const ui = render(view());
  await act(async () => {});
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
  ui.unmount();
  let resolve!: (value: unknown) => void;
  api.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      })
  );
  const next = render(view());
  const signal = api.mock.calls.at(-1)?.[1]?.signal;
  next.rerender(view(false));
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve({ role: "admin", capabilities: { recall_usage: true } }));
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
});

it.each(["/login", "/zh-CN/login", "/en/login"])(
  "defers the capability until successful login navigation from %s",
  async (path) => {
    runtime.path = path;
    api.mockResolvedValue({ role: "admin", capabilities: { recall_usage: true } });
    const ui = render(view());
    expect(api).not.toHaveBeenCalled();
    runtime.path = "/banks/demo";
    ui.rerender(view());
    await screen.findAllByText("Statistics on");
    expect(api).toHaveBeenCalledOnce();
    runtime.path = "/banks/login";
    ui.rerender(view());
    expect(screen.getAllByText("Statistics on")).toHaveLength(2);
    expect(api).toHaveBeenCalledOnce();
  }
);

it("masks product changes immediately and ignores a late old capability", async () => {
  const resolvers: Array<(value: unknown) => void> = [];
  api.mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)));
  const ui = render(view());
  runtime.product = "Different product";
  ui.rerender(view());
  await act(async () => resolvers[0]({ role: "admin", capabilities: { recall_usage: true } }));
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
  await act(async () => resolvers[1]({ role: "admin", capabilities: { recall_usage: false } }));
  expect(screen.getAllByText("Statistics off")).toHaveLength(2);
});

it.each([null, { role: "admin" }, { role: "admin", capabilities: { recall_usage: false } }])(
  "missing or disabled capability never starts a usage request in the real component chain %#",
  async (value) => {
    api.mockResolvedValue(value);
    await act(async () => {
      render(
        <NextIntlClientProvider locale="en" messages={withContextdbMessages({}, "en")}>
          <ContextDBModeProvider enabled>
            <ContextDBUsageCapabilities>
              <ContextDBUsageProvider
                bankId="demo"
                objectType="memory"
                ids={["00000000-0000-4000-8000-000000000001"]}
              >
                <p>Memory body</p>
                <ContextDBUsageFields objectId="00000000-0000-4000-8000-000000000001" />
              </ContextDBUsageProvider>
            </ContextDBUsageCapabilities>
          </ContextDBModeProvider>
        </NextIntlClientProvider>
      );
    });
    expect(screen.getByText("Memory body")).toBeTruthy();
    expect(screen.queryByText(/Recall count/)).toBeNull();
    expect(api).toHaveBeenCalledOnce();
    expect(api.mock.calls[0][0]).toBe("/admin/identity");
  }
);
