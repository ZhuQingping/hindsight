import type { ContextBaseClient, ContextBaseClientOptions } from "contextbase-client";
import type { PluginConfig } from "./types.js";

export type RetainExtractionMode = "concise" | "verbose" | "custom" | "verbatim" | "chunks";

const RETAIN_EXTRACTION_MODES = new Set<RetainExtractionMode>([
  "concise",
  "verbose",
  "custom",
  "verbatim",
  "chunks",
]);

export interface BankDefaults {
  reflectMission?: string;
  retainMission?: string;
  observationsMission?: string;
  retainExtractionMode?: RetainExtractionMode;
  enableObservations?: boolean;
  dispositionSkepticism?: number;
  dispositionLiteralism?: number;
  dispositionEmpathy?: number;
}

export interface BankConfigApiUpdates {
  entity_labels?: unknown;
  enable_auto_consolidation?: boolean;
}

export function normalizeDispositionTrait(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isInteger(value)) return undefined;
  if (value < 1 || value > 5) return undefined;
  return value;
}

export function normalizeRetainExtractionMode(value: unknown): RetainExtractionMode | undefined {
  if (typeof value !== "string") return undefined;
  const mode = value.trim().toLowerCase();
  return RETAIN_EXTRACTION_MODES.has(mode as RetainExtractionMode)
    ? (mode as RetainExtractionMode)
    : undefined;
}

export function normalizeEntityLabels(value: unknown): unknown | undefined {
  if (value == null) return undefined;
  if (Array.isArray(value)) {
    return value.length > 0 ? value : undefined;
  }
  // The server accepts either a bare list or a `{ attributes: [...] }` object
  // (see parse_entity_labels). A plain keyed object is silently ignored
  // server-side, so only pass through the documented wrapper shape — otherwise
  // drop it and preserve the bank's existing entity_labels.
  if (typeof value === "object") {
    const attributes = (value as { attributes?: unknown }).attributes;
    return Array.isArray(attributes) && attributes.length > 0 ? value : undefined;
  }
  return undefined;
}

function missionFromConfig(value: unknown): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

/**
 * Build updateBankConfig() payload from plugin config. Only includes explicitly set
 * fields so unset options preserve server/bank defaults (backwards compatible).
 */
export function buildBankDefaults(config: PluginConfig): BankDefaults {
  const out: BankDefaults = {};

  const reflectMission = missionFromConfig(config.bankMission);
  if (reflectMission) out.reflectMission = reflectMission;

  const retainMission = missionFromConfig(config.retainMission);
  if (retainMission) out.retainMission = retainMission;

  const observationsMission = missionFromConfig(config.observationsMission);
  if (observationsMission) out.observationsMission = observationsMission;

  if (config.retainExtractionMode) {
    out.retainExtractionMode = config.retainExtractionMode;
  }
  if (typeof config.enableObservations === "boolean") {
    out.enableObservations = config.enableObservations;
  }

  if (config.dispositionSkepticism !== undefined) {
    out.dispositionSkepticism = config.dispositionSkepticism;
  }
  if (config.dispositionLiteralism !== undefined) {
    out.dispositionLiteralism = config.dispositionLiteralism;
  }
  if (config.dispositionEmpathy !== undefined) {
    out.dispositionEmpathy = config.dispositionEmpathy;
  }

  return out;
}

/**
 * Fields applied via PATCH /banks/{id}/config because the wrapper does not
 * accept them in the generated client wrapper.
 */
export function buildBankConfigApiUpdates(config: PluginConfig): BankConfigApiUpdates {
  const out: BankConfigApiUpdates = {};

  if (config.entityLabels !== undefined) {
    out.entity_labels = config.entityLabels;
  }
  if (typeof config.enableAutoConsolidation === "boolean") {
    out.enable_auto_consolidation = config.enableAutoConsolidation;
  }

  return out;
}

export function hasConfiguredBankDefaults(config: PluginConfig): boolean {
  const createPayload = buildBankDefaults(config);
  const configUpdates = buildBankConfigApiUpdates(config);
  return Object.keys(createPayload).length > 0 || Object.keys(configUpdates).length > 0;
}

export async function patchBankConfig(
  bankId: string,
  updates: Record<string, unknown>,
  options: ContextBaseClientOptions
): Promise<void> {
  const url = `${options.baseUrl.replace(/\/$/, "")}/v1/default/banks/${encodeURIComponent(bankId)}/config`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
  if (options.apiKey) {
    headers.Authorization = `Bearer ${options.apiKey}`;
  }

  const response = await fetch(url, {
    method: "PATCH",
    headers,
    body: JSON.stringify({ updates }),
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`patchBankConfig failed (${response.status}): ${text}`);
  }
}

/**
 * Stamp configured missions and bank defaults onto a bank exactly once per
 * process lifetime (caller tracks the set). No-op when no defaults are configured.
 */
export async function applyConfiguredBankDefaults(
  client: ContextBaseClient,
  bankId: string,
  config: PluginConfig,
  clientOpts: ContextBaseClientOptions
): Promise<void> {
  const createPayload = buildBankDefaults(config);
  const configUpdates = buildBankConfigApiUpdates(config);

  if (Object.keys(createPayload).length === 0 && Object.keys(configUpdates).length === 0) {
    return;
  }

  await client.getBankConfig(bankId);

  if (Object.keys(createPayload).length > 0) {
    await client.updateBankConfig(bankId, createPayload);
  }

  if (Object.keys(configUpdates).length > 0) {
    await patchBankConfig(bankId, configUpdates as Record<string, unknown>, clientOpts);
  }
}
