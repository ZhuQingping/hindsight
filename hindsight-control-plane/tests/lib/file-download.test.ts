import { describe, expect, it } from "vitest";
import { isNativeFileDownloadPath, nativeFileDownloadPath } from "@/lib/file-download";

describe("native file download paths", () => {
  it("uses opaque storage keys even when the store returns a signed absolute URL", () => {
    expect(
      nativeFileDownloadPath({
        storage_key: "tenants/public/banks/team%2Fone/exports/导出.zip",
        download_url: "https://object-store.invalid/bucket/file?signature=private",
      })
    ).toBe(
      "/v1/default/files/download/tenants/public/banks/team%252Fone/exports/%E5%AF%BC%E5%87%BA.zip"
    );
  });
  it("retains an already native URL", () => {
    expect(
      nativeFileDownloadPath({
        download_url: "/v1/default/files/download/tenants/public/export.zip",
      })
    ).toBe("/v1/default/files/download/tenants/public/export.zip");
  });
  it.each([
    "https://untrusted.invalid/file",
    "/v1/default/banks",
    "/v1/default/files/download/../banks",
    "/v1/default/files/download/%2e%2e/banks",
    "/v1/default/files/download/file?redirect=elsewhere",
    "/v1/default/files/download/",
    "/v1/default/files/download/\\evil",
  ])("refuses unsafe download route %s", (path) => {
    expect(isNativeFileDownloadPath(path)).toBe(false);
    expect(nativeFileDownloadPath({ download_url: path })).toBeNull();
  });
  it("does not normalize dot components in opaque keys into another API route", () => {
    expect(nativeFileDownloadPath({ storage_key: "../banks" })).toBeNull();
  });
});
