import { expect, it } from "vitest";
import en from "@/messages/en.json";
import zh from "@/messages/zh-CN.json";

function values(value: object): string[] {
  return Object.values(value).flatMap((item) => (typeof item === "string" ? [item] : values(item)));
}
function displayText(value: string): string {
  // Literal CLI commands are public protocol names; surrounding prose still says workspace.
  return value.replace(
    /\{[^}]*\}|<[^>]*>|--bank-id\b|npx @huaweicloud\/contextbase-coding-agents@latest bank use\b/g,
    ""
  );
}

it("allows the exact Bank-switch command while still rejecting bank in display prose", () => {
  expect(
    displayText("Switch: npx @huaweicloud/contextbase-coding-agents@latest bank use <BANK_ID>")
  ).not.toMatch(/\bbanks?\b/i);
  expect(displayText("Select a bank")).toMatch(/\bbanks?\b/i);
});

it("names workspaces consistently while documenting the SDK bank mapping", () => {
  for (const messages of [en, zh]) {
    const display = { ...messages, resourcePages: { ...messages.resourcePages, connectIntro: "" } };
    for (const value of values(display)) {
      // ICU placeholders, rich-text identifiers and CLI flags retain their protocol names.
      const text = displayText(value);
      expect(text).not.toMatch(/记忆库|\b(?:memory banks?|banks?)\b/i);
    }
    expect(messages.resourcePages.connectIntro).toContain("bank_id");
    expect(messages.metadata.title).toBe("{productName}");
    expect(messages.banksOverview.welcomeTitle).toContain("{productName}");
    expect(messages.login.title).toContain("{productName}");
    expect(messages.resourcePages.guideTitle).toContain("{productName}");
  }
  expect(en.metadata.description).toBe("A data foundation for agents");
  expect(zh.metadata.description).toBe("面向 Agent 的数据底座");
});
