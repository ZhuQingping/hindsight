import { describe, expect, it } from "vitest";
import { formatMemoryTime, sortMemoriesByTime } from "@/lib/memory-time";

describe("memory timestamps", () => {
  it("compares actual instants, keeps equal times stable, puts absent dates last, and leaves input intact", () => {
    const rows = [
      { id: "missing", time: null },
      { id: "newer", time: "2026-10-27T08:32:00Z" },
      { id: "invalid", time: "not-a-date" },
      { id: "older", time: "2026-10-27T16:31:00+08:00" },
      { id: "equal", time: "2026-10-27T08:32:00Z" },
    ];
    expect(sortMemoriesByTime(rows, "time", "desc").map((r) => r.id)).toEqual([
      "newer",
      "equal",
      "older",
      "missing",
      "invalid",
    ]);
    expect(sortMemoriesByTime(rows, "time", "asc").map((r) => r.id)).toEqual([
      "older",
      "newer",
      "equal",
      "missing",
      "invalid",
    ]);
    expect(rows[0].id).toBe("missing");
  });

  it.each(["zh-CN", "zh-TW", "en"])("shows date, hour and minute in %s", (locale) => {
    const date = new Date(2026, 9, 27, 14, 5, 59);
    const result = formatMemoryTime(date.toISOString(), locale);
    expect(result).toContain("2026");
    expect(result).toContain("14:05");
    expect(result).not.toContain("14:05:59");
  });

  it("leaves missing or invalid times blank", () => {
    expect(formatMemoryTime(null, "en")).toBeNull();
    expect(formatMemoryTime(undefined, "en")).toBeNull();
    expect(formatMemoryTime("invalid", "en")).toBeNull();
  });
});
