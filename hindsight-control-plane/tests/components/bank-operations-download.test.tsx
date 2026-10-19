// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { BankOperationsView } from "@/components/bank-operations-view";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/bank-context", () => ({ useBank: () => ({ currentBank: "example" }) }));
vi.mock("@/components/document-chunk-modal", () => ({ DocumentChunkModal: () => null }));
const operation = {
  id: "export-test",
  operation_id: "export-test",
  task_type: "export_documents",
  operation_type: "export_documents",
  status: "completed",
  created_at: "2026-10-18T00:00:00Z",
  items_count: 1,
  result_metadata: { storage_key: "exports/example/fixture.zip", filename: "fixture.zip" },
};
vi.mock("@/lib/api", () => ({
  client: {
    listOperations: async () => ({ operations: [operation], total: 1 }),
    getOperationStatus: async () => operation,
  },
}));
const fetchMock = vi.fn();
const createURL = vi.fn(() => "blob:archive");
const revokeURL = vi.fn();
let anchorClick: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  document.documentElement.dataset.contextdbName = "agentstratum";
  vi.stubEnv("NEXT_PUBLIC_BASE_PATH", "/brand-ui");
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = createURL;
      static revokeObjectURL = revokeURL;
    }
  );
  anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  delete document.documentElement.dataset.contextdbName;
});
async function download() {
  render(<BankOperationsView />);
  fireEvent.click(await screen.findByText("operationType.exportDocuments"));
  fireEvent.click(await screen.findByRole("button", { name: "action.download" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(
    "/brand-ui/api/files/download?path=%2Fv1%2Fdefault%2Ffiles%2Fdownload%2Fexports%2Fexample%2Ffixture.zip"
  );
  expect(new Headers(init.headers).get("X-Product-Name")).toBe("agentstratum");
}
it("saves the real archive bytes after the operation-detail Download button succeeds", async () => {
  const bytes = new Blob(["PK archive"]);
  fetchMock.mockResolvedValue(new Response(bytes));
  await download();
  await waitFor(() => expect(anchorClick).toHaveBeenCalledOnce());
  expect(createURL).toHaveBeenCalledOnce();
  expect(anchorClick.mock.instances[0].download).toBe("fixture.zip");
  expect(revokeURL).toHaveBeenCalledWith("blob:archive");
});
it("shows a stale-tab refusal and never saves the error response as an archive", async () => {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify({ error: "PRODUCT_NAME_STALE" }), { status: 409 })
  );
  await download();
  expect((await screen.findByRole("alert")).textContent).toBe("PRODUCT_NAME_STALE");
  expect(createURL).not.toHaveBeenCalled();
  expect(anchorClick).not.toHaveBeenCalled();
  expect(fetchMock).toHaveBeenCalledOnce();
});
