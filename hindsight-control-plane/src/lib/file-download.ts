const FILE_DOWNLOAD_PREFIX = "/v1/default/files/download/";

interface ExportFileMetadata {
  [key: string]: unknown;
  storage_key?: unknown;
  download_url?: unknown;
}

/** Only a canonical API-relative file route may receive the server credential. */
export function isNativeFileDownloadPath(path: string): boolean {
  if (!path.startsWith(FILE_DOWNLOAD_PREFIX) || path.length === FILE_DOWNLOAD_PREFIX.length) {
    return false;
  }
  // eslint-disable-next-line no-control-regex -- URL/header control bytes are intentionally rejected.
  if (/[\\\u0000-\u0020\u007f?#]/.test(path)) return false;
  const url = new URL(path, "http://dataplane.invalid");
  return url.origin === "http://dataplane.invalid" && url.pathname === path;
}

/**
 * Object storage exports can return an absolute signed URL. The UI already has
 * an authenticated native download route: use the operation's storage key so
 * private object-store topology and credentials stay behind the server proxy.
 */
export function nativeFileDownloadPath(metadata?: ExportFileMetadata | null): string | null {
  if (typeof metadata?.storage_key === "string" && metadata.storage_key) {
    const path =
      FILE_DOWNLOAD_PREFIX + metadata.storage_key.split("/").map(encodeURIComponent).join("/");
    return isNativeFileDownloadPath(path) ? path : null;
  }
  if (
    typeof metadata?.download_url === "string" &&
    isNativeFileDownloadPath(metadata.download_url)
  ) {
    return metadata.download_url;
  }
  return null;
}
