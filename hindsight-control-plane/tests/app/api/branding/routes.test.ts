import { NextRequest } from "next/server";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("@/lib/hindsight-client", () => ({
  dataplaneBankUrl: (bank: string, suffix: string) =>
    "http://dataplane/v1/default/banks/" + encodeURIComponent(bank) + suffix,
  getDataplaneHeaders: () => ({ Authorization: "Bearer internal-fixture" }),
}));
import { GET as exportBank } from "@/app/api/banks/[bankId]/export/route";
import { POST as importBank } from "@/app/api/banks/[bankId]/import/route";
import { POST as cloneBank } from "@/app/api/banks/[bankId]/clone/route";
import { GET as timeseries } from "@/app/api/stats/[agentId]/memories-timeseries/route";
import { POST as retainFile } from "@/app/api/files/retain/route";
const upstream = vi.fn();
beforeEach(() => {
  upstream.mockReset();
  vi.stubGlobal("fetch", upstream);
});
afterEach(() => vi.unstubAllGlobals());
const bank = { params: Promise.resolve({ bankId: "customer-hindsight" }) };
const routes = [
  {
    name: "export",
    call: () => exportBank(new NextRequest("http://ui/api/banks/bank/export"), bank),
  },
  {
    name: "import",
    call: () =>
      importBank(
        new NextRequest("http://ui/api/banks/bank/import", {
          method: "POST",
          body: JSON.stringify({ name: "customer hindsight" }),
        }),
        bank
      ),
  },
  {
    name: "clone",
    call: () =>
      cloneBank(
        new NextRequest("http://ui/api/banks/bank/clone", {
          method: "POST",
          body: JSON.stringify({ target_bank_id: "customer-hindsight" }),
        }),
        bank
      ),
  },
  {
    name: "timeseries",
    call: () =>
      timeseries(new NextRequest("http://ui/api/stats/bank/memories-timeseries"), {
        params: Promise.resolve({ agentId: "customer-hindsight" }),
      }),
  },
  {
    name: "file upload",
    call: () => {
      const body = new FormData();
      body.set("request", JSON.stringify({ bank_id: "customer-hindsight" }));
      body.set("files", new Blob(["customer hindsight bytes"]), "hindsight.txt");
      return retainFile(new NextRequest("http://ui/api/files/retain", { method: "POST", body }));
    },
  },
];
it.each(routes)("$name preserves service errors, status and validation input", async ({ call }) => {
  upstream.mockResolvedValue(
    Response.json(
      {
        detail: [
          { msg: "Invalid bank 'HINDSIGHT-review': access denied", input: "customer hindsight" },
        ],
      },
      { status: 422 }
    )
  );
  const response = await call();
  expect(response.status).toBe(422);
  const body = await response.json();
  expect(body.detail[0].msg).toBe("Invalid bank 'HINDSIGHT-review': access denied");
  expect(body.detail[0].input).toBe("customer hindsight");
});
it.each(routes)("$name preserves successful customer data", async ({ call, name }) => {
  const data = { message: "customer hindsight", error: "customer Hindsight", content: "hindsight" };
  upstream.mockResolvedValue(Response.json(data));
  const response = await call();
  await expect(response.json()).resolves.toEqual(data);
  expect(upstream.mock.calls[0][0]).toContain("customer-hindsight");
  if (name === "file upload") {
    const form = upstream.mock.calls[0][1].body as FormData;
    const file = form.get("files") as File;
    expect(file.name).toBe("hindsight.txt");
    await expect(file.text()).resolves.toBe("customer hindsight bytes");
  }
});

it.each(routes)("$name keeps proxy exceptions internal", async ({ call }) => {
  const error = new Error("connection failed in /srv/hindsight/private-config");
  upstream.mockRejectedValue(error);
  const response = await call();
  expect(response.status).toBe(500);
  expect(await response.text()).not.toContain(error.message);
});
