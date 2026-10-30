// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { formatMemoryTime } from "@/lib/memory-time";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "zh-CN",
}));
vi.mock("@/lib/bank-context", () => ({ useBank: () => ({ currentBank: "time-test" }) }));
const { getGraph, listMemories } = vi.hoisted(() => ({
  getGraph: vi.fn(),
  listMemories: vi.fn(),
}));
vi.mock("@/lib/api", () => ({
  client: {
    getGraph,
    listMemories,
    getBankStats: async () => ({ pending_consolidation: 0 }),
    listObservationScopes: async () => ({ scopes: [] }),
  },
}));
vi.mock("@/components/constellation", () => ({ Constellation: () => null }));
vi.mock("@/components/graph-data", () => ({
  convertGraphData: () => ({ nodes: [], links: [] }),
}));
vi.mock("@/components/memory-detail-modal", () => ({ MemoryDetailModal: () => null }));
vi.mock("@/components/tag-filter-input", () => ({ TagFilterInput: () => null }));
vi.mock("@/components/observation-scope-filter", () => ({ ObservationScopeFilter: () => null }));

const { DataView, TimelineView } = await import("@/components/data-view");
const row = (id: string, date: string) => ({
  id,
  text: id,
  mentioned_at: date,
  occurred_start: date,
});
const rows = [
  row("old-year", "2025-02-03T02:10:00Z"),
  row("same-day-early", "2026-10-27T01:02:00Z"),
  row("other-month", "2026-08-05T03:00:00Z"),
  row("same-day-late", "2026-10-27T06:07:00Z"),
];

beforeEach(() => {
  getGraph.mockResolvedValue({ table_rows: rows, total_units: rows.length });
  listMemories.mockResolvedValue({ items: rows });
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function tableTexts() {
  return Array.from(screen.getByRole("table").querySelectorAll("tbody tr")).map(
    (element) => element.querySelector("td")?.textContent
  );
}

function timelineTexts(container: HTMLElement) {
  return Array.from(container.querySelectorAll("p.line-clamp-2")).map((el) => el.textContent);
}

describe("memory table time", () => {
  it.each(["world", "experience", "observation"] as const)(
    "%s shows minutes and toggles mention order before pagination",
    async (factType) => {
      render(<DataView factType={factType} />);
      fireEvent.click(await screen.findByRole("button", { name: "table" }));
      expect(tableTexts()).toEqual(["same-day-late", "same-day-early", "other-month", "old-year"]);
      const newest = within(screen.getByRole("table")).getAllByRole("row")[1];
      const cells = within(newest).getAllByRole("cell");
      expect(cells.at(-1)?.textContent).toBe(formatMemoryTime(rows[3].mentioned_at, "zh-CN"));
      expect(cells.at(-2)?.textContent).toBe(formatMemoryTime(rows[3].occurred_start, "zh-CN"));
      fireEvent.click(screen.getByRole("button", { name: "columnMentioned: newestFirst" }));
      expect(tableTexts()).toEqual(["old-year", "other-month", "same-day-early", "same-day-late"]);
      fireEvent.click(screen.getByRole("button", { name: "columnMentioned: oldestFirst" }));
      expect(tableTexts()[0]).toBe("same-day-late");
    }
  );

  it("sorts all loaded rows before taking a page and resets the page on direction change", async () => {
    getGraph.mockResolvedValue({
      total_units: 101,
      table_rows: Array.from({ length: 101 }, (_, i) =>
        row(`memory-${i}`, new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString())
      ),
    });
    render(<DataView factType="world" />);
    fireEvent.click(await screen.findByRole("button", { name: "table" }));
    expect(tableTexts()).toHaveLength(100);
    expect(tableTexts()[0]).toBe("memory-100");
    fireEvent.click(screen.getByRole("button", { name: "next" }));
    expect(tableTexts()).toEqual(["memory-0"]);
    fireEvent.change(screen.getByRole("combobox", { name: "sortTimeField" }), {
      target: { value: "occurred_start" },
    });
    expect(tableTexts()).toHaveLength(100);
    expect(tableTexts()[0]).toBe("memory-100");
    fireEvent.click(screen.getByRole("button", { name: "next" }));
    fireEvent.click(screen.getByRole("button", { name: "columnOccurred: newestFirst" }));
    expect(tableTexts()).toHaveLength(100);
    expect(tableTexts()[0]).toBe("memory-0");
  });

  it("applies the same ordering to invalidated facts", async () => {
    render(<DataView factType="world" />);
    fireEvent.click(await screen.findByRole("button", { name: "table" }));
    fireEvent.click(screen.getByRole("button", { name: "filterInvalidated" }));
    await screen.findByText("same-day-late");
    expect(listMemories).toHaveBeenCalledWith(
      "time-test",
      expect.objectContaining({ state: "invalidated" })
    );
    expect(tableTexts()[0]).toBe("same-day-late");
    fireEvent.click(screen.getByRole("button", { name: "columnMentioned: newestFirst" }));
    expect(tableTexts()[0]).toBe("old-year");
  });
});

it("orders timeline groups and same-day items in both directions at every zoom level", () => {
  const onMemoryClick = vi.fn();
  const { container } = render(
    <TimelineView data={{}} filteredRows={rows} onMemoryClick={onMemoryClick} />
  );
  const desc = ["same-day-late", "same-day-early", "other-month", "old-year"];
  expect(timelineTexts(container)).toEqual(desc);
  expect(
    screen.getByText(`columnOccurred: ${formatMemoryTime(rows[3].occurred_start, "zh-CN")}`)
  ).toBeTruthy();
  for (const level of ["month", "week", "day"]) {
    expect(screen.getByText(`granularity${level[0].toUpperCase()}${level.slice(1)}`)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "columnMentioned: newestFirst" }));
    expect(timelineTexts(container)).toEqual([...desc].reverse());
    fireEvent.click(screen.getByRole("button", { name: "columnMentioned: oldestFirst" }));
    expect(timelineTexts(container)).toEqual(desc);
    if (level !== "day") fireEvent.click(screen.getByTitle("zoomIn"));
  }
  for (let i = 0; i < 3; i++) fireEvent.click(screen.getByTitle("zoomOut"));
  expect(screen.getByText("granularityYear")).toBeTruthy();
  expect(timelineTexts(container)).toEqual(desc);
  fireEvent.click(screen.getByRole("button", { name: "columnMentioned: newestFirst" }));
  expect(timelineTexts(container)).toEqual([...desc].reverse());
  fireEvent.click(screen.getByText("old-year"));
  expect(onMemoryClick).toHaveBeenCalledWith("old-year");
});

