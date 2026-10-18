import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import { translateApiError } from "@/lib/i18n/api-errors";
import en from "../messages/en.json";
import zh from "../messages/zh-CN.json";
import { contextdbWorkspaceMessages } from "./contextdb-messages";

describe("ContextDB workspace terminology", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("uses workspace terminology in API errors only when ContextDB is enabled", () => {
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "false");
    expect(translateApiError("api.errors.banks.fetch")).toBe("Failed to fetch banks");
    vi.stubEnv("HINDSIGHT_CP_CONTEXTDB_ENABLED", "true");
    expect(translateApiError("api.errors.banks.fetch")).toBe("Failed to fetch workspaces");
    expect(
      translateApiError("api.errors.banks.fetch", undefined, {
        headers: new Headers({ "accept-language": "zh-CN" }),
      })
    ).toContain("工作空间");
  });

  it("renders English workspace labels while keeping real ICU arguments functional", () => {
    const messages = contextdbWorkspaceMessages(en, "en");
    const t = createTranslator({ locale: "en", messages });
    expect(t("banksOverview.title")).toBe("Workspaces");
    expect(t("nav.bank.returnTo", { bank: "MySQL" })).toBe("Return to MySQL");
    expect(t("bank.cloneSucceeded", { bankName: "PG" })).toBe("Workspace cloned into PG");
    expect(en.banksOverview.title).toBe("Memory banks");
  });

  it("invites empty instances to create a workspace and explains sharing within a workspace", () => {
    const t = createTranslator({
      locale: "zh-CN",
      messages: contextdbWorkspaceMessages(zh, "zh-CN"),
    });
    expect(t("nav.bank.select")).toBe("选择工作空间...");
    expect(t("banksOverview.welcomeBody")).toContain("创建一个工作空间");
    expect(t("banksOverview.subtitle")).toContain("共享同一空间");
    expect(zh.nav.bank.select).toBe("选择记忆库...");
  });

  it("preserves protocol identifiers and rich-text tags when formatting labels", () => {
    const t = createTranslator({
      locale: "en",
      messages: contextdbWorkspaceMessages(
        {
          label: "Bank <bankName>{bank}</bankName> (bank_id): memory banks",
        },
        "en"
      ),
    });
    expect(t.rich("label", { bank: "MySQL", bankName: (text) => String(text) })).toBe(
      "Workspace MySQL (bank_id): workspaces"
    );
  });

  it("retains unsupported locale catalogs for their native translators", () => {
    const messages = { label: "Banques" };
    expect(contextdbWorkspaceMessages(messages, "fr")).toBe(messages);
  });
});
