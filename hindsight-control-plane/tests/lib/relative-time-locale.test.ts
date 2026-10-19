// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { formatAbsoluteDateTime, formatRelativeTime } from "@/lib/relative-time";

afterEach(() => {
  vi.useRealTimers();
  document.documentElement.lang = "";
});

describe("visible time language", () => {
  it("uses the active page locale for both relative and absolute timestamps", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-14T00:00:00Z"));
    document.documentElement.lang = "zh-CN";
    const relative = formatRelativeTime("2026-10-13T12:00:00Z");
    const absolute = formatAbsoluteDateTime("2026-10-13T12:00:00Z");
    expect(relative).toContain("小时前");
    expect(relative).not.toContain("ago");
    expect(absolute).toContain("2026");
    expect(absolute).not.toContain("Oct");
  });
});
