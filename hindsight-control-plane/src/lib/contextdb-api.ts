import { withBasePath } from "@/lib/base-path";

export interface ContextDBUser {
  user_id: string;
  name: string;
  status: "active" | "disabled" | "deleted";
  version: number;
  created_at: string;
}
export type KeyPermission = "read" | "read_write";
export type KeyAuthorization =
  | {
      mode: "selected";
      workspaces: {
        bank_id: string;
        workspace_id: string;
        permission: KeyPermission;
        workspace_name?: string | null;
      }[];
    }
  | { mode: "all"; permission: KeyPermission };
export type KeyAuthorizationInput =
  | {
      mode: "selected";
      workspaces: { bank_id: string; workspace_id: string; permission: KeyPermission }[];
    }
  | { mode: "all"; permission: KeyPermission };
export interface ContextDBKeyEditable {
  key_id: string;
  user_id: string;
  name: string;
  display_key?: string | null;
  authorization: KeyAuthorization;
  version: number;
  created_at: string;
}
export interface ContextDBKeyMetadata extends ContextDBKeyEditable {
  last_used_at: string | null;
}
export interface ContextDBKeyIssued extends ContextDBKeyEditable {
  secret: string;
}
export interface ContextDBWorkspace {
  workspace_id: string;
  bank_id: string;
  etag: string;
  name: string;
  description: string;
  state: string;
  version: number;
  created_at: string;
}
export class ContextDBError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public request_id: string | null
  ) {
    super(message);
    this.name = "ContextDBError";
  }
}
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
function requestMessage(kind: "unknown" | "unavailable" | "conflict"): string {
  const chinese = typeof document !== "undefined" && document.documentElement.lang.startsWith("zh");
  const messages = chinese
    ? {
        unknown: "结果未知，请先刷新核对资源再重试。不要自动重复创建、删除或修改资源。",
        unavailable: "暂时无法连接管理服务，请刷新后重试。",
        conflict: "记录已被修改，请关闭编辑窗口，刷新后重新确认，不能直接覆盖。",
      }
    : {
        unknown:
          "Result unknown. Refresh and inspect the resource before retrying; do not automatically repeat a create, delete, or update request.",
        unavailable: "Unable to reach the management service. Refresh to retry.",
        conflict: "This record changed. Close the editor and refresh before retrying.",
      };
  return messages[kind];
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  version?: number;
  etag?: string;
  signal?: AbortSignal;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function contextDBRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return requestJSON(path, options);
}

async function requestJSON<T>(
  path: string,
  options: RequestOptions,
  validCreation?: (data: unknown, status: number) => boolean
): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.etag !== undefined) headers.set("If-Match", options.etag);
  else if (options.version !== undefined) headers.set("If-Match", `"${options.version}"`);
  const response = await fetch(withBasePath(`/api/contextdb${path}`), {
    method: options.method || "GET",
    headers,
    credentials: "same-origin",
    cache: "no-store",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  }).catch((error: unknown) => {
    if (options.signal?.aborted) throw error;
    throw new ContextDBError(
      requestMessage(options.method && options.method !== "GET" ? "unknown" : "unavailable"),
      0,
      "connection_unknown",
      null
    );
  });
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    const error = isObject(payload) ? payload : {};
    const message =
      typeof error.error === "string"
        ? error.error
        : typeof error.detail === "string"
          ? error.detail
          : typeof error.message === "string"
            ? error.message
            : `Request failed (${response.status})`;
    throw new ContextDBError(
      response.status === 412
        ? requestMessage("conflict")
        : response.status >= 500 && options.method && options.method !== "GET"
          ? `${message} ${requestMessage("unknown")}`
          : message,
      response.status,
      typeof error.code === "string" ? error.code : "request_failed",
      typeof error.request_id === "string" ? error.request_id : response.headers.get("X-Request-ID")
    );
  }
  if (response.status === 204 && !validCreation) return undefined as T;
  try {
    const data: unknown = await response.json();
    if (validCreation && !validCreation(data, response.status))
      throw new Error("Invalid creation response");
    return data as T;
  } catch {
    // The server may have committed even when its success body is lost or invalid.
    throw new ContextDBError(
      requestMessage(options.method && options.method !== "GET" ? "unknown" : "unavailable"),
      0,
      "response_unknown",
      response.headers.get("X-Request-ID")
    );
  }
}

