// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
}));
vi.mock("@/lib/bank-context", () => ({
  useBank: () => ({ currentBank: "typography-test" }),
}));

const reflect = vi.fn();
vi.mock("@/lib/api", () => ({
  client: { reflect: (...args: unknown[]) => reflect(...args) },
}));
vi.mock("@/components/memory-detail-modal", () => ({
  MemoryDetailModal: () => null,
}));
vi.mock("@/components/mental-model-detail-modal", () => ({
  MentalModelDetailModal: () => null,
}));

const { ThinkView } = await import("@/components/think-view");

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("preserves an answer table and its scroll position when the query changes", async () => {
  reflect.mockResolvedValue({
    text: "| Instrument | Preparation |\n| --- | --- |\n| Telescope | Align the finder |",
  });
  render(<ThinkView />);
  const query = screen.getByPlaceholderText("queryPlaceholder");
  fireEvent.change(query, { target: { value: "How should the club prepare?" } });
  fireEvent.click(screen.getByRole("button", { name: "reflect" }));

  const table = await screen.findByRole("table");
  const scroller = table.parentElement!;
  // jsdom has no layout. Browser verification covers actual overflow; this
  // guards the DOM identity that owns the user's scroll position.
  scroller.scrollLeft = 140;
  fireEvent.change(query, { target: { value: "What happens next?" } });

  expect(screen.getByRole("table")).toBe(table);
  expect(screen.getByRole("table").parentElement).toBe(scroller);
  expect(scroller.scrollLeft).toBe(140);
  expect(reflect).toHaveBeenCalledTimes(1);
});

it("keeps the answer and sources visible while diagnostics are collapsed", async () => {
  reflect.mockResolvedValue({
    text: "Answer with evidence",
    based_on: { memories: [{ id: "fact-1", text: "Source evidence", type: "world" }] },
    trace: { tool_calls: [], llm_calls: [] },
  });
  render(<ThinkView />);
  fireEvent.change(screen.getByPlaceholderText("queryPlaceholder"), {
    target: { value: "Question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "reflect" }));
  expect(await screen.findByText("Answer with evidence")).toBeTruthy();
  expect(screen.getByText("Source evidence")).toBeTruthy();
  const disclosure = screen.getByText("diagnostics").closest("details")!;
  expect(disclosure.open).toBe(false);
  expect(screen.queryByRole("button", { name: "viewJson" })).toBeNull();
  fireEvent.click(screen.getByText("diagnostics"));
  fireEvent.click(await screen.findByRole("button", { name: "viewJson" }));
  expect(screen.getByText("rawResponseTitle")).toBeTruthy();
  expect(screen.getByText("basedOnTitle")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "reflect" }));
  await waitFor(() => expect(screen.getByText("diagnostics").closest("details")!.open).toBe(false));
  expect(screen.queryByText("rawResponseTitle")).toBeNull();
});
