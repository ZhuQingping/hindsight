import { afterEach, expect, it, vi } from "vitest";

afterEach(() => {
  vi.doUnmock("./brand-defaults.js");
  vi.resetModules();
});
it.each(["A", "ContextBase", "Atlas Grove"])("renders valid ANSI for display %s", async (name) => {
  vi.doMock("./brand-defaults.js", () => ({ DISPLAY_NAME: name }));
  const { brandWord } = await import("./brand.js");
  const rendered = brandWord();
  expect(rendered).not.toContain("NaN");
  expect(rendered.replace(/\x1b\[[0-9;]*m/g, "")).toBe(name);
});