it("shares direction between the table and timeline", async () => {
  render(<DataView factType="world" />);
  fireEvent.click(await screen.findByRole("button", { name: "table" }));
  fireEvent.click(screen.getByRole("button", { name: "columnMentioned: newestFirst" }));
  fireEvent.click(screen.getByRole("button", { name: "timeline" }));
  expect(screen.getByRole("button", { name: "columnMentioned: oldestFirst" })).toBeTruthy();
});

const mixedRows = [
  { ...row("past-event", "2026-10-27T07:00:00Z"), occurred_start: "2026-10-20T01:00:00Z" },
  { ...row("recent-event", "2026-10-26T07:00:00Z"), occurred_start: "2026-10-25T01:00:00Z" },
  { ...row("preference", "2026-10-27T08:00:00Z"), occurred_start: null },
  { id: "unknown", text: "unknown", mentioned_at: null, occurred_start: null },
];

it.each(["world", "experience", "observation"] as const)(
  "%s keeps table and timeline membership/order aligned when dates differ or are missing",
  async (factType) => {
    getGraph.mockResolvedValue({ table_rows: mixedRows, total_units: mixedRows.length });
    const { container } = render(<DataView factType={factType} />);
    await screen.findByRole("table");
    const mentionOrder = ["preference", "past-event", "recent-event", "unknown"];
    expect(tableTexts()).toEqual(mentionOrder);
    fireEvent.click(screen.getByRole("button", { name: "timeline" }));
    expect(timelineTexts(container)).toEqual(mentionOrder);
    expect(screen.getByText("noMentionedTime")).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "sortTimeField" }), {
      target: { value: "occurred_start" },
    });
    const occurrenceOrder = ["recent-event", "past-event", "preference", "unknown"];
    expect(timelineTexts(container)).toEqual(occurrenceOrder);
    const undated = container.querySelector('[data-time-group="undated"]')!;
    expect(within(undated as HTMLElement).getByText("noOccurredTime")).toBeTruthy();
    expect(timelineTexts(undated as HTMLElement)).toEqual(["preference", "unknown"]);
    fireEvent.click(screen.getByRole("button", { name: "table" }));
    expect(
      (screen.getByRole("combobox", { name: "sortTimeField" }) as HTMLSelectElement).value
    ).toBe("occurred_start");
    expect(tableTexts()).toEqual(occurrenceOrder);
    fireEvent.click(screen.getByRole("button", { name: "columnOccurred: newestFirst" }));
    expect(tableTexts()).toEqual(["past-event", "recent-event", "preference", "unknown"]);
    fireEvent.click(screen.getByRole("button", { name: "timeline" }));
    expect(timelineTexts(container)).toEqual([
      "past-event",
      "recent-event",
      "preference",
      "unknown",
    ]);
    expect(container.querySelector('[data-time-group="undated"]')).toBe(
      container.querySelector("[data-time-group]:last-child")
    );
    expect(getGraph).toHaveBeenCalledTimes(1);
  }
);

it("keeps controls and cards available when every timestamp on the selected axis is missing", () => {
  const missingRows = [
    { id: "missing", text: "missing", mentioned_at: null, occurred_start: null },
    {
      id: "invalid",
      text: "invalid",
      mentioned_at: "invalid-date",
      occurred_start: "invalid-date",
    },
  ];
  const onMemoryClick = vi.fn();
  const { container } = render(
    <TimelineView data={{}} filteredRows={missingRows} onMemoryClick={onMemoryClick} />
  );
  expect(timelineTexts(container)).toEqual(["missing", "invalid"]);
  expect(screen.getByText("noMentionedTime")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox", { name: "sortTimeField" }), {
    target: { value: "occurred_start" },
  });
  expect(screen.getByText("noOccurredTime")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "columnOccurred: newestFirst" }));
  expect(timelineTexts(container)).toEqual(["missing", "invalid"]);
  fireEvent.click(screen.getByText("missing"));
  expect(onMemoryClick).toHaveBeenCalledWith("missing");
  expect(container.textContent).not.toContain("Invalid Date");
});
