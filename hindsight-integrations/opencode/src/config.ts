/**
 * Configuration management for the ContextBase OpenCode plugin.
 *
 * Loading order (later entries win):
 *   1. Built-in defaults
 *   2. User config file (~/.contextbase/opencode.json)
 *   3. Plugin options (from opencode.json plugin tuple)
 *   4. Environment variable overrides
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

/** Default API URL used when no override is supplied via env, file, or plugin options. */
export const DEFAULT_CONTEXTBASE_API_URL = "";

export interface ContextBaseConfig {
  // Recall
  autoRecall: boolean;
  recallBudget: string;
  recallMaxTokens: number;
  recallTypes: string[];
  recallContextTurns: number;
  recallMaxQueryChars: number;
  recallPromptPreamble: string;
  recallTags: string[];
  recallTagsMatch: "any" | "all" | "any_strict" | "all_strict";

  // Retain
  autoRetain: boolean;
  retainMode: string;
  retainEveryNTurns: number;
  retainOverlapTurns: number;
  retainContext: string;
  retainTags: string[];
  retainMetadata: Record<string, string>;

  // Connection
  contextbaseApiUrl: string | null;
  contextbaseApiToken: string | null;

  // Bank
  bankId: string | null;
  bankIdPrefix: string;
  dynamicBankId: boolean;
  dynamicBankGranularity: string[];
  bankMission: string;
  retainMission: string | null;
  agentName: string;

  // Misc
  debug: boolean;
}

const DEFAULTS: ContextBaseConfig = {
  // Recall
  autoRecall: true,
  recallBudget: "mid",
  recallMaxTokens: 1024,
  recallTypes: ["world", "experience"],
  recallContextTurns: 1,
  recallMaxQueryChars: 800,
  recallTags: [],
  recallTagsMatch: "any",
  recallPromptPreamble:
    "Relevant memories from past conversations (prioritize recent when " +
    "conflicting). Only use memories that are directly useful to continue " +
    "this conversation; ignore the rest:",

  // Retain
  autoRetain: true,
  retainMode: "full-session",
  retainEveryNTurns: 3,
  retainOverlapTurns: 2,
  retainContext: "opencode",
  retainTags: [],
  retainMetadata: {},

  // Connection
  contextbaseApiUrl: DEFAULT_CONTEXTBASE_API_URL,
  contextbaseApiToken: null,

  // Bank
  bankId: null,
  bankIdPrefix: "",
  dynamicBankId: false,
  dynamicBankGranularity: ["agent", "project"],
  bankMission: "",
  retainMission: null,
  agentName: "opencode",

  // Misc
  debug: false,
};

/** Env var → config key + type mapping */
const ENV_OVERRIDES: Record<string, [keyof ContextBaseConfig, "string" | "bool" | "int"]> = {
  CONTEXTBASE_API_URL: ["contextbaseApiUrl", "string"],
  CONTEXTBASE_API_TOKEN: ["contextbaseApiToken", "string"],
  CONTEXTBASE_BANK_ID: ["bankId", "string"],
  CONTEXTBASE_AGENT_NAME: ["agentName", "string"],
  CONTEXTBASE_AUTO_RECALL: ["autoRecall", "bool"],
  CONTEXTBASE_AUTO_RETAIN: ["autoRetain", "bool"],
  CONTEXTBASE_RETAIN_MODE: ["retainMode", "string"],
  CONTEXTBASE_RECALL_BUDGET: ["recallBudget", "string"],
  CONTEXTBASE_RECALL_MAX_TOKENS: ["recallMaxTokens", "int"],
  CONTEXTBASE_RECALL_MAX_QUERY_CHARS: ["recallMaxQueryChars", "int"],
  CONTEXTBASE_RECALL_CONTEXT_TURNS: ["recallContextTurns", "int"],
  CONTEXTBASE_DYNAMIC_BANK_ID: ["dynamicBankId", "bool"],
  CONTEXTBASE_BANK_MISSION: ["bankMission", "string"],
  CONTEXTBASE_BANK_ID_PREFIX: ["bankIdPrefix", "string"],
  CONTEXTBASE_RETAIN_EVERY_N_TURNS: ["retainEveryNTurns", "int"],
  CONTEXTBASE_RETAIN_OVERLAP_TURNS: ["retainOverlapTurns", "int"],
  CONTEXTBASE_RECALL_TAGS: ["recallTags", "string"],
  CONTEXTBASE_RETAIN_TAGS: ["retainTags", "string"],
  CONTEXTBASE_RECALL_TAGS_MATCH: ["recallTagsMatch", "string"],
  CONTEXTBASE_RECALL_PROMPT_PREAMBLE: ["recallPromptPreamble", "string"],
  CONTEXTBASE_RETAIN_CONTEXT: ["retainContext", "string"],
  // NOTE: `debug` is intentionally NOT an env override. It is a proper config
  // option set via opencode.json plugin options or ~/.contextbase/opencode.json,
  // because env vars are unreliable to set for OpenCode's plugin runtime
  // (notably on Windows).
};

