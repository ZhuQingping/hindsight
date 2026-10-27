#!/usr/bin/env node
/** Configure the remote ContextBase service without installing a local engine. */
import * as p from "@clack/prompts";
import { realpathSync } from "fs";
import { resolve } from "path";
import { fileURLToPath } from "url";
import {
  DEFAULT_OPENCLAW_CONFIG_PATH,
  applyApiMode,
  applyCloudMode,
  ensurePluginConfig,
  isValidEnvVarName,
  loadConfig,
  saveConfig,
  type SetupMode,
} from "./setup-lib.js";
import { validateApiUrl } from "./index.js";

export interface ParsedCliArgs {
  help: boolean;
  configPath?: string;
  mode?: SetupMode;
  apiUrl?: string;
  token?: string;
  tokenEnv?: string;
  bankId?: string;
  noToken: boolean;
  positional?: string;
}
export function parseCliArgs(argv: string[]): ParsedCliArgs {
  const args: ParsedCliArgs = { help: false, noToken: false };
  for (let i = 0; i < argv.length; i++) {
    const flag = argv[i];
    if (flag === "--help" || flag === "-h") {
      args.help = true;
      continue;
    }
    if (flag === "--no-token") {
      args.noToken = true;
      continue;
    }
    const keys = {
      "--config-path": "configPath",
      "--mode": "mode",
      "--api-url": "apiUrl",
      "--token": "token",
      "--token-env": "tokenEnv",
      "--bank-id": "bankId",
    } as const;
    if (flag in keys) {
      const value = argv[++i];
      if (!value || value.startsWith("--")) throw new Error(`Missing value for ${flag}`);
      if (flag === "--mode" && value !== "cloud" && value !== "api")
        throw new Error("Only cloud or api mode is supported.");
      Object.assign(args, { [keys[flag as keyof typeof keys]]: value });
    } else if (!flag.startsWith("-") && !args.positional) args.positional = flag;
    else throw new Error(`Unknown option: ${flag}`);
  }
  return args;
}
export async function runNonInteractive(args: ParsedCliArgs): Promise<void> {
  const path = args.configPath ?? args.positional ?? DEFAULT_OPENCLAW_CONFIG_PATH;
  const cfg = await loadConfig(path);
  const existing = cfg.plugins?.entries?.["contextbase-openclaw"]?.config;
  const apiUrl = validateApiUrl(args.apiUrl ?? (existing?.contextbaseApiUrl as string | undefined));
  const bankId = (args.bankId ?? (existing?.bankId as string | undefined))?.trim();
  if (!bankId) throw new Error("--bank-id is required; use an existing authorized Bank.");
  if (args.mode === "cloud" && args.noToken) throw new Error("Cloud mode requires a credential.");
  if ([Boolean(args.token), Boolean(args.tokenEnv), args.noToken].filter(Boolean).length > 1)
    throw new Error("Choose only one token option.");
  if (args.tokenEnv && !isValidEnvVarName(args.tokenEnv))
    throw new Error("Invalid token environment variable name.");
  const pc = ensurePluginConfig(cfg);
  // Keep an existing credential unless the user supplied a replacement or explicitly disabled it.
  const previous = pc.contextbaseApiToken;
  const input = { apiUrl, token: args.token, tokenEnvVar: args.tokenEnv };
  if (args.mode === "cloud" && !previous && !args.token && !args.tokenEnv)
    throw new Error("Cloud mode requires --token or --token-env.");
  if (args.mode === "cloud" && (args.token || args.tokenEnv)) applyCloudMode(pc, input);
  else applyApiMode(pc, input);
  if (!args.token && !args.tokenEnv && !args.noToken && previous) pc.contextbaseApiToken = previous;
  pc.bankId = bankId;
  pc.dynamicBankId = false;
  await saveConfig(path, cfg);
}
async function main(): Promise<void> {
  const args = parseCliArgs(process.argv.slice(2));
  if (args.help) {
    console.log(
      "contextbase-openclaw-setup --mode cloud --api-url <Endpoint> --token-env CONTEXTBASE_API_TOKEN --bank-id <Bank> [--config-path <file>]\nUse --mode api --no-token only for a service that allows unauthenticated requests."
    );
    return;
  }
  if (!args.mode) {
    p.intro("ContextBase remote service");
    const values = await p.group(
      {
        apiUrl: () =>
          p.text({
            message: "API Endpoint",
            validate: (v) => {
              try {
                validateApiUrl(v);
                return;
              } catch {
                return "Enter an HTTP(S) API Endpoint.";
              }
            },
          }),
        token: () => p.password({ message: "API Key" }),
        bankId: () =>
          p.text({
            message: "Existing Bank ID",
            validate: (v) => (v?.trim() ? undefined : "Bank ID is required"),
          }),
      },
      {
        onCancel: () => {
          throw new Error("Setup cancelled");
        },
      }
    );
    Object.assign(args, values, { mode: "cloud" });
  }
  await runNonInteractive(args);
  console.log("ContextBase configured. Restart the OpenClaw gateway to activate.");
}
export function isDirectExecution(argv1: string | undefined, moduleUrl: string): boolean {
  if (!argv1) return false;
  try {
    return realpathSync(resolve(argv1)) === realpathSync(fileURLToPath(moduleUrl));
  } catch {
    return false;
  }
}
if (isDirectExecution(process.argv[1], import.meta.url))
  main().catch((error) => {
    console.error(`ContextBase setup failed: ${error.message}`);
    process.exitCode = 1;
  });
