import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

vi.mock("@/lib/contextbase-client", () => ({
  DATAPLANE_URL: "http://private-dataplane.invalid",
  dataplaneBankUrl: (bankId: string, suffix: string) =>
    `http://private-dataplane.invalid/v1/default/banks/${encodeURIComponent(bankId)}${suffix}`,
  getDataplaneHeaders: () => ({ Authorization: "Bearer synthetic-private-key" }),
}));

import { POST as upload } from "@/app/api/files/retain/route";
import { GET as download } from "@/app/api/files/download/route";

afterEach(() => vi.unstubAllGlobals());

it.each([200, 422, 503])(
  "keeps upload status %i and hides only server diagnostics",
  async (status) => {
    const data = { detail: "Hindsight customer input", debug: "/internal/hindsight/server.py" };
    const fetchMock = vi.fn(async () => Response.json(data, { status }));
    vi.stubGlobal("fetch", fetchMock);
    const form = new FormData();
    form.set("request", JSON.stringify({ bank_id: "team/one" }));
    form.set("files", new Blob(["customer file"]), "file.txt");
    const response = await upload(
      new NextRequest("http://console.test/api/files/retain", {
        method: "POST",
        body: form,
      })
    );
    expect(response.status).toBe(status);
    expect(await response.json()).toEqual(status >= 500 ? { detail: "Failed" } : data);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://private-dataplane.invalid/v1/default/banks/team%2Fone/files/retain",
      expect.objectContaining({ headers: { Authorization: "Bearer synthetic-private-key" } })
    );
    expect(response.headers.get("authorization")).toBeNull();
  }
);

it("does not expose an HTML server error through file download", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("<pre>Hindsight internal trace</pre>", {
          status: 502,
          headers: { "X-Internal-Service": "Hindsight", Authorization: "private" },
        })
    )
  );
  const response = await download(
    new NextRequest(
      "http://console.test/api/files/download?path=/v1/default/files/download/file.zip"
    )
  );
  expect(response.status).toBe(502);
  expect(await response.json()).toEqual({ detail: "Failed" });
  expect(response.headers.get("x-internal-service")).toBeNull();
});

it("streams successful downloads without rewriting customer content", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("customer Hindsight bytes", {
          headers: { "Content-Disposition": 'attachment; filename="customer.zip"' },
        })
    )
  );
  const response = await download(
    new NextRequest(
      "http://console.test/api/files/download?path=/v1/default/files/download/file.zip"
    )
  );
  expect(response.status).toBe(200);
  expect(await response.text()).toBe("customer Hindsight bytes");
  expect(response.headers.get("content-disposition")).toBe('attachment; filename="customer.zip"');
});