function castEnv(value: string, typ: "string" | "bool" | "int"): string | boolean | number | null {
  if (typ === "bool") return ["true", "1", "yes"].includes(value.toLowerCase());
  if (typ === "int") {
    const n = parseInt(value, 10);
    return isNaN(n) ? null : n;
  }
  return value;
}

function loadSettingsFile(path: string): Record<string, unknown> {
  try {
    const raw = readFileSync(path, "utf-8");
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

export function loadConfig(pluginOptions?: Record<string, unknown>): ContextBaseConfig {
  // 1. Start with defaults
  const config: Record<string, unknown> = { ...DEFAULTS };

  // 2. User config file (~/.contextbase/opencode.json)
  const userConfigPath = join(homedir(), ".contextbase", "opencode.json");
  const fileConfig = loadSettingsFile(userConfigPath);
  for (const [key, value] of Object.entries(fileConfig)) {
    if (value !== null && value !== undefined) {
      config[key] = value;
    }
  }

  // 3. Plugin options (from opencode.json: ["@vectorize-io/opencode-contextbase", { ... }])
  if (pluginOptions) {
    for (const [key, value] of Object.entries(pluginOptions)) {
      if (value !== null && value !== undefined) {
        config[key] = value;
      }
    }
  }

  // 4. Environment variable overrides (highest priority)
  for (const [envName, [key, typ]] of Object.entries(ENV_OVERRIDES)) {
    const val = process.env[envName];
    if (val !== undefined) {
      const castVal = castEnv(val, typ);
      if (castVal !== null) {
        config[key] = castVal;
      }
    }
  }

  // Array env vars (comma-separated)
  const recallTagsEnv = process.env["CONTEXTBASE_RECALL_TAGS"];
  if (recallTagsEnv !== undefined) {
    config["recallTags"] = recallTagsEnv
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  }
  const recallTagsMatchEnv = process.env["CONTEXTBASE_RECALL_TAGS_MATCH"];
  if (recallTagsMatchEnv !== undefined) {
    config["recallTagsMatch"] = recallTagsMatchEnv;
  }

  const retainTagsEnv = process.env["CONTEXTBASE_RETAIN_TAGS"];
  if (retainTagsEnv !== undefined) {
    config["retainTags"] = retainTagsEnv
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
  }

  const result = config as unknown as ContextBaseConfig;

  // Validate enum-like fields to catch typos early
  const VALID_RETAIN_MODES = ["full-session", "last-turn"];
  if (!VALID_RETAIN_MODES.includes(result.retainMode)) {
    console.error(
      `[ContextBase] Unknown retainMode "${result.retainMode}" — ` +
        `valid: ${VALID_RETAIN_MODES.join(", ")}. Falling back to "full-session".`
    );
    result.retainMode = "full-session";
  }

  const VALID_TAGS_MATCH = ["any", "all", "any_strict", "all_strict"];
  if (!VALID_TAGS_MATCH.includes(result.recallTagsMatch)) {
    console.error(
      `[ContextBase] Unknown recallTagsMatch "${result.recallTagsMatch}" — ` +
        `valid: ${VALID_TAGS_MATCH.join(", ")}. Falling back to "any".`
    );
    result.recallTagsMatch = "any";
  }

  const VALID_BUDGETS = ["low", "mid", "high"];
  if (!VALID_BUDGETS.includes(result.recallBudget)) {
    console.error(
      `[ContextBase] Unknown recallBudget "${result.recallBudget}" — ` +
        `valid: ${VALID_BUDGETS.join(", ")}. Falling back to "mid".`
    );
    result.recallBudget = "mid";
  }

  return result;
}
