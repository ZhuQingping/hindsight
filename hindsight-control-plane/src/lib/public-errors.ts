/** Error-boundary filtering only; never apply this to successful data or file bytes. */
export function publicErrorMessage(message: string): string {
  return /hindsight/i.test(message)
    ? "The service could not complete the operation. Contact your service administrator."
    : message;
}

/** Preserve validation inputs and business fields; inspect only diagnostic fields. */
export function publicErrorPayload<T>(payload: T): T {
  if (typeof payload === "string") return publicErrorMessage(payload) as T;
  if (Array.isArray(payload)) return payload.map(publicErrorPayload) as T;
  if (!payload || typeof payload !== "object") return payload;
  const result = { ...payload } as Record<string, unknown>;
  for (const field of [
    "error",
    "message",
    "msg",
    "detail",
    "details",
    "errors",
    "error_message",
    "upstream",
  ]) {
    if (field in result) result[field] = publicErrorPayload(result[field]);
  }
  return result as T;
}
