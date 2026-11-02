import { describe, expect, it, vi } from "vitest";
vi.mock("./git-layout", () => ({
  probeGitLayout: vi.fn(() => ({ status: "failed", reason: "EAGAIN" })),
}));
import { configuredBankIdOrSkip, isOptedIn } from "./bank";
import { probeGitLayout } from "./git-layout";

describe("Git cannot choose the Bank", () => {
  it("uses the configured ID even when Git is unavailable", () => {
    expect(configuredBankIdOrSkip({ bankId: "fixed" })).toBe("fixed");
    expect(probeGitLayout).not.toHaveBeenCalled();
  });
  it("leaves opt-in approval fail-closed", () => {
    expect(isOptedIn({ optInOnly: true, optInPaths: ["/elsewhere"] }, "/home/me/project")).toBe(
      false
    );
  });
});
