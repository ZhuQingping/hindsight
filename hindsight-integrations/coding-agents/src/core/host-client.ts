/**
 * ONE place a long-lived host turns "which repo am I serving" into a configured client.
 *
 * Every persistent host (dsh, Cline, Kilo, Prime Agent, opencode and the other plugin entries, the
 * MCP server) used to carry its own copy of the same four steps — loadConfig, configuredBankIdOrSkip,
 * applyBankConfig, `new ContextBaseClient({...})`. Five copies of a block is five chances to leave a
 * field out, and two already had: dsh and Prime Agent never passed `maxParallelRetains` (so both
 * silently ignored that setting), and dsh never passed the directory to `applyBankConfig` (so
 * `optInOnly` was not enforced there at all). #3600 was the same shape a third time — the
 * credential snapshot — which is why the fix is one shared builder rather than a sixth line added
 * to each host.
 *
 * The one-shot CLIs (`status.ts`, `deepen.ts`) stay out: they resolve config from `--config`/
 * `--harness` flags rather than from a workspace, and their process ends long before a credential
 * can rotate under them.
 */
import { applyBankConfig, loadConfig, resolveConfig, type Config } from "./config";
import { configuredBankIdOrSkip } from "./bank";
import { RemoteConnectionError } from "./connection";
import { log } from "./log";
import { ContextBaseClient } from "./contextbase";

/** A host's resolved memory: the config for THIS workspace, the bank it resolved to, and a client
 *  bound to both. */
export interface HostMemory {
  cfg: Config;
  bankId: string;
  client: ContextBaseClient;
}

/** Resolve config for one workspace: env + file + `harnesses.<name>`, then the `banks.<id>`
 *  behavioral section for the configured Bank, with `optInOnly` enforced. */
export function resolveHostConfig(
  harness: string,
  directory: string
): { cfg: Config; bankId: string } {
  let cfg0: Config;
  try {
    cfg0 = loadConfig({ harness });
  } catch (error) {
    if (!(error instanceof RemoteConnectionError)) throw error;
    // Host startup is not the installer: invalid memory settings must not reject
    // the host plugin. Every persistent adapter honors this shared disabled exit.
    log.warn(harness, `Memory integration disabled: ${error.message}`);
    return { cfg: resolveConfig({ disabled: true, harness }), bankId: "" };
  }
  // A globally disabled plugin stops HERE, before Bank selection: `disabled` exists to be a
  // zero-overhead baseline — the same agent with no memory — not merely a silent one. Callers
  // return early on `cfg.disabled`, so the empty bank id never reaches a request.
  if (cfg0.disabled) return { cfg: cfg0, bankId: "" };
  const bankId = configuredBankIdOrSkip(cfg0, harness);
  // Missing Bank configuration disables every persistent host through the same boundary.
  if (bankId === null) return { cfg: { ...cfg0, disabled: true }, bankId: "" };
  const resolved = applyBankConfig(cfg0, bankId, directory);
  return resolved;
}

/**
 * Resolve config for `directory` and build the client for it.
 *
 * Callers still decide what a disabled config means for them (skip registration, cache a null
 * workspace, expose no tools) — `cfg.disabled` on the returned config already accounts for both
 * the global switch and the per-bank opt-out. Building a client has no side effect: nothing is
 * sent until a caller asks for something.
 */
export function resolveHostMemory(harness: string, directory: string): HostMemory {
  const { cfg, bankId } = resolveHostConfig(harness, directory);
  return {
    cfg,
    bankId,
    client: new ContextBaseClient({
      apiUrl: cfg.apiUrl,
      apiToken: cfg.apiToken,
      bank: bankId,
      maxParallelRetains: cfg.maxParallelRetains,
      observationScopes: cfg.observationScopes,
      pageSearchLimit: cfg.pageSearchLimit,
      recallOptions: cfg.recallOptions,
      // The credential a host STARTED with is not the one it must keep using: enable auth or
      // rotate the key mid-session and the snapshot 401s every call until restart (#3600). Read
      // through the same pipeline the constructor used, keeping the one default connection.
      // The URL stays the one this client was built with, so a token re-read after the config
      // moved this directory to ANOTHER server is that server's credential: never send it here.
      tokenProvider: () => {
        const live = resolveHostConfig(harness, directory).cfg;
        return live.apiUrl === cfg.apiUrl ? live.apiToken : cfg.apiToken;
      },
    }),
  };
}
