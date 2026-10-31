// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
const route = vi.hoisted(() => ({ tab: "general" }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ bankId: "demo" }),
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams({ view: "profile", bankConfigTab: route.tab }),
}));
vi.mock("next-intl", () => ({
  useTranslations: () => Object.assign((key: string) => key, { rich: (key: string) => key }),
}));
vi.mock("@/lib/contextdb-mode", () => ({ useContextDBMode: () => true }));
vi.mock("@/lib/features-context", () => ({
  useFeatures: () => ({ features: { llm_trace: true } }),
}));
vi.mock("@/lib/bank-context", () => ({ useBank: () => ({ currentBank: "demo" }) }));
vi.mock("@/lib/api", () => ({ client: {} }));
vi.mock("@/components/bank-selector", () => ({ BankSelector: () => <div>BankSelector</div> }));
vi.mock("@/components/sidebar", () => ({ Sidebar: () => <div>Sidebar</div> }));
vi.mock("@/components/data-view", () => ({ DataView: () => <div>DataView</div> }));
vi.mock("@/components/documents-view", () => ({ DocumentsView: () => <div>DocumentsView</div> }));
vi.mock("@/components/entities-view", () => ({ EntitiesView: () => <div>EntitiesView</div> }));
vi.mock("@/components/knowledge-base-view", () => ({
  KnowledgeBaseView: () => <div>KnowledgeBaseView</div>,
}));
vi.mock("@/components/home-view", () => ({ HomeView: () => <div>HomeView</div> }));
vi.mock("@/components/think-view", () => ({ ThinkView: () => <div>ThinkView</div> }));
vi.mock("@/components/search-debug-view", () => ({
  SearchDebugView: () => <div>SearchDebugView</div>,
}));
vi.mock("@/components/bank-profile-view", () => ({
  BankProfileView: () => <div>BankProfileView</div>,
}));
vi.mock("@/components/bank-config-view", () => ({
  BankConfigView: () => <div>BankConfigView</div>,
}));
vi.mock("@/components/memory-defense-section", () => ({
  MemoryDefenseSection: () => <div>MemoryDefenseSection</div>,
}));
vi.mock("@/components/bank-stats-view", () => ({ BankStatsView: () => <div>BankStatsView</div> }));
vi.mock("@/components/bank-operations-view", () => ({
  BankOperationsView: () => <div>BankOperationsView</div>,
}));
vi.mock("@/components/mental-models-view", () => ({
  MentalModelsView: () => <div>MentalModelsView</div>,
}));
vi.mock("@/components/audit-logs-view", () => ({ AuditLogsView: () => <div>AuditLogsView</div> }));
vi.mock("@/components/llm-health-dialog", () => ({
  LlmHealthDialog: () => <div>LlmHealthDialog</div>,
}));
const { default: BankPage } = await import("@/app/[locale]/banks/[bankId]/page");
afterEach(() => cleanup());
it.each(["webhooks", "llm-requests", "unknown"])(
  "shows the overview for retired or unknown tab %s",
  (tab) => {
    route.tab = tab;
    render(<BankPage />);
    expect(screen.getByText("BankOperationsView")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "webhooks" })).toBeNull();
    expect(screen.queryByRole("button", { name: "llmRequests" })).toBeNull();
  }
);