/** Never retry a write here; inspect the resource after an uncertain response. */
export function workspaceMutation<Method extends "POST" | "DELETE">(
  path: string,
  method: Method,
  body?: { name: string; description?: string },
  signal?: AbortSignal,
  etag?: string
): Promise<Method extends "POST" ? ContextDBWorkspace : void> {
  if (method === "DELETE" && !/^"[0-9a-f]{32}:[1-9][0-9]*"$/.test(etag ?? ""))
    throw new Error("Workspace deletion requires the original identity-bound ETag.");
  const bankId = body?.name.normalize("NFKC").trim().toLowerCase();
  return requestJSON(
    path,
    { method, body, signal, etag },
    method === "POST"
      ? (data, status) => {
          // A parseable JSON body used to be accepted as a resource. Verify the
          // submitted target and its original identity before closing or navigating.
          return (
            status === 201 &&
            isObject(data) &&
            typeof data.workspace_id === "string" &&
            /^[0-9a-f]{32}$/.test(data.workspace_id) &&
            typeof data.bank_id === "string" &&
            data.bank_id === bankId &&
            data.state === "active" &&
            typeof data.version === "number" &&
            Number.isSafeInteger(data.version) &&
            data.version > 0 &&
            data.etag === `"${data.workspace_id}:${data.version}"`
          );
        }
      : undefined
  );
}

/** Verify the created identity before closing the member form or reporting success. */
export function createContextDBUser(
  body: { name: string },
  signal?: AbortSignal
): Promise<ContextDBUser> {
  // Match Python str.strip: it includes NEL and information separators,
  // while ECMAScript trim also removes a BOM that the backend preserves.
  const name = body.name
    .normalize("NFKC")
    // eslint-disable-next-line no-control-regex -- Python strips these information separators.
    .replace(/^[\p{White_Space}\u001c-\u001f]+|[\p{White_Space}\u001c-\u001f]+$/gu, "");
  return requestJSON(
    "/users",
    { method: "POST", body, signal },
    (data, status) =>
      status === 201 &&
      isObject(data) &&
      typeof data.user_id === "string" &&
      /^[0-9a-f]{32}$/.test(data.user_id) &&
      data.name === name &&
      data.status === "active" &&
      typeof data.version === "number" &&
      Number.isSafeInteger(data.version) &&
      data.version > 0 &&
      typeof data.created_at === "string" &&
      !Number.isNaN(Date.parse(data.created_at))
  );
}

export function createContextDBKey(
  userId: string,
  body: { name: string; authorization: KeyAuthorizationInput },
  signal?: AbortSignal
): Promise<ContextDBKeyIssued> {
  return requestJSON(
    `/users/${encodeURIComponent(userId)}/keys`,
    { method: "POST", body, signal },
    (data, status) =>
      // A missing one-time secret cannot be recovered by reading Key metadata.
      // Keep it in the uncertain-result path instead of reporting success.
      status === 201 &&
      isObject(data) &&
      typeof data.key_id === "string" &&
      /^[0-9a-f]{32}$/.test(data.key_id) &&
      data.user_id === userId &&
      typeof data.secret === "string" &&
      data.secret.trim().length > 0
  );
}

/** A transport failure cannot establish that a write was rolled back. */
export function contextDBWriteOutcome(error: unknown): "unknown" | "conflict" | "failed" {
  if (!(error instanceof ContextDBError)) return "failed";
  if (error.status === 412) return "conflict";
  return error.status === 0 || error.status >= 500 ? "unknown" : "failed";
}
