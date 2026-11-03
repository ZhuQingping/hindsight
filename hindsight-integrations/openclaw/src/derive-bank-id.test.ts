import { describe, it, expect } from "vitest";
import { deriveBankId, getPluginConfig } from "./index.js";
import type { MoltbotPluginAPI } from "./types.js";

describe("explicit Bank selection", () => {
  it.each([undefined, "", "   "])("rejects a missing Bank (%s)", (bankId) => {
    expect(() => deriveBankId({ agentId: "main" }, { bankId })).toThrow("Bank ID is required");
  });

  it("keeps the same configured Bank across agents and sessions", () => {
    const config = getPluginConfig({
      config: {
        plugins: {
          entries: {
            "contextbase-openclaw": {
              config: {
                bankId: " team ",
                dynamicBankId: true,
                bankIdPrefix: "prod",
                dynamicBankGranularity: ["agent", "user"],
                agentBankMap: { main: "other" },
              },
            },
          },
        },
      },
    } as unknown as MoltbotPluginAPI);
    for (const ctx of [
      undefined,
      { agentId: "main", sessionKey: "agent:main:main" },
      { agentId: "another", senderId: "user", channelId: "channel", messageProvider: "slack" },
    ]) {
      expect(deriveBankId(ctx, config)).toBe("team");
    }
  });
});
