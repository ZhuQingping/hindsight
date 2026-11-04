// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import messages from "@/messages/en.json";
import { withContextdbMessages } from "@/i18n/contextdb-messages";
import { BankConfigView } from "@/components/bank-config-view";
import { SettingsVisibilityProvider } from "@/lib/settings-visibility";
import { MemoryDefenseSection } from "@/components/memory-defense-section";

const state = vi.hoisted(() => ({
  bankId: "workspace_a",
  enabled: true,
  getBankConfig: vi.fn(),
  updateBankConfig: vi.fn(),
  previewConsolidationStrategies: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ client: state }));
vi.mock("@/lib/contextdb-mode", () => ({ useContextDBMode: () => true }));
vi.mock("@/lib/bank-context", () => ({ useBank: () => ({ currentBank: state.bankId }) }));
vi.mock("@/lib/features-context", () => ({
  useFeatures: () => ({ features: { bank_config_api: state.enabled } }),
}));
const config = {
  retain_mission: "Remember architecture decisions",
  reflect_mission: "Cite recorded evidence",
  retain_chunk_size: 7000,
  retain_extraction_mode: "verbose",
  retain_strategies: { careful: { retain_chunk_size: 9000 } },
  retain_default_strategy: "careful",
  enable_observations: false,
  enable_graph_retrieval: false,
  disposition_skepticism: 5,
  reflect_default_options: { reflect_search_observations_max_tokens: 6000 },
  mental_model_min_refresh_interval_seconds: 120,
  mcp_enabled_tools: ["recall"],
  audit_log_enabled: false,
  store_document_text: true,
};
const response = () => ({ bank_id: state.bankId, config: { ...config }, overrides: {} });
const provider = (children: React.ReactNode, showAdvanced = false) => (
  <NextIntlClientProvider locale="en" messages={withContextdbMessages(messages, "en")}>
    <SettingsVisibilityProvider showAdvanced={showAdvanced}>{children}</SettingsVisibilityProvider>
  </NextIntlClientProvider>
);
const section = (id: string) => {
  const e = document.getElementById(`bank-config-${id}`);
  if (!e) throw new Error(id);
  return within(e);
};
beforeEach(() => {
  vi.resetAllMocks();
  state.bankId = "workspace_a";
  state.enabled = true;
  state.getBankConfig.mockResolvedValue(response());
  state.updateBankConfig.mockImplementation(async (_id, updates) => ({
    ...response(),
    config: { ...config, ...updates },
    overrides: updates,
  }));
  state.previewConsolidationStrategies.mockResolvedValue({
    default: { match_count: 0, samples: [] },
    strategies: [],
    complete: true,
  });
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows business settings and only patches changed goals, preserving hidden customizations", async () => {
  render(provider(<BankConfigView />));
  const goal = await screen.findByRole("textbox", { name: "What should be remembered" });
  expect(screen.getAllByRole("textbox")).toHaveLength(2);
  expect(screen.getAllByRole("combobox")).toHaveLength(2);
  expect(screen.queryByRole("spinbutton")).toBeNull();
  expect(screen.queryByText("Recall")).toBeNull();
  expect(screen.queryByText("Preview prompt")).toBeNull();
  expect(screen.queryByText("Default strategy")).toBeNull();
  expect(screen.queryByText("Skepticism")).toBeNull();
  expect(screen.queryByText("Restrict tools")).toBeNull();
  expect(screen.queryByText("Advanced client settings")).toBeNull();
  expect(state.updateBankConfig).not.toHaveBeenCalled();
  fireEvent.change(goal, { target: { value: "Remember API contracts" } });
  fireEvent.click(section("retain").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenCalledExactlyOnceWith("workspace_a", {
      retain_mission: "Remember API contracts",
    })
  );
  await waitFor(() =>
    expect(section("retain").getByRole<HTMLButtonElement>("button").disabled).toBe(true)
  );
  fireEvent.change(screen.getByRole("textbox", { name: "Answer requirements" }), {
    target: { value: "Be concise" },
  });
  fireEvent.click(section("reflect").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenLastCalledWith("workspace_a", {
      reflect_mission: "Be concise",
    })
  );
});

