// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import * as mode from "@/lib/contextdb-mode";
import { ContextDBModeProvider } from "@/lib/contextdb-mode";
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { ContextDBUsageProvider, ContextDBUsageFields } from "@/components/contextdb/recall-usage";
import { contextDBRequest } from "@/lib/contextdb-api";
vi.mock("@/lib/contextdb-api", () => ({ contextDBRequest: vi.fn() }));
vi.mock("@/components/contextdb/usage-capabilities", () => ({
  useRecallUsageEnabled: () => mode.useContextDBMode(),
}));
const api = vi.mocked(contextDBRequest);
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const report = (bank = "a", ids = [id(1)], count = 2) => ({
  bank_id: bank,
  object_type: "memory",
  items: ids.map((object_id) => ({
    object_id,
    recall_count: count,
    last_recalled_at: count ? "2026-10-28T06:00:00Z" : null,
  })),
});
function view(bank = "a", ids = [id(1)], enabled = true, locale = "en") {
  return (
    <NextIntlClientProvider locale={locale} messages={withContextdbMessages({}, locale)}>
      <ContextDBModeProvider enabled={enabled}>
        <ContextDBUsageProvider bankId={bank} objectType="memory" ids={ids}>
          <p>Content is visible</p>
          {ids.map((objectId) => (
            <ContextDBUsageFields key={objectId} objectId={objectId} />
          ))}
        </ContextDBUsageProvider>
      </ContextDBModeProvider>
    </NextIntlClientProvider>
  );
}
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  vi.useRealTimers();
});
it("renders content while one batch for 100 visible objects is pending; equal sets do not refetch", async () => {
  let resolve!: (value: unknown) => void;
  api.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      })
  );
  const ids = Array.from({ length: 100 }, (_, n) => id(n));
  const ui = render(view("a", ids));
  expect(screen.getByText("Content is visible")).toBeTruthy();
  expect(screen.getAllByText("Recall count: Loading…")).toHaveLength(100);
  expect(api).toHaveBeenCalledOnce();
  const path = api.mock.calls[0][0];
  expect(new URL(path, "http://ui.local").searchParams.getAll("ids")).toHaveLength(100);
  ui.rerender(view("a", [...ids].reverse()));
  expect(api).toHaveBeenCalledOnce();
  await act(async () => resolve(report("a", ids)));
  expect(screen.getAllByText("Recall count: 2")).toHaveLength(100);
});
it("aborts old bank/page requests and ignores late results without showing another bank's stats", async () => {
  const pending: Array<(value: unknown) => void> = [];
  api.mockImplementation(() => new Promise((r) => pending.push(r)));
  const ui = render(view());
  const signal = api.mock.calls[0][1]?.signal;
  ui.rerender(view("b", [id(2)]));
  expect(signal?.aborted).toBe(true);
  await act(async () => pending[1](report("b", [id(2)], 9)));
  expect(screen.getByText("Recall count: 9")).toBeTruthy();
  await act(async () => pending[0](report("a", [id(1)], 2)));
  expect(screen.queryByText("Recall count: 2")).toBeNull();
  ui.rerender(view("b", [id(3)]));
  expect(screen.queryByText("Recall count: 9")).toBeNull();
  expect(screen.getByText("Recall count: Loading…")).toBeTruthy();
});
it("keeps content on failure, never invents zero, and retries only the statistics GET", async () => {
  api.mockRejectedValueOnce(new Error("503"));
  api.mockResolvedValueOnce(report());
  render(view());
  await screen.findByText("Recall statistics unavailable. Content is still available.");
  expect(screen.getByText("Content is visible")).toBeTruthy();
  expect(screen.queryByText("Recall count: 0")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Retry statistics" }));
  await screen.findByText("Recall count: 2");
  expect(api).toHaveBeenCalledTimes(2);
  expect(api.mock.calls.every(([, options]) => options?.method === undefined)).toBe(true);
});
it.each(["en", "zh-CN"])("renders zero/null and locale dates in %s", async (locale) => {
  api.mockResolvedValueOnce(report("a", [id(1)], 0));
  api.mockResolvedValueOnce(report("a", [id(2)], 2));
  const ui = render(view("a", [id(1)], true, locale));
  await screen.findByText(locale === "en" ? "Recall count: 0" : "召回次数: 0");
  expect(
    screen.getByText(locale === "en" ? "Last recalled: Not recorded" : "最后召回时间: 暂无记录")
  ).toBeTruthy();
  ui.rerender(view("a", [id(2)], true, locale));
  await screen.findByText(new Date("2026-10-28T06:00:00Z").toLocaleString(locale));
  expect(document.querySelector("time")?.getAttribute("datetime")).toBe("2026-10-28T06:00:00Z");
});
it("does not invent zero for an omitted/deleted object", async () => {
  api.mockResolvedValue(report("a", []));
  render(view());
  await screen.findByText("Recall count: Unavailable");
  expect(screen.queryByText("Recall count: 0")).toBeNull();
});
it.each([
  { ...report(), bank_id: "another-bank" },
  { ...report(), items: [...report().items, ...report().items] },
  report("a", [id(99)]),
  { ...report(), items: [{ ...report().items[0], recall_count: -1 }] },
  { ...report(), items: [{ ...report().items[0], last_recalled_at: "invalid" }] },
  { ...report(), items: [{ ...report().items[0], last_recalled_at: null }] },
])(
  "rejects malformed or mismatched reports instead of displaying misleading values %#",
  async (invalid) => {
    api.mockResolvedValue(invalid);
    render(view());
    await screen.findByText("Recall statistics unavailable. Content is still available.");
    expect(screen.queryByText("Recall count: 2")).toBeNull();
  }
);
it("native mode and empty/over-limit pages make no statistics request", async () => {
  const ui = render(view("a", [id(1)], false));
  expect(screen.queryByText(/Recall count/)).toBeNull();
  ui.rerender(view("a", []));
  expect(api).not.toHaveBeenCalled();
  ui.rerender(
    view(
      "a",
      Array.from({ length: 101 }, (_, n) => id(n))
    )
  );
  await screen.findByText("Recall statistics unavailable. Content is still available.");
  expect(api).not.toHaveBeenCalled();
});
it("does not poll and aborts on unmount", async () => {
  api.mockResolvedValue(report());
  const ui = render(view());
  await screen.findByText("Recall count: 2");
  vi.useFakeTimers();
  await act(async () => vi.advanceTimersByTime(60000));
  expect(api).toHaveBeenCalledOnce();
  const signal = api.mock.calls[0][1]?.signal;
  ui.unmount();
  expect(signal?.aborted).toBe(true);
});
