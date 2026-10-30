export type MemoryDisplayTimeField = "mentioned_at" | "occurred_start";

export type MemorySortOrder = "asc" | "desc";

/** Keep missing/invalid timestamps last in either direction without mutating API data. */
export function sortMemoriesByTime<T>(
  rows: readonly T[],
  field: keyof T,
  order: MemorySortOrder
): T[] {
  const timestamp = (row: T) => {
    const value = row[field];
    return typeof value === "string" ? Date.parse(value) : NaN;
  };
  return [...rows].sort((a, b) => {
    const left = timestamp(a);
    const right = timestamp(b);
    if (!Number.isFinite(left)) return Number.isFinite(right) ? 1 : 0;
    if (!Number.isFinite(right)) return -1;
    return (left - right) * (order === "asc" ? 1 : -1);
  });
}

/** Show the stored instant in the browser's local timezone, to minute precision. */
export function formatMemoryTime(value: string | null | undefined, locale: string): string | null {
  if (!value || !Number.isFinite(Date.parse(value))) return null;
  return new Date(value).toLocaleString(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
