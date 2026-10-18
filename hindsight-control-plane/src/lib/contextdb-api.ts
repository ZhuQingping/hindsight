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
export interface ContextDBKey {
  key_id: string;
  user_id: string;
  name: string;
  display_key: string | null;
  authorization: KeyAuthorization;
  version: number;
  created_at: string;
  last_used_at: string | null;
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
  latest_operation_id: string | null;
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
export interface WorkspaceOperation {
  operation_id: string;
  workspace_id: string;
  state: string;
  error_code?: string | null;
}

function requestMessage(kind: "unknown" | "unavailable" | "conflict"): string {
  const chinese = typeof document !== "undefined" && document.documentElement.lang.startsWith("zh");
  const messages = chinese
    ? {
        unknown: "结果未知，请先刷新核对资源再重试。不要自动重复创建成员或 API Key。",
        unavailable: "暂时无法连接管理服务，请刷新后重试。",
        conflict: "记录已被修改，请关闭编辑窗口，刷新后重新确认，不能直接覆盖。",
      }
    : {
        unknown:
          "Result unknown. Refresh and inspect the resource before retrying; do not automatically create another member or key.",
        unavailable: "Unable to reach the management service. Refresh to retry.",
        conflict: "This record changed. Close the editor and refresh before retrying.",
      };
  return messages[kind];
}

export async function contextDBRequest<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    version?: number;
    etag?: string;
    signal?: AbortSignal;
    idempotencyKey?: string;
  } = {}
): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (options.etag !== undefined) headers.set("If-Match", options.etag);
  else if (options.version !== undefined) headers.set("If-Match", `"${options.version}"`);
  if (options.idempotencyKey) headers.set("Idempotency-Key", options.idempotencyKey);
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
    const error = await response.json().catch(() => ({}));
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
  return response.status === 204 ? (undefined as T) : response.json();
}

/** getRandomValues also works on remote HTTP UIs, unlike randomUUID. */
export function managementRequestId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
    value.toString(16).padStart(2, "0")
  ).join("");
}

/** Keep the same request ID on a retry; a timeout never starts a second operation. */
export async function workspaceMutation(
  path: string,
  method: "POST" | "DELETE",
  idempotencyKey: string,
  body?: { name: string; description?: string },
  signal?: AbortSignal,
  etag?: string
): Promise<WorkspaceOperation> {
  if (method === "DELETE" && !/^"[0-9a-f]{32}:[1-9][0-9]*"$/.test(etag ?? ""))
    throw new Error("Workspace deletion requires the original identity-bound ETag.");
  const intent: WorkspaceIntent = {
    idempotency_key: idempotencyKey,
    path,
    method,
    ...(etag ? { etag } : {}),
    created_at:
      workspaceIntents().find((item) => item.idempotency_key === idempotencyKey)?.created_at ??
      Date.now(),
    ...(body ? { raw_body: JSON.stringify(body) } : {}),
  };
  const previous = workspaceIntents().find((item) => item.idempotency_key === idempotencyKey);
  if (
    previous &&
    (previous.path !== path ||
      previous.method !== method ||
      previous.raw_body !== intent.raw_body ||
      previous.etag !== intent.etag)
  )
    throw new Error("An existing idempotency key must keep the same original request.");
  if (previous?.operation_id) {
    const operation = await waitForWorkspaceOperation(previous.operation_id, signal);
    removeWorkspaceIntent(idempotencyKey);
    return operation;
  }
  if (previous && !canReplayWorkspaceIntent(previous))
    throw new Error(
      "Saved operation expired. Refresh and inspect the resource before starting a new operation."
    );
  saveWorkspaceIntent(intent);
  let operation: WorkspaceOperation;
  try {
    operation = await contextDBRequest<WorkspaceOperation>(path, {
      method,
      body,
      idempotencyKey,
      etag,
      signal,
    });
  } catch (error) {
    // A rejected first submission never became a background operation. Keep
    // uncertain earlier attempts and network/5xx failures recoverable, but do
    // not turn an ordinary duplicate-name error into a permanent pending row.
    if (!previous && error instanceof ContextDBError && error.status >= 400 && error.status < 500)
      removeWorkspaceIntent(idempotencyKey);
    throw error;
  }
  saveWorkspaceIntent({
    ...intent,
    operation_id: operation.operation_id,
    workspace_id: operation.workspace_id,
  });
  const completed =
    operation.state === "pending" || operation.state === "running"
      ? await waitForWorkspaceOperation(operation.operation_id, signal)
      : operation;
  if (completed.state !== "succeeded")
    throw new Error(completed.error_code || "Workspace operation failed");
  removeWorkspaceIntent(idempotencyKey);
  return completed;
}