it("keeps privacy defaults inherited and patches only the changed audit setting", async () => {
  render(provider(<BankConfigView />));
  await screen.findByRole("textbox", { name: "What should be remembered" });
  const audit = screen.getByRole("combobox", { name: "Enable Audit Logging" });
  expect(audit.textContent).toContain("Server Default (Disabled)");
  expect(screen.getByRole("combobox", { name: "Store Document Text" }).textContent).toContain(
    "Server Default (Enabled)"
  );
  fireEvent.keyDown(audit, { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("option", { name: "Enabled" }));
  fireEvent.click(section("security").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenCalledExactlyOnceWith("workspace_a", {
      audit_log_enabled: true,
    })
  );
});

it("clears a privacy override with null and shows the newly resolved server default", async () => {
  state.getBankConfig.mockResolvedValueOnce({
    ...response(),
    config: { ...config, audit_log_enabled: true },
    overrides: { audit_log_enabled: true },
  });
  state.updateBankConfig.mockResolvedValueOnce(response());
  render(provider(<BankConfigView />));
  await screen.findByRole("textbox", { name: "What should be remembered" });
  fireEvent.keyDown(screen.getByRole("combobox", { name: "Enable Audit Logging" }), {
    key: "ArrowDown",
  });
  fireEvent.click(await screen.findByRole("option", { name: messages.bankConfig.serverDefault }));
  fireEvent.click(section("security").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenCalledExactlyOnceWith("workspace_a", {
      audit_log_enabled: null,
    })
  );
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Enable Audit Logging" }).textContent).toContain(
      "Server Default (Disabled)"
    )
  );
});

it("preserves newer typing when an earlier save completes", async () => {
  let finishSave!: (value: ReturnType<typeof response>) => void;
  state.updateBankConfig.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishSave = resolve;
      })
  );
  render(provider(<BankConfigView />));
  const goal = await screen.findByRole("textbox", { name: "What should be remembered" });
  fireEvent.change(goal, { target: { value: "Submitted goal" } });
  fireEvent.click(section("retain").getByRole("button", { name: "Save changes" }));
  fireEvent.change(goal, { target: { value: "Newer goal" } });
  await act(async () =>
    finishSave({ ...response(), config: { ...config, retain_mission: "Submitted goal" } })
  );
  expect(screen.getByDisplayValue("Newer goal")).toBeTruthy();
  expect(section("retain").getByRole<HTMLButtonElement>("button").disabled).toBe(false);
});

it("does not reuse a pending previous workspace read after switching workspaces", async () => {
  let resolveFirst!: (value: ReturnType<typeof response>) => void;
  state.getBankConfig.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveFirst = resolve;
      })
  );
  const view = render(provider(<BankConfigView />));
  state.bankId = "workspace_b";
  state.getBankConfig.mockResolvedValueOnce({
    ...response(),
    config: { ...config, retain_mission: "Workspace B" },
  });
  view.rerender(provider(<BankConfigView />));
  await screen.findByDisplayValue("Workspace B");
  await act(async () =>
    resolveFirst({ ...response(), config: { ...config, retain_mission: "Workspace A" } })
  );
  expect(screen.queryByDisplayValue("Workspace A")).toBeNull();
  fireEvent.change(screen.getByRole("textbox", { name: "What should be remembered" }), {
    target: { value: "B edited" },
  });
  fireEvent.click(section("retain").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenLastCalledWith("workspace_b", {
      retain_mission: "B edited",
    })
  );
});

it("offers no form after a failed read or when config writes are disabled", async () => {
  state.getBankConfig.mockRejectedValueOnce(new Error("Unavailable"));
  const view = render(provider(<BankConfigView />));
  await screen.findByText("Unavailable");
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  state.enabled = false;
  view.rerender(provider(<BankConfigView />));
  await screen.findByText("Workspace configuration API is not enabled");
  expect(state.updateBankConfig).not.toHaveBeenCalled();
});

it("restores complete settings directly when the display configuration is enabled", async () => {
  render(provider(<BankConfigView />, true));
  await screen.findByDisplayValue(7000);
  expect(screen.getByText("Restrict tools")).toBeTruthy();
  expect(document.getElementById("bank-config-recall")).toBeTruthy();
  expect(document.getElementById("bank-config-models")).toBeTruthy();
  expect(screen.queryByText("Advanced client settings")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "retain" }));
  fireEvent.click(section("clients").getByRole("button", { name: "Save changes" }));
  await waitFor(() =>
    expect(state.updateBankConfig).toHaveBeenCalledExactlyOnceWith("workspace_a", {
      mcp_enabled_tools: ["retain", "recall"],
    })
  );
});

it("does not render detailed defense controls or a disclosure entry when hidden", async () => {
  render(provider(<MemoryDefenseSection bankId="workspace_a" />));
  await screen.findByText(messages.bankConfig.memoryDefenseTitle);
  expect(screen.getAllByRole("switch")).toHaveLength(1);
  expect(screen.queryByText(messages.bankConfig.memoryDefenseSecretLeakTitle)).toBeNull();
  expect(document.querySelector("details")).toBeNull();
  expect(state.updateBankConfig).not.toHaveBeenCalled();
});

it("renders defense rules directly when the display configuration is enabled", async () => {
  render(provider(<MemoryDefenseSection bankId="workspace_a" />, true));
  await screen.findByText(messages.bankConfig.memoryDefenseSecretLeakTitle);
  expect(document.querySelector("details")).toBeNull();
  expect(state.updateBankConfig).not.toHaveBeenCalled();
});
