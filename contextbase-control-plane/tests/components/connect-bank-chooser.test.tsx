// @vitest-environment jsdom
import { useState, type ComponentProps } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BankProvider, useBank } from "@/lib/bank-context";
import { ConnectBankChooser } from "@/components/connect-bank-chooser";

const api = vi.hoisted(() => ({ listBanks: vi.fn() }));
vi.mock("@/lib/api", () => ({ client: api }));
vi.mock("next/navigation", () => ({ usePathname: () => "/connect" }));
vi.mock("@/i18n/navigation", () => ({ Link: (props: ComponentProps<"a">) => <a {...props} /> }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string, values?: { shown: number; total: number }) =>
    values ? `${values.shown}/${values.total}` : key,
}));

beforeEach(() => {
  api.listBanks.mockImplementation(
    async ({ q, limit, offset }: { q?: string; limit: number; offset: number }) => {
      const all = Array.from({ length: 61 }, (_, i) => ({ bank_id: `match-${i}` }));
      const banks = q ? all.filter((bank) => bank.bank_id.includes(q)) : all;
      return { banks: banks.slice(offset, offset + limit), total: banks.length };
    }
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function Flow() {
  const { searchBanks } = useBank();
  const [choosing, setChoosing] = useState(true);
  return (
    <>
      <button onClick={() => void searchBanks("match-6")}>header search</button>
      <button onClick={() => setChoosing(!choosing)}>
        {choosing ? "select workspace" : "change workspace"}
      </button>
      {choosing && <ConnectBankChooser />}
    </>
  );
}

it("pages through more than 50 Workspaces and multi-page server search results", async () => {
  render(
    <BankProvider>
      <ConnectBankChooser />
    </BankProvider>
  );
  await screen.findByText("50/61");
  expect(screen.queryByRole("link", { name: /match-60/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "loadMore" }));
  await screen.findByText("61/61");
  expect(screen.getByRole("link", { name: /match-60/ }).getAttribute("href")).toBe(
    "/connect?bank_id=match-60"
  );
  expect(screen.queryByRole("button", { name: "loadMore" })).toBeNull();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "match" } });
  await screen.findByText("50/61");
  fireEvent.click(screen.getByRole("button", { name: "loadMore" }));
  await screen.findByText("61/61");
  expect(api.listBanks).toHaveBeenLastCalledWith({ q: "match", limit: 50, offset: 50 });
});

it("keeps the visible search consistent on remount and shared header searches", async () => {
  render(
    <BankProvider>
      <Flow />
    </BankProvider>
  );
  await screen.findByText("50/61");
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "match-5" } });
  await screen.findByText("11/11");
  fireEvent.click(screen.getByRole("button", { name: "select workspace" }));
  fireEvent.click(screen.getByRole("button", { name: "change workspace" }));
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("match-5");
  fireEvent.click(screen.getByRole("button", { name: "header search" }));
  await waitFor(() =>
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("match-6")
  );
  await screen.findByText("2/2");
  expect(screen.queryByRole("link", { name: /match-5/ })).toBeNull();
});
