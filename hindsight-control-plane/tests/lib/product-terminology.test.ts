import { expect, it } from "vitest";
import en from "@/messages/en.json";
import zh from "@/messages/zh-CN.json";

function values(value: object): string[] {
  return Object.values(value).flatMap(item => typeof item === "string" ? [item] : values(item));
}
it("names workspaces consistently while documenting the SDK bank mapping", () => {
  for (const messages of [en, zh]) {
    const display = { ...messages, resourcePages: { ...messages.resourcePages, connectIntro: "" } };
    for (const value of values(display)) {
      // ICU placeholders and rich-text identifiers are protocol names, not visible copy.
      const text = value.replace(/\{[^}]*\}|<[^>]*>/g, "");
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