export async function waitForWorkspaceOperation(
  operationId: string,
  signal?: AbortSignal
): Promise<WorkspaceOperation> {
  const deadline = Date.now() + 120000;
  let attempt = 0;
  while (true) {
    await operationDelay(Math.min(1000 * 2 ** attempt++, 5000), signal);
    const operation = await contextDBRequest<WorkspaceOperation>(`/operations/${operationId}`, {
      signal,
    });
    if (operation.state === "failed")
      throw new Error(operation.error_code || "Workspace operation failed");
    if (operation.state === "succeeded") return operation;
    if (Date.now() >= deadline)
      throw new Error("Workspace operation is still running. Check its progress before retrying.");
  }
}

export interface WorkspaceIntent {
  idempotency_key: string;
  path: string;
  method: "POST" | "DELETE";
  raw_body?: string;
  etag?: string;
  operation_id?: string;
  workspace_id?: string;
  created_at?: number;
}
// Server history is retained at least24h after its terminal update. Unknown
// browser writes expire conservatively24h after first submission, never later.
export function canReplayWorkspaceIntent(intent: WorkspaceIntent): boolean {
  return (
    typeof intent.created_at === "number" &&
    Number.isFinite(intent.created_at) &&
    Date.now() >= intent.created_at &&
    Date.now() - intent.created_at < 24 * 60 * 60 * 1000
  );
}
const INTENTS_KEY = "contextdb-workspace-intents";
/** The only persisted values are operation IDs and the original non-secret request. */
export function workspaceIntents(): WorkspaceIntent[] {
  if (typeof sessionStorage === "undefined") return [];
  try {
    const parsed: unknown = JSON.parse(sessionStorage.getItem(INTENTS_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item): item is WorkspaceIntent => {
      if (!item || typeof item !== "object" || !/^[A-Za-z0-9_-]{1,128}$/.test(item.idempotency_key))
        return false;
      if (item.method === "DELETE")
        return (
          /^\/workspaces\/[a-z0-9][a-z0-9_]{0,53}$/.test(item.path) &&
          item.raw_body === undefined &&
          /^"[0-9a-f]{32}:[1-9][0-9]*"$/.test(item.etag ?? "")
        );
      if (
        item.method !== "POST" ||
        item.path !== "/workspaces" ||
        typeof item.raw_body !== "string"
      )
        return false;
      try {
        const body = JSON.parse(item.raw_body);
        return (
          body &&
          typeof body.name === "string" &&
          Object.keys(body).every((key) => ["name", "description"].includes(key))
        );
      } catch {
        return false;
      }
    });
  } catch {
    return [];
  }
}
export function saveWorkspaceIntent(intent: WorkspaceIntent): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(
    INTENTS_KEY,
    JSON.stringify([
      ...workspaceIntents().filter((item) => item.idempotency_key !== intent.idempotency_key),
      { ...intent, created_at: intent.created_at ?? Date.now() },
    ])
  );
}
export function removeWorkspaceIntent(id: string): void {
  if (typeof sessionStorage === "undefined") return;
  sessionStorage.setItem(
    INTENTS_KEY,
    JSON.stringify(workspaceIntents().filter((item) => item.idempotency_key !== id))
  );
}

/** Abort stops this browser wait only; the accepted server operation continues. */
export function operationDelay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const aborted = () => {
      clearTimeout(timer);
      reject(new DOMException("Stopped", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", aborted);
      resolve();
    }, ms);
    if (signal?.aborted) aborted();
    else signal?.addEventListener("abort", aborted, { once: true });
  });
}

/** Explicit user action only: replay may restart a failed lifecycle operation. */
export async function replayWorkspaceIntent(
  intent: WorkspaceIntent,
  signal?: AbortSignal
): Promise<WorkspaceOperation> {
  if (!canReplayWorkspaceIntent(intent))
    throw new Error(
      "Saved operation expired. Refresh and inspect the resource before starting a new operation."
    );
  // Preserve the original deadline when explicitly retrying a known failure.
  saveWorkspaceIntent({ ...intent, operation_id: undefined });
  return workspaceMutation(
    intent.path,
    intent.method,
    intent.idempotency_key,
    intent.raw_body ? JSON.parse(intent.raw_body) : undefined,
    signal,
    intent.etag
  );
}
