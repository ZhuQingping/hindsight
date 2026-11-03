// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ProductRuntime } from "@/components/product-runtime";
import { Brand } from "@/components/brand";
import { productFetch } from "@/lib/product-fetch";
import messages from "@/messages/en.json";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.contextdbName;
});
it("keeps the old tab input without resubmitting when the running product changes", async () => {
  const send = vi.fn();
  const fetch = vi.fn(async () =>
    Response.json({ product_config_version: 1, contextdb_name: "contextdb" })
  );
  vi.stubGlobal("fetch", fetch);
  render(
    <ProductRuntime
      name="contextbase"
      locale="en"
      localeNotice={messages.productRuntime.localeNotice}
    >
      <Brand />
      <form onSubmit={send}>
        <input aria-label="draft" defaultValue="original operation body" />
        <button>Submit</button>
      </form>
    </ProductRuntime>
  );
  fireEvent.change(screen.getByLabelText("draft"), { target: { value: "edited unsent input" } });
  await waitFor(() =>
    expect(screen.getByRole("alert").textContent).toContain("Preserve your input")
  );
  expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe("edited unsent input");
  expect(screen.getByLabelText("contextbase")).toBeTruthy();
  expect(send).not.toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledTimes(1);
});
it("stamps the original rendered brand and preserves caller headers", async () => {
  document.documentElement.dataset.contextdbName = "contextdb";
  const fetch = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
    Response.json({ ok: true })
  );
  vi.stubGlobal("fetch", fetch);
  await productFetch("/api/banks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "original-operation",
  });
  const init = fetch.mock.calls[0][1]!;
  expect(new Headers(init.headers).get("X-Product-Name")).toBe("contextdb");
  expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
  expect(init.body).toBe("original-operation");
});
it("explains the English fallback for retained locale choices", () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => Response.json({ product_config_version: 1, contextdb_name: "contextdb" }))
  );
  render(
    <ProductRuntime
      name="contextdb"
      locale="fr"
      localeNotice={messages.productRuntime.localeNotice}
    >
      <Brand />
    </ProductRuntime>
  );
  expect(screen.getByRole("status").textContent).toContain("English is shown");
  expect(screen.getByLabelText("contextdb")).toBeTruthy();
});
