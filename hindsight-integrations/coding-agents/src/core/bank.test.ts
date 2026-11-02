import { describe, expect, it, vi } from "vitest";
import { configuredBankId, configuredBankIdOrSkip } from "./bank";
import { resolveConfig } from "./config";

vi.mock("./git-layout", () => ({
  probeGitLayout: vi.fn(() => {
    throw new Error("Git must not select a Bank");
  }),
}));

describe("configured Bank", () => {
  it("uses only the explicit ID and trims surrounding whitespace", () => {
    expect(configuredBankId({ bankId: "  team_workspace  " })).toBe("team_workspace");
  });
  it.each([undefined, "", "   "])(
    "rejects an absent ID (%s) without generating a replacement",
    (bankId) => {
      expect(() => configuredBankId({ bankId })).toThrow(/bank use <BANK_ID>/);
      expect(configuredBankIdOrSkip({ bankId })).toBeNull();
    }
  );
  it("ignores obsolete dynamic, directory mapping and template settings", () => {
    const config = resolveConfig({
      bankId: "fixed",
      dynamicBankId: true,
      bankIdTemplate: "{project}",
      mapPathToBank: { "/": "other" },
    } as never);
    expect(configuredBankId(config)).toBe("fixed");
    expect(configuredBankIdOrSkip(resolveConfig({ dynamicBankId: false } as never))).toBeNull();
  });
});
