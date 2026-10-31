// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/bank-context", () => ({ useBank: () => ({ currentBank: "demo" }) }));
const recall = vi.fn();
vi.mock("@/lib/api", () => ({ client: { recall: (...args: unknown[]) => recall(...args) } }));
vi.mock("@/components/memory-detail-modal", () => ({ MemoryDetailModal: () => null }));
const { SearchDebugView } = await import("@/components/search-debug-view");
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("keeps recall results visible and resets diagnostics for the next query", async () => {
  recall.mockResolvedValue({
    results: [{ id: "fact-1", text: "Retrieved fact", scores: { final: 0.8 } }],
    trace: { summary: { total_duration_seconds: 0.1, total_nodes_visited: 1 } },
  });
  render(<SearchDebugView />);
  fireEvent.change(screen.getByPlaceholderText("queryPlaceholder"), {
    target: { value: "Question" },
  });
  fireEvent.click(screen.getByRole("button", { name: "recall" }));
  expect(await screen.findByText("Retrieved fact")).toBeTruthy();
  expect(screen.getByText("diagnostics").closest("details")!.open).toBe(false);
  expect(screen.queryByRole("button", { name: "viewJson" })).toBeNull();
  fireEvent.click(screen.getByText("diagnostics"));
  fireEvent.click(await screen.findByRole("button", { name: "viewJson" }));
  expect(screen.getByText("rawResponse")).toBeTruthy();
  expect(screen.getByText("Retrieved fact", { selector: "p" })).toBeTruthy();
  expect(recall.mock.calls[0][0].trace).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "recall" }));
  await waitFor(() => expect(screen.getByText("diagnostics").closest("details")!.open).toBe(false));
});
