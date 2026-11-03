import type {
  MoltbotPluginAPI,
  PluginConfig,
  PluginHookAgentContext,
  PluginHookEndedTranscript,
  MemoryResult,
  RetainRequest,
} from "./types.js";
import {
  ContextBaseClient,
  type ContextBaseClientOptions,
  type MinScores,
} from "contextbase-client";
import { RetainQueue } from "./retain-queue.js";
import { createMemoryProviderRuntime } from "./memory-provider.js";
import { compileSessionPatterns, matchesSessionPattern } from "./session-patterns.js";
import { parseSessionFile } from "./session-file.js";
import { createHash, randomUUID } from "crypto";
import { dirname, join } from "path";
import * as log from "./logger.js";
import { configureLogger, setApiLogger, stopLogger } from "./logger.js";
import { mkdirSync } from "fs";
import { createRequire } from "module";
import { homedir } from "os";
import {
  applyConfiguredBankDefaults,
  hasConfiguredBankDefaults,
  normalizeDispositionTrait,
  normalizeEntityLabels,
  normalizeRetainExtractionMode,
} from "./bank-defaults.js";

function loadPackageVersion(): string {
  try {
    const require = createRequire(import.meta.url);
    const pkg = require("../package.json") as { version?: string };
    return pkg.version ?? "0.0.0";
  } catch {
    return "0.0.0";
  }
}

const USER_AGENT = `contextbase-openclaw/${loadPackageVersion()}`;

export const DEFAULT_RETAIN_CONTEXT =
  "This content is an AI-assistant conversation transcript from OpenClaw. " +
  "Retain request metadata may include routing identifiers such as " +
  "'sender_id' (an opaque user ID, not a human name), 'channel_id' (a chat identifier), " +
  "and 'provider' (the messaging platform name). " +
  "These are operational routing metadata, not semantic actors or people. " +
  "Messages with role 'assistant' are from the AI assistant; first-person statements " +
  "in assistant messages refer to the AI, not the human user. " +
  "Messages with role 'user' are from the human user. " +
  "Bank IDs, session keys, agent IDs, thread IDs, source systems, " +
  "and tags in metadata are also operational routing identifiers, " +
  "not human names, project names, or organizations.";

// Debug logging: silent by default, enable with debug: true or logLevel: 'debug'
let debugEnabled = false;
const debug = (...args: unknown[]) => {
  if (debugEnabled)
    log.verbose(
      args
        .map((a) => (typeof a === "string" ? a.replace(/^\[ContextBase\]\s*/, "") : String(a)))
        .join(" ")
    );
};

// Module-level state
let client: ContextBaseClient | null = null;
let clientOptions: ContextBaseClientOptions | null = null;
let initPromise: Promise<void> | null = null;
let isInitialized = false;

// Capability detected once per service.start() against `<apiUrl>/version`.
// `true` when the ContextBase API supports `update_mode: 'append'` (added in
// 0.5.0 — see the upstream append-mode change) and stores document text. When false,
// retain falls back to a per-turn document id so prior turns aren't silently
// overwritten or rejected by text-disabled deployments.
let supportsUpdateModeAppend = false;
let appendCapabilityProbed = false;
const MIN_VERSION_FOR_UPDATE_MODE_APPEND = "0.5.0";

/** Whether retain is currently using session-scoped documents + `update_mode: 'append'`. */
export function isAppendModeSupported(): boolean {
  return supportsUpdateModeAppend;
}

export type AsyncRetainOperationIdCapability = "supported" | "unsupported" | "unknown";
let asyncRetainOperationIdCapability: AsyncRetainOperationIdCapability = "unknown";
const MIN_VERSION_FOR_ASYNC_RETAIN_OPERATION_ID = "0.8.6";

// Store the current plugin config for explicit Bank selection
let currentPluginConfig: PluginConfig | null = null;
let serviceGeneration = 0;
let serviceAbortController: AbortController | null = null;
// External-API hooks can lazy-initialize before the first service.start(). Keep
// that lifetime cancellable: the first start() or stop() aborts it.
//
// It covers retain as well as recall. It used to be recall-only, but OpenClaw
// re-evaluates this module for each plugin registry it loads and only ever calls
// service.start() on the first one, so the hooks that actually run often belong
// to a copy that is never started. Recall worked there and retain returned at its
// lifecycle guard without a log line, so memory silently stopped growing. (#4828)
const preServiceController = new AbortController();

/**
 * Snapshot the lifecycle a hook runs under: the started service's, or the
 * pre-start one when this module copy was never started. `isCurrent()` turns
 * false once a later start() or stop() replaces it, so in-flight work can bail.
 * After an explicit stop() there is no lifecycle and hooks do nothing.
 */
function captureHookLifecycle(): { signal: AbortSignal | undefined; isCurrent: () => boolean } {
  const generation = serviceGeneration;
  const controller = serviceAbortController ?? (generation === 0 ? preServiceController : null);
  return {
    signal: controller?.signal,
    isCurrent: () =>
      controller !== null &&
      (serviceAbortController ?? preServiceController) === controller &&
      generation === serviceGeneration &&
      !controller.signal.aborted,
  };
}

// Track which banks have had configured defaults applied (missions + bank config).
const banksWithDefaultsApplied = new Set<string>();

// In-flight recall deduplication: concurrent recalls for the same bank reuse one promise
import type { RecallResponse } from "./types.js";
const inflightRecalls = new Map<string, Promise<RecallResponse>>();

// Lightweight bank-scoped facade over ContextBaseClient. Created per-request via
// getClientForContext() so hook bodies can keep their bankId-implicit style
// without going back to a stateful setBankId pattern. Also bridges the
// small shape differences (e.g. RetainRequest.metadata is Record<string, unknown>
// at build time; ContextBaseClient wants Record<string, string>).
export interface BankScopedClient {
  readonly bankId: string;
  retain(
    req: RetainRequest,
    capability?: AsyncRetainOperationIdCapability,
    signal?: globalThis.AbortSignal
  ): Promise<void>;
  recall(
    req: {
      query: string;
      maxTokens?: number;
      budget?: "low" | "mid" | "high";
      types?: Array<"world" | "experience" | "observation">;
      preferObservations?: boolean;
      minScores?: MinScores;
    },
    timeoutMs?: number,
    signal?: globalThis.AbortSignal
  ): Promise<RecallResponse>;
  setMissions(opts: BankMissionsUpdate): Promise<void>;
}

export interface BankMissionsUpdate {
  reflectMission?: string;
  retainMission?: string;
  observationsMission?: string;
}

export function scopeClient(c: ContextBaseClient, bankId: string): BankScopedClient {
  return {
    bankId,
    async retain(req, capability = asyncRetainOperationIdCapability, signal) {
      await c.retain(bankId, req.content, {
        documentId: req.documentId,
        context: req.context,
        metadata: toStringMetadata(req.metadata),
        tags: req.tags,
        updateMode: req.updateMode,
        async: true,
        signal,
        ...(capability === "supported" && req.operationId ? { operationId: req.operationId } : {}),
      });
    },
    async recall(req, timeoutMs, signal) {
      signal?.throwIfAborted();
      // Two independent reasons to stop: the caller's service-owned signal (stop
      // or restart) and this call's own deadline. Compose them so the transport is
      // cancelled by whichever fires first, while the reason the caller classifies
      // on survives — a TimeoutError for the deadline, an AbortError for a stop.
      const deadline = new AbortController();
      const effective = signal ? AbortSignal.any([signal, deadline.signal]) : deadline.signal;
      let onAbort!: () => void;
      const cancelled = new Promise<never>((_, reject) => {
        onAbort = () => reject(effective.reason);
        effective.addEventListener("abort", onAbort, { once: true });
      });
      const timer = timeoutMs
        ? setTimeout(
            () =>
              deadline.abort(
                new DOMException(`Recall timed out after ${timeoutMs}ms`, "TimeoutError")
              ),
            timeoutMs
          )
        : undefined;
      try {
        // A race alone only stopped the hook's wait. Forward cancellation to the
        // client too, so its HTTP request receives the deadline and service stops.
        //
        // The race stays as a backstop for a transport that ignores the signal,
        // which is not hypothetical: from client 0.10.x recall routes through
        // `retryOnCapacity`, whose backoff sleeps in a plain setTimeout, so an
        // abort during a 429/503 wait does not interrupt it. (#4445)
        const response = await Promise.race([
          c.recall(bankId, req.query, {
            maxTokens: req.maxTokens,
            budget: req.budget,
            types: req.types,
            preferObservations: req.preferObservations,
            minScores: req.minScores,
            signal: effective,
          }),
          cancelled,
        ]);
        effective.throwIfAborted();
        return response;
      } finally {
        clearTimeout(timer);
        effective.removeEventListener("abort", onAbort);
      }
    },
    async setMissions(opts) {
      // Updating settings must not create a missing Bank.
      await c.getBankProfile(bankId);
      await c.updateBankConfig(bankId, {
        reflectMission: opts.reflectMission,
        retainMission: opts.retainMission,
        observationsMission: opts.observationsMission,
      });
    },
  };
}

async function ensureBankDefaultsApplied(bankId: string, config: PluginConfig): Promise<void> {
  if (!client || !clientOptions || !hasConfiguredBankDefaults(config)) {
    return;
  }
  if (banksWithDefaultsApplied.has(bankId)) {
    return;
  }
  try {
    await applyConfiguredBankDefaults(client, bankId, config, clientOptions);
    banksWithDefaultsApplied.add(bankId);
    debug(`[ContextBase] Applied configured defaults for bank: ${bankId}`);
  } catch (error) {
    log.warn(
      `could not apply bank defaults for ${bankId}: ${error instanceof Error ? error.message : error}`
    );
  }
}

/**
 * Format a single perf line for the `debugPerfTiming` flag. Pure function so
 * the formatting can be unit-tested without standing up the full hook pipeline.
 * Caller is responsible for stringifying durations with the `ms` suffix —
 * counts and identifiers are rendered as-is.
 */
export function formatHookPerf(
  hook: string,
  hookTotalMs: number,
  fields: Record<string, string | number | undefined>
): string {
  const parts = [`hook_total=${hookTotalMs}ms`];
  for (const [k, v] of Object.entries(fields)) {
    if (v === undefined) continue;
    parts.push(`${k}=${v}`);
  }
  return `perf: ${hook} ${parts.join(" ")}`;
}

/**
 * The generated client's metadata type is `Record<string, string>`; the
 * openclaw builder uses `Record<string, unknown>` because some fields come
 * from optional plugin context. Drop undefined/null, stringify the rest.
 */
function toStringMetadata(
  input: Record<string, unknown> | undefined
): Record<string, string> | undefined {
  if (!input) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(input)) {
    if (v === undefined || v === null) continue;
    out[k] = typeof v === "string" ? v : String(v);
  }
  return out;
}
const turnCountBySession = new Map<string, number>();
const MAX_TRACKED_SESSIONS = 10_000;
const DEFAULT_RECALL_TIMEOUT_MS = 10_000;

type SessionIdentityRecord = Pick<
  PluginHookAgentContext,
  "senderId" | "messageProvider" | "channelId"
>;
export type IdentitySkipReason =
  | {
      kind: "retryable";
      detail: "missing stable message provider" | "missing stable sender identity";
    }
  | { kind: "final"; detail: string };

const sessionIdentityBySession = new Map<string, SessionIdentityRecord>();
const skipContextBaseTurnBySession = new Map<string, IdentitySkipReason>();
const documentSequenceBySession = new Map<string, number>();

// Random token minted once per host process and mixed into fallback (non-append)
// document ids. `documentSequenceBySession` lives only in memory, so it restarts
// at 1 on every host restart — and it is FIFO-capped at MAX_TRACKED_SESSIONS, so
// a busy host can evict a live session's counter and recycle its ids without any
// restart at all. Either way the replayed id hits an existing server-side
// document, and retain's default `update_mode: 'replace'` *deletes* that
// document's memories before reprocessing: months of history collapsed to a
// single restart cycle's worth of turns. (#3686)
let documentIdBootToken: string | null = null;

/** Per-process token that keeps fallback document ids unique across restarts. */
export function getDocumentIdBootToken(): string {
  if (!documentIdBootToken) {
    documentIdBootToken = randomUUID().replace(/-/g, "").slice(0, 8);
  }
  return documentIdBootToken;
}

// Cooldown + guard to prevent concurrent reinit attempts
let lastReinitAttempt = 0;
let isReinitInProgress = false;
const REINIT_COOLDOWN_MS = 30_000;

// Persistent retry queue for temporary API outages
let retainQueue: RetainQueue | null = null;
let retainQueueFlushTimer: ReturnType<typeof setInterval> | null = null;
let isFlushInProgress = false;
const DEFAULT_FLUSH_INTERVAL_MS = 60_000; // 1 min

/**
 * Open the JSONL retain queue and start its periodic flush timer.
 *
 * Never throws: without the queue a failed retain is dropped exactly as it was
 * before the queue existed, which is worth far less than taking the whole plugin
 * down over an unwritable state directory.
 */
function initRetainQueue(
  pluginConfig: PluginConfig,
  expectedGeneration: number,
  signal: globalThis.AbortSignal
): void {
  // service.start() can run again without an intervening stop() (gateway
  // reloads); don't leak the previous generation's timer onto the new one.
  if (retainQueueFlushTimer) {
    clearInterval(retainQueueFlushTimer);
    retainQueueFlushTimer = null;
  }
  try {
    const queueDir = pluginConfig.retainQueuePath
      ? dirname(pluginConfig.retainQueuePath)
      : join(homedir(), ".openclaw", "data");
    mkdirSync(queueDir, { recursive: true });
    const queuePath =
      pluginConfig.retainQueuePath || join(queueDir, "contextbase-retain-queue.jsonl");
    const queueFlushInterval = pluginConfig.retainQueueFlushIntervalMs ?? DEFAULT_FLUSH_INTERVAL_MS;
    const queueMaxAge = pluginConfig.retainQueueMaxAgeMs ?? -1;
    retainQueue = new RetainQueue({ filePath: queuePath, maxAgeMs: queueMaxAge });
    const pending = retainQueue.size();
    if (pending > 0) {
      log.info(`retain queue: ${pending} items pending from previous session, will flush shortly`);
    }
    debug(`[ContextBase] Retain queue initialized: ${queuePath}`);

    // Periodic flush timer
    if (queueFlushInterval > 0) {
      retainQueueFlushTimer = setInterval(() => {
        void flushRetainQueue(undefined, undefined, undefined, expectedGeneration, signal);
      }, queueFlushInterval);
      retainQueueFlushTimer.unref?.();
    }
  } catch (error) {
    retainQueue = null;
    log.warn(`could not initialize retain queue, continuing without it: ${error}`);
  }
}

/**
 * Attempt to flush pending retains from the queue.
 * Each item is sent exactly as it would have been originally — same bank, payload, metadata.
 */
export async function flushRetainQueue(
  queueOverride?: RetainQueue,
  clientOverride?: ContextBaseClient,
  capabilityOverride?: AsyncRetainOperationIdCapability,
  expectedGeneration = serviceGeneration,
  signal: globalThis.AbortSignal | undefined = serviceAbortController?.signal
): Promise<void> {
  const activeQueue = queueOverride ?? retainQueue;
  const activeClient = clientOverride ?? client;
  if (
    !activeQueue ||
    isFlushInProgress ||
    expectedGeneration !== serviceGeneration ||
    signal?.aborted
  )
    return;

  isFlushInProgress = true;
  let flushed = 0;
  let failed = 0;

  try {
    // Nothing queued means nothing to be idempotent about, so don't spend a
    // /version round trip: this runs on a timer *and* after every successful
    // retain, and probing an empty queue put a request behind every turn. The
    // capability is re-read here whenever there is actually work to replay,
    // which is the only moment it changes the outcome.
    const pending = activeQueue.size();
    if (pending === 0) return;
    const capability =
      capabilityOverride ?? (await refreshQueueOperationIdCapability(expectedGeneration, signal));
    if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
    if (capability === "unknown") {
      // Held back on purpose: a replay without operation_id is the one path that
      // can duplicate durable memories. Warn rather than debug — if /version
      // stays unreachable the queue grows without ever draining, and that must
      // not be silent.
      log.warn(
        `retain queue flush deferred (${pending} queued): server operation-id capability unknown`
      );
      return;
    }
    if (!activeClient) return; // no client yet — can't flush

    // Cleanup expired items first
    activeQueue.cleanup();

    const items = activeQueue.peek(50);
    for (const item of items) {
      try {
        if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
        const operationId =
          capability === "supported"
            ? activeQueue.ensureOperationId(item.id, randomUUID())
            : undefined;
        await activeClient.retain(item.bankId, item.content, {
          documentId: item.documentId,
          context: item.context,
          metadata: toStringMetadata(item.metadata),
          tags: item.tags,
          updateMode: item.updateMode,
          async: true,
          signal,
          ...(operationId ? { operationId } : {}),
        });

        if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
        // Checkpoint each acknowledgement before the next network await. A
        // later abort must not replay already-accepted work on legacy servers.
        activeQueue.remove(item.id);
        flushed++;
      } catch {
        if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
        // API still down — stop trying this batch
        failed++;
        break;
      }
    }

    if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
    const remaining = activeQueue.size();
    if (flushed > 0) {
      log.info(
        `queue flush: ${flushed} queued retains delivered${remaining > 0 ? `, ${remaining} still pending` : ", queue empty"}`
      );
    } else if (failed > 0) {
      debug(`[ContextBase] Queue flush: API still unreachable, ${remaining} retains pending`);
    }
  } finally {
    isFlushInProgress = false;
  }
}

const DEFAULT_RECALL_PROMPT_PREAMBLE =
  "Relevant memories from past conversations (prioritize recent when conflicting). Only use memories that are directly useful to continue this conversation; ignore the rest:";

/**
 * The messages a retain should work from, for a `session_end` event that carries none.
 *
 * OpenClaw's `buildSessionEndHookPayload()` sends `sessionId`, `sessionKey`,
 * `messageCount`, `durationMs`, `reason`, `sessionFile` and the next session's ids -
 * no `messages` array, and a `context` holding only ids. The forced flush added for
 * #1726 therefore ended at its own "no messages" guard on every session close, and the
 * turns after the last cadence boundary were never retained (#4341).
 *
 * The transcript the event points at is the source: one synchronous read, which is what
 * the shutdown drain's shared 2s budget allows, and extraction still happens
 * asynchronously in the bank's operation queue. `undefined` when there is no readable
 * transcript, which leaves the caller's existing guard to skip the flush as before.
 *
 * `/new` matters here: OpenClaw emits the previous session's `session_end` lazily, on
 * the first turn of its successor, so the old messages are gone from the live session
 * entry by then and the file is the only copy.
 */
export function sessionEndMessagesFromTranscript(
  event: unknown,
  read: typeof parseSessionFile = parseSessionFile
): unknown[] | undefined {
  const payload = (event ?? {}) as Record<string, any>;
  const sessionFile = typeof payload.sessionFile === "string" ? payload.sessionFile : undefined;
  if (!sessionFile) return undefined;
  const agentId = typeof payload.context?.agentId === "string" ? payload.context.agentId : "";
  try {
    const messages = read(sessionFile, agentId).messages;
    return messages.length > 0 ? messages : undefined;
  } catch {
    // A missing, truncated or unreadable transcript is not an error worth failing the
    // session close over; the caller skips the flush exactly as it did before.
    return undefined;
  }
}

// Generous bounds for one session's tail; OpenClaw applies its own caps on top.
const ENDED_TRANSCRIPT_MAX_MESSAGES = 10_000;
const ENDED_TRANSCRIPT_MAX_BYTES = 8 * 1024 * 1024;

/**
 * The messages of a session that just ended, for the `session_end` flush.
 *
 * OpenClaw 2026.9.4 moved transcripts into SQLite, so the JSONL file the event
 * points at no longer exists and the flush found nothing (#4594). 2026.10.1 added
 * `ctx.endedTranscript`, a bounded reader over that store; use it when the host
 * offers one and keep the file read for older hosts.
 */
export async function sessionEndMessages(
  event: unknown,
  endedTranscript: PluginHookEndedTranscript | undefined
): Promise<unknown[] | undefined> {
  if (endedTranscript === undefined) return sessionEndMessagesFromTranscript(event);
  if (!endedTranscript.available) {
    debug(`[ContextBase Hook] session_end: transcript unavailable (${endedTranscript.reason})`);
    return undefined;
  }
  try {
    const { messages, truncated } = await endedTranscript.readTail({
      maxMessages: ENDED_TRANSCRIPT_MAX_MESSAGES,
      maxBytes: ENDED_TRANSCRIPT_MAX_BYTES,
    });
    if (truncated) debug("[ContextBase Hook] session_end: transcript truncated to its tail");
    return messages.length > 0 ? [...messages] : undefined;
  } catch (error) {
    log.warn(`session_end: could not read the ended transcript: ${error}`);
    return undefined;
  }
}

export function formatCurrentTimeForRecall(date = new Date()): string {
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  const hours = String(date.getUTCHours()).padStart(2, "0");
  const minutes = String(date.getUTCMinutes()).padStart(2, "0");
  // Suffix with " UTC" so the LLM doesn't misread the timestamp as local
  // time and make wrong recency judgments. Mirrors the fix landed for the
  // Claude Code integration in #1568. (#1789)
  return `${year}-${month}-${day} ${hours}:${minutes} UTC`;
}

/**
 * Lazy re-initialization after startup failure.
 * Called by waitForReady when initPromise rejected but API may now be reachable.
 * Throttled to one attempt per 30s to avoid hammering a down service.
 * Only works if initialization was attempted at least once (isInitialized guard).
 */
async function lazyReinit(configOverride?: PluginConfig): Promise<void> {
  const now = Date.now();
  if (now - lastReinitAttempt < REINIT_COOLDOWN_MS || isReinitInProgress) {
    return;
  }

  const config = configOverride ?? currentPluginConfig;
  if (!config) {
    debug("[ContextBase] lazyReinit skipped - no plugin config available");
    return;
  }

  // Persist config if we only have it from the live hook registration path.
  currentPluginConfig = config;

  isReinitInProgress = true;
  lastReinitAttempt = now;
  const externalApi = detectExternalApi(config);
  if (!externalApi.apiUrl) {
    isReinitInProgress = false;
    return;
  }

  debug("[ContextBase] Attempting lazy re-initialization...");
  try {
    deriveBankId(undefined, config);
    await checkExternalApiHealth(externalApi.apiUrl, externalApi.apiToken);
    await detectAppendCapability(externalApi.apiUrl, externalApi.apiToken);

    clientOptions = buildClientOptions(externalApi);
    banksWithDefaultsApplied.clear();
    client = new ContextBaseClient(clientOptions);

    await ensureBankDefaultsApplied(deriveBankId(undefined, config), config);

    isInitialized = true;
    // A copy that was never started has no retain queue, so a failed retain
    // would be dropped instead of replayed. (#4537)
    // ponytail: the started copy may hold the same file, so both can replay one
    // item; the persisted operation id keeps that idempotent on API >= 0.8.6.
    // Share one queue per process via globalThis if duplicates show up on older APIs.
    if (!retainQueue && serviceGeneration === 0 && !preServiceController.signal.aborted) {
      initRetainQueue(config, 0, preServiceController.signal);
    }
    // Replace the rejected initPromise with a resolved one
    initPromise = Promise.resolve();
    debug("[ContextBase] ✓ Lazy re-initialization succeeded");
  } catch (error) {
    log.warn(
      `lazy re-init failed (retry in ${REINIT_COOLDOWN_MS / 1000}s): ${error instanceof Error ? error.message : error}`
    );
  } finally {
    isReinitInProgress = false;
  }
}

// Global access for hooks (Moltbot loads hooks separately)
if (typeof global !== "undefined") {
  (global as any).__contextbaseClient = {
    getClient: () => client,
    waitForReady: async () => {
      if (isInitialized) {
        return;
      }
      // If initPromise is null, it means service.start() hasn't been called yet
      // (CLI mode, not gateway mode). Hooks should gracefully no-op.
      if (!initPromise) {
        if (currentPluginConfig) {
          log.warn(
            "waitForReady called before service.start() — attempting lazy initialization fallback"
          );
          await lazyReinit(currentPluginConfig);
          return;
        }
        log.warn(
          "waitForReady called before service.start() — hooks will no-op (expected in CLI mode)"
        );
        return;
      }
      try {
        await initPromise;
      } catch {
        // Init failed (e.g., health check timeout at startup).
        // Attempt lazy re-initialization so ContextBase recovers
        // once the API becomes reachable again.
        if (!isInitialized) {
          await lazyReinit();
        }
      }
    },
    /**
     * Get a bank-scoped client handle for a specific agent context.
     * Uses the configured Bank and applies its explicitly configured defaults.
     */
    getClientForContext: async (
      ctx: PluginHookAgentContext | undefined
    ): Promise<BankScopedClient | null> => {
      if (!client) return null;
      const config = currentPluginConfig || {};
      const bankId = deriveBankId(ctx, config);
      const scoped = scopeClient(client, bankId);

      // Stamp configured defaults onto this bank on first use (recall or retain).
      await ensureBankDefaultsApplied(bankId, config);

      return scoped;
    },
    getPluginConfig: () => currentPluginConfig,
  };
}

// Throttle set: log an info-level skip message at most once per (sessionKey) per
// process lifetime so operators can discover silent retention/recall skips without
// flooding the log on every turn.
const loggedSkipSessions = new Set<string>();

function getConfiguredBankId(pluginConfig: PluginConfig): string | undefined {
  if (typeof pluginConfig.bankId !== "string") {
    return undefined;
  }

  const trimmed = pluginConfig.bankId.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

/** All agents use the explicitly configured Bank. */
export function agentOnlyBankId(_agentId: string, pluginConfig: PluginConfig): string {
  return deriveBankId(undefined, pluginConfig);
}

/** The initialized client and its options, initializing lazily like the hooks do. */
async function readyClient(): Promise<{
  client: ContextBaseClient;
  options: ContextBaseClientOptions;
} | null> {
  await (global as any).__contextbaseClient?.waitForReady();
  return client && clientOptions ? { client, options: clientOptions } : null;
}

function authHeaders(options: ContextBaseClientOptions): Record<string, string> {
  return options.apiKey ? { Authorization: `Bearer ${options.apiKey}` } : {};
}

/**
 * Strip plugin-injected memory tags from content to prevent retain feedback loop.
 * Removes <contextbase_memories> and <relevant_memories> blocks that were injected
 * during before_prompt_build so they don't get re-stored into the memory bank.
 */
export function stripMemoryTags(content: string): string {
  content = content.replace(/<contextbase_memories>[\s\S]*?<\/contextbase_memories>/g, "");
  content = content.replace(/<relevant_memories>[\s\S]*?<\/relevant_memories>/g, "");
  return content;
}

/**
 * Extract per-message retain tag overrides from inline user content.
 *
 * Supported forms:
 * - <retain_tags>tag:a, tag:b</retain_tags>
 * - <contextbase_retain_tags>tag:a, tag:b</contextbase_retain_tags>
 */
export function extractInlineRetainTags(content: string): string[] {
  if (!content) return [];

  const tags: string[] = [];
  const blockRe = /<(?:contextbase_)?retain_tags>([\s\S]*?)<\/(?:contextbase_)?retain_tags>/gi;
  let match: RegExpExecArray | null;

  while ((match = blockRe.exec(content)) !== null) {
    const normalized = normalizeRetainTags(match[1]);
    for (const tag of normalized) {
      if (!tags.includes(tag)) {
        tags.push(tag);
      }
    }
  }

  return tags;
}

/**
 * Remove inline retain tag directives from message content before storing it.
 */
export function stripInlineRetainTags(content: string): string {
  if (!content) return content;
  return content.replace(
    /<(?:contextbase_)?retain_tags>[\s\S]*?<\/(?:contextbase_)?retain_tags>/gi,
    ""
  );
}

/**
 * Strip OpenClaw's inline timestamp prefix (e.g. "[Wed 2026-04-15 10:44 GMT+2] ")
 * from the start of user-facing text. We lift this into a structured `timestamp`
 * field on the retained message instead, so facts aren't polluted by a weekday
 * prefix that varies per message.
 */
const INLINE_TIMESTAMP_PREFIX_RE =
  /^\s*\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}(?::\d{2})?\s+(?:GMT|UTC)(?:[+\-]\d{1,2}(?::\d{2})?)?\]\s*/;

export function stripInlineTimestampPrefix(content: string): string {
  if (!content) return content;
  return content.replace(INLINE_TIMESTAMP_PREFIX_RE, "");
}

/**
 * Provenance marker OpenClaw appends to every injected inbound context header
 * since 2026.8.1 — e.g. `Conversation info: ⟦openclaw:ctx⟧`. Older hosts label
 * the same blocks `Conversation info (untrusted metadata):` instead. Both forms
 * are recognised: the plugin has to keep working against hosts on either side
 * of that change.
 */
const INBOUND_CONTEXT_MARKER = "⟦openclaw:ctx⟧";

/** Matches a header line in either the marker (2026.8.1+) or legacy form. */
const INBOUND_META_HEADER_RE = new RegExp(
  `^[^\\n]*(?:${INBOUND_CONTEXT_MARKER}|\\(untrusted metadata\\))[^\\n]*$`
);

/** True when `line` opens an OpenClaw-injected inbound metadata block. */
function isInboundMetaHeaderLine(line: string): boolean {
  return INBOUND_META_HEADER_RE.test(line.trim());
}

interface InboundMetaBlock {
  /** Index of the header line's first character. */
  start: number;
  /** Index just past the block (header + body), i.e. where normal text resumes. */
  end: number;
  /** Parsed body when the block is a ```json fence, otherwise undefined. */
  json?: unknown;
}

/**
 * Locate every OpenClaw-injected inbound metadata block in `text`.
 *
 * Mirrors the host's own stripper: a header line is followed either by a
 * ```json fence (block ends at the closing fence) or by free-form lines that
 * end at the first blank line. Keying on the header rather than on a fenced
 * payload is what makes marker-form blocks like `Chat history since last
 * reply: ⟦openclaw:ctx⟧` strippable too.
 */
function findInboundMetaBlocks(text: string): InboundMetaBlock[] {
  if (!text) return [];
  const lines = text.split("\n");
  // Byte offset of the start of each line, plus a terminator past the end.
  const offsets: number[] = [];
  let cursor = 0;
  for (const line of lines) {
    offsets.push(cursor);
    cursor += line.length + 1;
  }
  offsets.push(cursor);

  const blocks: InboundMetaBlock[] = [];
  for (let i = 0; i < lines.length; i++) {
    if (!isInboundMetaHeaderLine(lines[i])) continue;
    const start = offsets[i];
    let end: number;
    let json: unknown;
    if (lines[i + 1]?.trim() === "```json") {
      let close = i + 2;
      while (close < lines.length && lines[close].trim() !== "```") close++;
      if (close < lines.length) {
        try {
          json = JSON.parse(lines.slice(i + 2, close).join("\n"));
        } catch {
          // Leave `json` undefined; the block is still stripped.
        }
      }
      end = offsets[Math.min(close + 1, lines.length)];
      i = close;
    } else {
      let blank = i + 1;
      while (blank < lines.length && lines[blank].trim() !== "") blank++;
      end = offsets[Math.min(blank + 1, lines.length)];
      i = blank;
    }
    blocks.push({ start, end, json });
  }
  return blocks;
}

/**
 * Extract sender_id from OpenClaw's injected inbound metadata blocks.
 * Reads both "Conversation info" and "Sender" blocks, in either the 2026.8.1+
 * `⟦openclaw:ctx⟧` marker form or the legacy "(untrusted metadata)" form.
 * Returns the first sender_id / id string found, or undefined if none.
 */
export function extractSenderIdFromText(text: string): string | undefined {
  if (!text) return undefined;
  for (const block of findInboundMetaBlocks(text)) {
    const obj = block.json as { sender_id?: unknown; id?: unknown } | undefined;
    const id = obj?.sender_id ?? obj?.id;
    if (typeof id === "string" && id) return id;
  }
  return undefined;
}

/**
 * Strip OpenClaw sender/conversation metadata envelopes from message content.
 * These blocks are injected by OpenClaw but are noise for memory storage and recall.
 */
export function stripMetadataEnvelopes(content: string): string {
  if (!content) return content;
  const blocks = findInboundMetaBlocks(content);
  if (blocks.length > 0) {
    const parts: string[] = [];
    let cursor = 0;
    for (const block of blocks) {
      parts.push(content.slice(cursor, Math.max(cursor, block.start)));
      cursor = Math.max(cursor, block.end);
    }
    parts.push(content.slice(cursor));
    content = parts.join("");
  }
  // Drop the `---` fences that wrapped the legacy envelope form.
  content = content.replace(/^---\n/, "").replace(/\n---$/, "");
  return stripRuntimeEnvelope(content).trim();
}

const RUNTIME_MESSAGE_ID_LINE_RE = /^\[message_id:\s*(?:om|ou|oc)_[A-Za-z0-9_-]+\]$/i;
const RUNTIME_OPAQUE_ID_LINE_RE = /^(?:om|ou|oc)_[A-Za-z0-9_-]+$/i;
const RUNTIME_OPAQUE_SENDER_PREFIX_RE = /^\s*(?:om|ou|oc)_[A-Za-z0-9_-]+\s*:\s*/i;

// Opt-in display-name prefix stripping (#3070). Some channels prepend a human
// display name to the user text ("Alice: today weather?"), which pollutes both
// the recall query and the retained transcript (the name gets extracted as a
// fact). No payload field carries the display name, and a generic `Word:`
// heuristic would eat ordinary user text ("计划: 今天修 retain 污染"), so the
// pattern is operator-supplied. Unset = byte-identical to the old behaviour.
// One process-global compiled pattern, armed from getPluginConfig(): the host
// holds a single contextbase-openclaw config, so every session in the process
// shares it. Compile per config if that ever stops being true.
let senderPrefixRe: RegExp | undefined;
let senderPrefixSource: string | undefined;

/**
 * Set (or clear) the display-name prefix pattern stripped by
 * {@link stripRuntimeEnvelope}. The pattern is the name alternation only
 * (e.g. `Alice|Bob` or `[A-Za-z ]{1,20}`); the anchor, surrounding whitespace
 * and the `:` separator are supplied here. An invalid regex fails closed:
 * stripping stays off and nothing throws.
 */
export function configureSenderPrefixStripping(pattern: string | undefined): void {
  if (pattern === senderPrefixSource) return; // no recompile, and no repeat warn
  senderPrefixSource = pattern;
  if (!pattern) {
    senderPrefixRe = undefined;
    return;
  }
  try {
    senderPrefixRe = new RegExp(`^\\s*(?:${pattern})\\s*:\\s*`);
  } catch (error) {
    senderPrefixRe = undefined;
    log.warn(`ignoring invalid senderPrefixPattern ${JSON.stringify(pattern)}: ${error}`);
  }
}

/**
 * Strip inline OpenClaw/Feishu runtime headers that can appear before user text.
 * These identifiers are routing/runtime metadata, not semantic conversation content.
 */
export function stripRuntimeEnvelope(content: string): string {
  if (!content) return content;

  const lines = content.split(/\r?\n/);
  const kept = lines.filter((line) => {
    const trimmed = line.trim();
    return !RUNTIME_MESSAGE_ID_LINE_RE.test(trimmed) && !RUNTIME_OPAQUE_ID_LINE_RE.test(trimmed);
  });

  const stripped = kept.join("\n").replace(RUNTIME_OPAQUE_SENDER_PREFIX_RE, "");
  return senderPrefixRe ? stripped.replace(senderPrefixRe, "") : stripped;
}

/**
 * Extract a recall query from a hook event's rawMessage or prompt.
 *
 * Prefers rawMessage (clean user text). Falls back to prompt, stripping
 * envelope formatting (System: lines, [Channel ...] headers, [from: X] footers).
 *
 * Returns null when no usable query (< 5 chars) can be extracted.
 */
export function extractRecallQuery(
  rawMessage: string | undefined,
  prompt: string | undefined
): string | null {
  // Reject known metadata/system message patterns — these are not user queries
  const METADATA_PATTERNS = [
    /^\s*conversation info\s*\(untrusted metadata\)/i,
    /^\s*\(untrusted metadata\)/i,
    /^\s*system:/i,
  ];
  const isMetadata = (s: string) =>
    METADATA_PATTERNS.some((p) => p.test(s)) ||
    // 2026.8.1+ marker form: a leftover header line is metadata, not a query.
    isInboundMetaHeaderLine(s.split("\n")[0] ?? "");

  let recallQuery = rawMessage;
  // Strip sender metadata envelope before any checks
  if (recallQuery) {
    recallQuery = stripRuntimeEnvelope(
      stripInlineTimestampPrefix(stripMetadataEnvelopes(recallQuery))
    );
  }
  if (
    !recallQuery ||
    typeof recallQuery !== "string" ||
    recallQuery.trim().length < 5 ||
    isMetadata(recallQuery)
  ) {
    recallQuery = prompt;
    // Strip metadata envelopes from prompt too, then check if anything useful remains
    if (recallQuery) {
      recallQuery = stripRuntimeEnvelope(
        stripInlineTimestampPrefix(stripMetadataEnvelopes(recallQuery))
      );
    }
    if (!recallQuery || recallQuery.length < 5) {
      return null;
    }

    // Strip envelope-formatted prompts from any channel
    let cleaned = recallQuery;

    // Remove leading "System: ..." lines (from prependSystemEvents)
    cleaned = cleaned.replace(/^(?:System:.*\n)+\n?/, "");

    // Remove session abort hint
    cleaned = cleaned.replace(/^Note: The previous agent run was aborted[^\n]*\n\n/, "");

    // Extract message after [ChannelName ...] envelope header
    const envelopeMatch = cleaned.match(/\[[A-Z][A-Za-z]*(?:\s[^\]]+)?\]\s*([\s\S]+)$/);
    if (envelopeMatch) {
      cleaned = envelopeMatch[1];
    }

    // Remove trailing [from: SenderName] metadata (group chats)
    cleaned = cleaned.replace(/\n\[from:[^\]]*\]\s*$/, "");

    // Strip metadata envelopes again after channel envelope extraction, in case
    // the metadata block appeared after the [ChannelName] header
    cleaned = stripRuntimeEnvelope(stripInlineTimestampPrefix(stripMetadataEnvelopes(cleaned)));

    recallQuery = cleaned.trim() || recallQuery;
  }

  const trimmed = recallQuery.trim();
  if (trimmed.length < 5 || isMetadata(trimmed)) return null;
  return trimmed;
}

export function composeRecallQuery(
  latestQuery: string,
  messages: any[] | undefined,
  recallContextTurns: number,
  recallRoles: Array<"user" | "assistant" | "system" | "tool"> = ["user", "assistant"]
): string {
  const latest = latestQuery.trim();
  if (recallContextTurns <= 1 || !Array.isArray(messages) || messages.length === 0) {
    return latest;
  }

  const allowedRoles = new Set(recallRoles);
  const contextualMessages = sliceLastTurnsByUserBoundary(messages, recallContextTurns);
  const contextLines = contextualMessages
    .map((msg: any) => {
      const role = msg?.role;
      if (!allowedRoles.has(role)) {
        return null;
      }

      let content = "";
      if (typeof msg?.content === "string") {
        content = msg.content;
      } else if (Array.isArray(msg?.content)) {
        content = msg.content
          .filter((block: any) => block?.type === "text" && typeof block?.text === "string")
          .map((block: any) => block.text)
          .join("\n");
      }

      content = stripMemoryTags(content).trim();
      content = stripMetadataEnvelopes(content);
      content = stripRuntimeEnvelope(stripInlineTimestampPrefix(content));
      if (!content) {
        return null;
      }
      if (role === "user" && content === latest) {
        return null;
      }
      return `${role}: ${content}`;
    })
    .filter((line: string | null): line is string => Boolean(line));

  if (contextLines.length === 0) {
    return latest;
  }

  return ["Prior context:", contextLines.join("\n"), latest].join("\n\n");
}

export function truncateRecallQuery(query: string, latestQuery: string, maxChars: number): string {
  if (maxChars <= 0) {
    return query;
  }

  const latest = latestQuery.trim();
  if (query.length <= maxChars) {
    return query;
  }

  const latestOnly = latest.length <= maxChars ? latest : latest.slice(0, maxChars);

  if (!query.includes("Prior context:")) {
    return latestOnly;
  }

  // New order: Prior context at top, latest user message at bottom.
  // Truncate by dropping oldest context lines first to preserve the suffix.
  const contextMarker = "Prior context:\n\n";
  const markerIndex = query.indexOf(contextMarker);
  if (markerIndex === -1) {
    return latestOnly;
  }

  const suffixMarker = "\n\n" + latest;
  const suffixIndex = query.lastIndexOf(suffixMarker);
  if (suffixIndex === -1) {
    return latestOnly;
  }

  const suffix = query.slice(suffixIndex); // \n\n<latest>
  if (suffix.length >= maxChars) {
    return latestOnly;
  }

  const contextBody = query.slice(markerIndex + contextMarker.length, suffixIndex);
  const contextLines = contextBody.split("\n").filter(Boolean);
  const keptContextLines: string[] = [];

  // Add context lines from newest (bottom) to oldest (top), stopping when we exceed maxChars
  for (let i = contextLines.length - 1; i >= 0; i--) {
    keptContextLines.unshift(contextLines[i]);
    const candidate = `${contextMarker}${keptContextLines.join("\n")}${suffix}`;
    if (candidate.length > maxChars) {
      keptContextLines.shift();
      break;
    }
  }

  if (keptContextLines.length > 0) {
    return `${contextMarker}${keptContextLines.join("\n")}${suffix}`;
  }

  return latestOnly;
}

/**
 * Parse the OpenClaw sessionKey to extract context fields.
 * Format: "agent:{agentId}:{provider}:{channelType}:{channelId}[:{extra}]"
 * Example: "agent:c0der:telegram:group:-1003825475854:topic:42"
 */
// Some OpenClaw hook contexts populate `ctx.channelId` with the provider name
// (e.g. "discord") instead of the actual channel ID. Treat those as missing so
// we fall through to the sessionKey-derived channel. See issue #854.
const PROVIDER_CHANNEL_ID_TOKENS = new Set([
  "discord",
  "telegram",
  "slack",
  "matrix",
  "whatsapp",
  "signal",
  "messenger",
  "sms",
  "email",
  "web",
  "cli",
]);

function sanitizeChannelId(channelId: string | undefined, provider?: string): string | undefined {
  if (!channelId) return undefined;
  if (provider && channelId === provider) return undefined;
  if (PROVIDER_CHANNEL_ID_TOKENS.has(channelId.toLowerCase())) return undefined;
  return channelId;
}

export interface ParsedSessionKey {
  agentId?: string;
  provider?: string;
  channel?: string;
}

export function parseSessionKey(sessionKey: string): ParsedSessionKey {
  const parts = sessionKey.split(":");
  if (parts[0] !== "agent") return {};
  if (parts.length === 3 && parts[2] === "main") {
    return {
      agentId: parts[1],
      provider: "main",
      channel: "main",
    };
  }
  // OpenClaw's Control UI creates `agent:<id>:dashboard:<opaque-id>` keys.
  // Recover only the agent identity: "dashboard" is a session namespace, not
  // the live message provider used for session metadata.
  if (parts.length === 4 && parts[2] === "dashboard") {
    return {
      agentId: parts[1],
    };
  }
  if (parts.length >= 4 && ["cron", "heartbeat", "subagent"].includes(parts[2])) {
    return {
      agentId: parts[1],
      provider: parts[2],
      channel: parts.slice(3).join(":"),
    };
  }
  if (parts.length < 5) return {};
  // parts[1] = agentId, parts[2] = provider, parts[3] = channelType, parts[4..] = channelId + extras
  return {
    agentId: parts[1],
    provider: parts[2],
    // Rejoin from channelType onward as the channel identifier (e.g. "group:-1003825475854:topic:42")
    channel: parts.slice(3).join(":"),
  };
}

export function extractTelegramDirectSenderId(channelId: string | undefined): string | undefined {
  if (typeof channelId !== "string") return undefined;
  const match = channelId.match(/^direct:([^:]+)$/);
  return match?.[1];
}

export function resolveSessionIdentity(
  ctx: PluginHookAgentContext | undefined
): PluginHookAgentContext | undefined {
  if (!ctx) return undefined;

  const sessionParsed = ctx.sessionKey ? parseSessionKey(ctx.sessionKey) : {};
  const messageProvider = ctx.messageProvider || sessionParsed.provider;
  const channelId = ctx.channelId || sessionParsed.channel;
  // direct:<id> channel ids carry the user id for any provider (telegram, msteams, …).
  const senderId = ctx.senderId || extractTelegramDirectSenderId(channelId);

  return {
    ...ctx,
    agentId: ctx.agentId || sessionParsed.agentId,
    messageProvider,
    channelId,
    senderId,
  };
}

function retryableSkipReason(
  detail: "missing stable message provider" | "missing stable sender identity"
): IdentitySkipReason {
  return { kind: "retryable", detail };
}

function finalSkipReason(detail: string): IdentitySkipReason {
  return { kind: "final", detail };
}

function formatIdentitySkipReason(reason: IdentitySkipReason | undefined): string | undefined {
  return reason?.detail;
}

function isRetryableIdentitySkipReason(reason: IdentitySkipReason | undefined): boolean {
  return reason?.kind === "retryable";
}

/**
 * Log an identity-skip event at info level, throttled to once per session key
 * per process lifetime. This makes silent skips visible to operators without
 * flooding the log on every turn.
 */
function logSkipOnce(
  operation: "recall" | "retain" | "dispatch",
  sessionKey: string | undefined,
  reason: IdentitySkipReason
): void {
  if (!sessionKey) return;
  const cacheKey = `${operation}:${sessionKey}`;
  if (loggedSkipSessions.has(cacheKey)) return;
  loggedSkipSessions.add(cacheKey);
  log.info(`Skipping ${operation} on session '${sessionKey}': ${reason.detail}`);
}

function cacheSessionIdentity(
  sessionKey: string | undefined,
  resolvedCtx: PluginHookAgentContext | undefined
): void {
  if (!sessionKey || !resolvedCtx) return;
  if (!resolvedCtx.messageProvider && !resolvedCtx.channelId && !resolvedCtx.senderId) return;

  setCappedMapValue(sessionIdentityBySession, sessionKey, {
    senderId: resolvedCtx.senderId,
    messageProvider: resolvedCtx.messageProvider,
    channelId: resolvedCtx.channelId,
  });
}

export interface ResolveAndCacheIdentityOptions {
  sessionKey?: string;
  ctx?: PluginHookAgentContext;
  senderIdHint?: string;
  dispatchChannel?: string;
}

export function resolveAndCacheIdentity(options: ResolveAndCacheIdentityOptions): {
  effectiveCtx: PluginHookAgentContext | undefined;
  resolvedCtx: PluginHookAgentContext | undefined;
  skipReason?: IdentitySkipReason;
} {
  const sessionKey = options.sessionKey ?? options.ctx?.sessionKey;
  const parsedSession = sessionKey ? parseSessionKey(sessionKey) : {};
  const cachedIdentity = sessionKey ? sessionIdentityBySession.get(sessionKey) : undefined;
  const baseCtx =
    options.ctx || (sessionKey ? ({ sessionKey } as PluginHookAgentContext) : undefined);
  // "main" is the synthetic provider produced by parseSessionKey for default
  // `agent:<id>:main` sessions — the *real* dispatch surface (telegram,
  // webchat, qqbot, …) is whatever the dispatcher provides. Treat it as if
  // the session key carried no provider so the dispatchChannel flows through
  // as the effective surface for downstream identity resolution. (#1541)
  const sessionProvider =
    parsedSession.provider && parsedSession.provider !== "main"
      ? parsedSession.provider
      : undefined;
  const effectiveCtx =
    baseCtx || cachedIdentity || options.senderIdHint || options.dispatchChannel || sessionKey
      ? {
          ...baseCtx,
          sessionKey: baseCtx?.sessionKey || sessionKey,
          agentId: baseCtx?.agentId || parsedSession.agentId,
          messageProvider: baseCtx?.messageProvider ?? cachedIdentity?.messageProvider,
          channelId: baseCtx?.channelId ?? cachedIdentity?.channelId,
          senderId: baseCtx?.senderId || cachedIdentity?.senderId || options.senderIdHint,
        }
      : undefined;
  const resolvedCtx = resolveSessionIdentity(
    effectiveCtx
      ? {
          ...effectiveCtx,
          messageProvider:
            effectiveCtx.messageProvider ?? sessionProvider ?? options.dispatchChannel,
          channelId: effectiveCtx.channelId ?? parsedSession.channel,
        }
      : undefined
  );

  const { resolvedCtx: identityCtx, reason: skipReason } = getIdentitySkipReason(resolvedCtx);
  cacheSessionIdentity(sessionKey, identityCtx);
  if (sessionKey) {
    if (skipReason) {
      setCappedMapValue(skipContextBaseTurnBySession, sessionKey, skipReason);
    } else {
      skipContextBaseTurnBySession.delete(sessionKey);
    }
  }

  return { effectiveCtx, resolvedCtx: identityCtx, skipReason };
}

export function getIdentitySkipReason(ctx: PluginHookAgentContext | undefined): {
  resolvedCtx: PluginHookAgentContext | undefined;
  reason?: IdentitySkipReason;
} {
  const resolvedCtx = resolveSessionIdentity(ctx);
  const sessionKey = resolvedCtx?.sessionKey;
  if (typeof sessionKey === "string") {
    if (/^agent:[^:]+:(cron|heartbeat|subagent):/.test(sessionKey)) {
      return { resolvedCtx, reason: finalSkipReason(`operational session ${sessionKey}`) };
    }
    if (/^temp:/.test(sessionKey)) {
      return { resolvedCtx, reason: finalSkipReason(`ephemeral temp session ${sessionKey}`) };
    }
  }

  const operationalProviders = ["cron", "heartbeat", "subagent"];
  if (resolvedCtx?.messageProvider && operationalProviders.includes(resolvedCtx.messageProvider)) {
    return {
      resolvedCtx,
      reason: finalSkipReason(`operational provider ${resolvedCtx.messageProvider}`),
    };
  }
  if (!resolvedCtx?.messageProvider || resolvedCtx.messageProvider === "unknown") {
    return { resolvedCtx, reason: retryableSkipReason("missing stable message provider") };
  }
  if (!resolvedCtx?.senderId || resolvedCtx.senderId === "anonymous") {
    if (resolvedCtx?.agentId) {
      resolvedCtx.senderId = `agent-user:${resolvedCtx.agentId}`;
    } else {
      return { resolvedCtx, reason: retryableSkipReason("missing stable sender identity") };
    }
  }
  if (
    resolvedCtx.messageProvider === "telegram" &&
    typeof resolvedCtx.channelId === "string" &&
    resolvedCtx.channelId.startsWith("direct:")
  ) {
    const directSenderId = extractTelegramDirectSenderId(resolvedCtx.channelId);
    if (!directSenderId || directSenderId !== resolvedCtx.senderId) {
      return {
        resolvedCtx,
        reason: finalSkipReason(
          `telegram direct identity mismatch (${resolvedCtx.channelId} vs ${resolvedCtx.senderId})`
        ),
      };
    }
  }

  return { resolvedCtx, reason: undefined };
}

export function isEphemeralOperationalText(text: string | undefined): boolean {
  if (!text || typeof text !== "string") return false;

  const normalized = text
    .replace(/\[role:\s*[^\]]+\]\s*/gi, "")
    .replace(/\[[a-z]+:end\]\s*/gi, "")
    .trim();

  // These prefixes are OpenClaw-generated operational/session-bootstrap strings,
  // not user-authored content, so they should not create recall/retain entries.
  return [
    /^A new session was started via \/(?:new|reset)\./i,
    /^Based on this conversation, generate a short 1-2/i,
    /^This (?:script|task|job|workflow) updates .* index/i,
  ].some((pattern) => pattern.test(normalized));
}

function setCappedMapValue<K, V>(map: Map<K, V>, key: K, value: V): void {
  // FIFO cap, not LRU: updating an existing key keeps its original insertion order.
  map.set(key, value);
  if (map.size > MAX_TRACKED_SESSIONS) {
    const oldest = map.keys().next().value;
    if (oldest) map.delete(oldest);
  }
}

/** Use the configured Bank verbatim; session identity never selects or creates a Bank. */
export function deriveBankId(
  _ctx: PluginHookAgentContext | undefined,
  pluginConfig: PluginConfig
): string {
  const bankId = getConfiguredBankId(pluginConfig);
  if (!bankId) {
    throw new Error(
      "ContextBase Bank ID is required; configure bankId with an existing authorized Bank."
    );
  }
  return bankId;
}

/**
 * Render the event window a memory carries. `mentioned_at` says when the fact
 * was stated; `occurred_start`/`occurred_end` say when the event itself
 * happened, which is what the agent needs to order past events against each
 * other. Either bound can be absent, so each case gets its own wording rather
 * than an open-ended range the model has to guess at.
 */
function formatOccurredWindow(
  start: string | null | undefined,
  end: string | null | undefined
): string {
  if (start && end) {
    return start === end ? ` [occurred: ${start}]` : ` [occurred: ${start} → ${end}]`;
  }
  if (start) return ` [occurred from: ${start}]`;
  if (end) return ` [occurred until: ${end}]`;
  return "";
}

export function formatMemories(results: MemoryResult[]): string {
  if (!results || results.length === 0) return "";
  return results
    .map((r) => {
      const type = r.type ? ` [${r.type}]` : "";
      const date = r.mentioned_at ? ` (${r.mentioned_at})` : "";
      const occurred = formatOccurredWindow(r.occurred_start, r.occurred_end);
      const doc = r.document_id ? ` [doc:${r.document_id}]` : "";
      return `- ${r.text}${type}${date}${occurred}${doc}`;
    })
    .join("\n\n");
}

/**
 * Detect external ContextBase API configuration from plugin config.
 */
export function detectExternalApi(pluginConfig?: PluginConfig): {
  apiUrl: string | null;
  apiToken: string | null;
} {
  return {
    apiUrl: pluginConfig?.contextbaseApiUrl ?? null,
    apiToken: pluginConfig?.contextbaseApiToken ?? null,
  };
}

/** One explicit service endpoint for hooks, tools and capability probes. */
function getActiveApiEndpoint(): { apiUrl: string | null; apiToken: string | null } {
  return detectExternalApi(currentPluginConfig ?? undefined);
}

export function buildClientOptions(externalApi: {
  apiUrl: string | null;
  apiToken: string | null;
}): ContextBaseClientOptions {
  return { baseUrl: validateApiUrl(externalApi.apiUrl), apiKey: externalApi.apiToken ?? undefined };
}

export function validateApiUrl(value: string | null | undefined): string {
  if (!value?.trim())
    throw new Error("ContextBase API URL is required; configure contextbaseApiUrl.");
  const url = new URL(value);
  if (
    !["https:", "http:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error(
      "ContextBase API URL must be an HTTP(S) endpoint without credentials, query or fragment."
    );
  }
  return value.trim().replace(/\/+$/, "");
}

/**
 * Health check for external ContextBase API.
 * Retries up to 3 times with 2s delay — container DNS may not be ready on first boot.
 */
/**
 * Compare two semver-shaped strings ("0.5.0", "0.4.22"). Returns true when
 * `actual >= minimum`. Tolerates pre-release suffixes (treats them as the
 * same major.minor.patch as the bare version — good enough for capability
 * gating).
 */
export function meetsMinimumVersion(actual: string, minimum: string): boolean {
  const parse = (v: string): number[] =>
    v
      .split("-")[0]
      .split(".")
      .map((part) => Number.parseInt(part, 10))
      .map((n) => (Number.isFinite(n) ? n : 0));
  const a = parse(actual);
  const m = parse(minimum);
  for (let i = 0; i < Math.max(a.length, m.length); i++) {
    const av = a[i] ?? 0;
    const mv = m[i] ?? 0;
    if (av > mv) return true;
    if (av < mv) return false;
  }
  return true;
}

export interface ContextBaseApiCapabilities {
  version: string;
  storeDocumentText: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function parseContextBaseApiCapabilities(
  payload: unknown
): ContextBaseApiCapabilities | null {
  if (!isRecord(payload) || typeof payload.api_version !== "string") {
    return null;
  }

  let storeDocumentText = true;
  if ("features" in payload) {
    const features = payload.features;
    storeDocumentText = isRecord(features) && features.store_document_text === true;
  }

  return {
    version: payload.api_version,
    storeDocumentText,
  };
}

export function supportsAppendFromCapabilities(
  capabilities: ContextBaseApiCapabilities | null
): boolean {
  return (
    capabilities !== null &&
    capabilities.storeDocumentText &&
    meetsMinimumVersion(capabilities.version, MIN_VERSION_FOR_UPDATE_MODE_APPEND)
  );
}

export function supportsAsyncRetainOperationIdFromCapabilities(
  capabilities: ContextBaseApiCapabilities | null
): boolean {
  return asyncRetainOperationIdCapabilityFromCapabilities(capabilities) === "supported";
}

export function asyncRetainOperationIdCapabilityFromCapabilities(
  capabilities: ContextBaseApiCapabilities | null
): AsyncRetainOperationIdCapability {
  if (capabilities === null) {
    return "unknown";
  }
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(capabilities.version);
  // JavaScript's `$` can match before a final line terminator, so require the
  // matched text to consume the complete payload as well as canonical digits.
  if (!match || match[0] !== capabilities.version) {
    return "unknown";
  }
  return meetsMinimumVersion(capabilities.version, MIN_VERSION_FOR_ASYNC_RETAIN_OPERATION_ID)
    ? "supported"
    : "unsupported";
}

/**
 * Allocate the identity before the first asynchronous request so a failed
 * acknowledgement and every durable-queue replay refer to the same server operation.
 */
export function createAsyncRetainOperationId(): string {
  return randomUUID();
}

/**
 * Probe `<apiUrl>/version` once at service.start to learn the running
 * ContextBase API capabilities. Returns `null` (treated as "no append support")
 * if the endpoint is unreachable or returns malformed payload — conservative
 * fallback path is the right call when we can't be sure.
 */
async function fetchContextBaseApiCapabilities(
  apiUrl: string,
  apiToken?: string | null,
  serviceSignal?: globalThis.AbortSignal
): Promise<ContextBaseApiCapabilities | null> {
  const versionUrl = `${apiUrl.replace(/\/$/, "")}/version`;
  try {
    const headers: Record<string, string> = { "User-Agent": USER_AGENT };
    if (apiToken) headers["Authorization"] = `Bearer ${apiToken}`;
    const timeoutSignal = AbortSignal.timeout(5000);
    const response = await fetch(versionUrl, {
      signal: serviceSignal ? AbortSignal.any([serviceSignal, timeoutSignal]) : timeoutSignal,
      headers,
    });
    if (!response.ok) {
      debug(`[ContextBase] /version returned HTTP ${response.status}; assuming legacy`);
      return null;
    }
    const data = await response.json();
    const capabilities = parseContextBaseApiCapabilities(data);
    if (!capabilities) {
      debug(`[ContextBase] /version payload missing api_version; assuming legacy`);
    }
    return capabilities;
  } catch (error) {
    debug(`[ContextBase] /version probe failed: ${String(error)}; assuming legacy`);
    return null;
  }
}

export async function refreshAsyncRetainOperationIdCapability(
  apiUrl: string,
  apiToken?: string | null,
  expectedGeneration = serviceGeneration,
  signal: globalThis.AbortSignal | undefined = serviceAbortController?.signal
): Promise<AsyncRetainOperationIdCapability> {
  const capabilities = await fetchContextBaseApiCapabilities(apiUrl, apiToken, signal);
  const capability = asyncRetainOperationIdCapabilityFromCapabilities(capabilities);
  if (expectedGeneration !== serviceGeneration || signal?.aborted) return "unknown";
  asyncRetainOperationIdCapability = capability;
  return capability;
}

async function refreshQueueOperationIdCapability(
  expectedGeneration = serviceGeneration,
  signal: globalThis.AbortSignal | undefined = serviceAbortController?.signal
): Promise<AsyncRetainOperationIdCapability> {
  if (expectedGeneration !== serviceGeneration || signal?.aborted) return "unknown";
  if (!currentPluginConfig) {
    asyncRetainOperationIdCapability = "unknown";
    return "unknown";
  }
  const endpoint = getActiveApiEndpoint();
  if (!endpoint.apiUrl) {
    asyncRetainOperationIdCapability = "unknown";
    return "unknown";
  }
  return refreshAsyncRetainOperationIdCapability(
    endpoint.apiUrl,
    endpoint.apiToken,
    expectedGeneration,
    signal
  );
}

/**
 * Probe `/version` and update the module-level append and async-operation-id
 * capability flags. Logs a one-time WARN block when the append API is
 * older than 0.5.0 or cannot store document text — without
 * `update_mode: 'append'`, every retain on the same session id silently
 * overwrites prior turns server-side, and append itself requires stored
 * document text.
 *
 * Called wherever the plugin (re)connects to an API — external *and* local
 * service. It used to hang off the `checkExternalApiHealth` call sites only,
 * which is why local-daemon mode never probed at all and silently retained
 * with per-turn document ids. (#3686)
 */
async function detectAppendCapability(
  apiUrl: string,
  apiToken?: string | null,
  expectedGeneration = serviceGeneration,
  signal: globalThis.AbortSignal | undefined = serviceAbortController?.signal
): Promise<void> {
  const capabilities = await fetchContextBaseApiCapabilities(apiUrl, apiToken, signal);
  if (expectedGeneration !== serviceGeneration || signal?.aborted) return;
  const supported = supportsAppendFromCapabilities(capabilities);
  asyncRetainOperationIdCapability = asyncRetainOperationIdCapabilityFromCapabilities(capabilities);
  const transitionedToUnsupported = supportsUpdateModeAppend && !supported;
  const firstProbe = !appendCapabilityProbed;
  appendCapabilityProbed = true;
  supportsUpdateModeAppend = supported;
  if (supported && capabilities) {
    debug(
      `[ContextBase] API version ${capabilities.version} supports update_mode=append with stored document text`
    );
    return;
  }
  // Warn on the first probe when unsupported, and on any transition from
  // supported -> unsupported. Stay silent on subsequent re-probes that
  // confirm the same unsupported state.
  if (!firstProbe && !transitionedToUnsupported) return;
  const version = capabilities?.version ?? null;
  const reason =
    capabilities !== null &&
    meetsMinimumVersion(capabilities.version, MIN_VERSION_FOR_UPDATE_MODE_APPEND) &&
    !capabilities.storeDocumentText
      ? `reports version "${capabilities.version}" but has features.store_document_text disabled`
      : `reports version "${version ?? "unknown"}", which is older than ${MIN_VERSION_FOR_UPDATE_MODE_APPEND}`;
  log.warn(
    `[ContextBase] ⚠️  API at ${apiUrl} ${reason}. ` +
      `Falling back to per-turn document ids — each retain becomes its own document instead of accumulating into one per-session document. ` +
      `Enable document text storage on ContextBase ${MIN_VERSION_FOR_UPDATE_MODE_APPEND} or newer to use session-scoped retention with update_mode=append.`
  );
}

async function checkExternalApiHealth(apiUrl: string, apiToken?: string | null): Promise<void> {
  const healthUrl = `${apiUrl.replace(/\/$/, "")}/health`;
  const maxRetries = 3;
  const retryDelay = 2000;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      debug(
        `[ContextBase] Checking external API health at ${healthUrl}... (attempt ${attempt}/${maxRetries})`
      );
      const headers: Record<string, string> = { "User-Agent": USER_AGENT };
      if (apiToken) {
        headers["Authorization"] = `Bearer ${apiToken}`;
      }
      const response = await fetch(healthUrl, { signal: AbortSignal.timeout(10000), headers });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      const data = (await response.json()) as { status?: string };
      debug(`[ContextBase] External API health: ${JSON.stringify(data)}`);
      return;
    } catch (error) {
      if (attempt < maxRetries) {
        debug(
          `[ContextBase] Health check attempt ${attempt} failed, retrying in ${retryDelay}ms...`
        );
        await new Promise((resolve) => setTimeout(resolve, retryDelay));
      } else {
        throw new Error(`Cannot connect to external ContextBase API at ${apiUrl}: ${error}`, {
          cause: error,
        });
      }
    }
  }
}

export function normalizeRetainTags(value: unknown): string[] {
  if (value == null) return [];

  const rawItems = Array.isArray(value) ? value : typeof value === "string" ? value.split(",") : [];

  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const item of rawItems) {
    if (typeof item !== "string") continue;
    const tag = item.trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    normalized.push(tag);
  }
  return normalized;
}

export function getPluginConfig(api: MoltbotPluginAPI): PluginConfig {
  const config = api.config.plugins?.entries?.["contextbase-openclaw"]?.config || {};

  const senderPrefixPattern =
    typeof config.senderPrefixPattern === "string" && config.senderPrefixPattern.trim().length > 0
      ? config.senderPrefixPattern.trim()
      : undefined;
  // Arm the shared stripper used by every recall/retain text path (#3070).
  configureSenderPrefixStripping(senderPrefixPattern);

  // No default fallback for missions: if the user doesn't set one, the plugin
  // does not stamp anything. This lets per-bank missions written via the API
  // (PATCH /banks/{id}) survive gateway restarts. (#1270)
  return {
    bankMission:
      typeof config.bankMission === "string" && config.bankMission.length > 0
        ? config.bankMission
        : undefined,
    retainMission:
      typeof config.retainMission === "string" && config.retainMission.length > 0
        ? config.retainMission
        : undefined,
    observationsMission:
      typeof config.observationsMission === "string" && config.observationsMission.length > 0
        ? config.observationsMission
        : undefined,
    retainExtractionMode: normalizeRetainExtractionMode(config.retainExtractionMode),
    enableObservations:
      typeof config.enableObservations === "boolean" ? config.enableObservations : undefined,
    enableAutoConsolidation:
      typeof config.enableAutoConsolidation === "boolean"
        ? config.enableAutoConsolidation
        : undefined,
    dispositionSkepticism: normalizeDispositionTrait(config.dispositionSkepticism),
    dispositionLiteralism: normalizeDispositionTrait(config.dispositionLiteralism),
    dispositionEmpathy: normalizeDispositionTrait(config.dispositionEmpathy),
    entityLabels: normalizeEntityLabels(config.entityLabels),
    contextbaseApiUrl: config.contextbaseApiUrl,
    contextbaseApiToken: config.contextbaseApiToken,
    bankId:
      typeof config.bankId === "string" && config.bankId.trim().length > 0
        ? config.bankId.trim()
        : undefined,
    retainTags: normalizeRetainTags(config.retainTags),
    retainSource:
      typeof config.retainSource === "string" && config.retainSource.trim().length > 0
        ? config.retainSource.trim()
        : undefined,
    retainContext:
      typeof config.retainContext === "string" && config.retainContext.trim().length > 0
        ? config.retainContext.trim()
        : DEFAULT_RETAIN_CONTEXT,
    excludeProviders: Array.isArray(config.excludeProviders)
      ? Array.from(
          new Set([
            "heartbeat",
            ...config.excludeProviders.filter(
              (provider): provider is string => typeof provider === "string"
            ),
          ])
        )
      : ["heartbeat"],
    autoRecall: config.autoRecall !== false, // Default: true (on) — backward compatible
    autoRetain: config.autoRetain !== false, // Default: true
    retainRoles: Array.isArray(config.retainRoles) ? config.retainRoles : undefined,
    retainFormat: config.retainFormat === "text" ? "text" : "json",
    retainToolCalls: config.retainToolCalls !== false,
    recallBudget: config.recallBudget || "mid",
    recallMaxTokens: config.recallMaxTokens || 1024,
    recallTypes: Array.isArray(config.recallTypes) ? config.recallTypes : ["observation"],
    preferObservations: config.preferObservations === true, // Default: false — backward compatible
    recallMinScores: config.recallMinScores,
    recallRoles: Array.isArray(config.recallRoles) ? config.recallRoles : ["user", "assistant"],
    retainEveryNTurns:
      typeof config.retainEveryNTurns === "number" && config.retainEveryNTurns >= 1
        ? config.retainEveryNTurns
        : 1,
    retainOverlapTurns:
      typeof config.retainOverlapTurns === "number" && config.retainOverlapTurns >= 0
        ? config.retainOverlapTurns
        : 0,
    recallTopK: typeof config.recallTopK === "number" ? config.recallTopK : undefined,
    recallContextTurns:
      typeof config.recallContextTurns === "number" && config.recallContextTurns >= 1
        ? config.recallContextTurns
        : 1,
    recallMaxQueryChars:
      typeof config.recallMaxQueryChars === "number" && config.recallMaxQueryChars >= 1
        ? config.recallMaxQueryChars
        : 800,
    recallPromptPreamble:
      typeof config.recallPromptPreamble === "string" &&
      config.recallPromptPreamble.trim().length > 0
        ? config.recallPromptPreamble
        : DEFAULT_RECALL_PROMPT_PREAMBLE,
    recallInjectionPosition:
      typeof config.recallInjectionPosition === "string" &&
      ["prepend", "append", "user"].includes(config.recallInjectionPosition)
        ? (config.recallInjectionPosition as PluginConfig["recallInjectionPosition"])
        : "user",
    recallTimeoutMs:
      typeof config.recallTimeoutMs === "number" && config.recallTimeoutMs >= 1000
        ? config.recallTimeoutMs
        : undefined,
    ignoreSessionPatterns: Array.isArray(config.ignoreSessionPatterns)
      ? config.ignoreSessionPatterns
      : [],
    statelessSessionPatterns: Array.isArray(config.statelessSessionPatterns)
      ? config.statelessSessionPatterns
      : [],
    skipStatelessSessions: config.skipStatelessSessions !== false,
    debug: config.debug ?? false,
    debugPerfTiming: config.debugPerfTiming === true,
    // Both were missing from this whitelist, so the logger always ran at
    // `info` with a 5-minute summary whatever the user configured.
    logLevel:
      config.logLevel && ["off", "error", "warning", "info", "debug"].includes(config.logLevel)
        ? config.logLevel
        : undefined,
    logSummaryIntervalMs:
      typeof config.logSummaryIntervalMs === "number" && config.logSummaryIntervalMs >= 0
        ? config.logSummaryIntervalMs
        : undefined,
    // Retain queue: kept off the strict whitelist before — user values were
    // silently dropped before queue init read them. (#1443)
    retainQueuePath:
      typeof config.retainQueuePath === "string" && config.retainQueuePath.trim().length > 0
        ? config.retainQueuePath
        : undefined,
    retainQueueMaxAgeMs:
      typeof config.retainQueueMaxAgeMs === "number" ? config.retainQueueMaxAgeMs : undefined,
    retainQueueFlushIntervalMs:
      typeof config.retainQueueFlushIntervalMs === "number" && config.retainQueueFlushIntervalMs > 0
        ? config.retainQueueFlushIntervalMs
        : undefined,
    senderPrefixPattern,
  };
}

// Registration guard: WeakSet keyed by api instance to prevent double-registration
// on the same api object while allowing fresh registration on new api objects.
// Does not reintroduce issue #1029 because WeakSet.has() checks object identity,
// not a module-level boolean.
const _registeredApis = new WeakSet<MoltbotPluginAPI>();

export default function (api: MoltbotPluginAPI) {
  if (_registeredApis.has(api)) {
    debug("[ContextBase] Plugin entry skipped (this api instance already registered)");
    return;
  }
  _registeredApis.add(api);
  try {
    log.info("plugin entry invoked");
    debug("[ContextBase] Plugin loading...");

    // Get plugin config first (needed for debug flag and service registration)
    const pluginConfig = getPluginConfig(api);
    // If logLevel is 'debug', also enable legacy debug flag
    // `debug` is always a boolean here (getPluginConfig defaults it, and so does
    // the schema), so `??` never reached logLevel and `logLevel: "debug"` was a no-op.
    debugEnabled = pluginConfig.debug === true || pluginConfig.logLevel === "debug";

    // Configure structured logger — route through OpenClaw's api.logger for consistent formatting
    if (api.logger) setApiLogger(api.logger);
    configureLogger({
      logLevel: pluginConfig.logLevel ?? (pluginConfig.debug ? "debug" : "info"),
      logSummaryIntervalMs: pluginConfig.logSummaryIntervalMs,
    });

    // Store config globally for explicit Bank selection in hooks
    currentPluginConfig = pluginConfig;

    debug("[ContextBase] Plugin loaded successfully (deferred heavy init to gateway start)");

    // Register background service for cleanup
    // IMPORTANT: Heavy initialization (API connection and capability checks)
    // happens in service.start() which is ONLY called on gateway start,
    // not on every CLI command.
    debug("[ContextBase] Registering service...");
    log.info("registering plugin service");
    api.registerService({
      id: "contextbase-memory",
      async start() {
        preServiceController.abort();
        serviceAbortController?.abort();
        inflightRecalls.clear();
        const serviceController = new AbortController();
        serviceAbortController = serviceController;
        const startGeneration = ++serviceGeneration;
        log.info("service.start invoked");
        debug("[ContextBase] Service start called - beginning heavy initialization...");

        deriveBankId(undefined, pluginConfig);
        const externalApi = detectExternalApi(pluginConfig);
        // Validate before starting timers or making any request; never discover or start an engine.
        client = null;
        isInitialized = false;
        const options = buildClientOptions(externalApi);
        clientOptions = options;
        initRetainQueue(pluginConfig, startGeneration, serviceController.signal);
        initPromise = (async () => {
          await checkExternalApiHealth(options.baseUrl, externalApi.apiToken);
          if (serviceController.signal.aborted || startGeneration !== serviceGeneration) return;
          await detectAppendCapability(options.baseUrl, externalApi.apiToken);
          if (serviceController.signal.aborted || startGeneration !== serviceGeneration) return;
          banksWithDefaultsApplied.clear();
          client = new ContextBaseClient(options);
          const bankId = deriveBankId(undefined, pluginConfig);
          await ensureBankDefaultsApplied(bankId, pluginConfig);
          if (serviceController.signal.aborted || startGeneration !== serviceGeneration) return;
          isInitialized = true;
          log.info(
            `initialized (mode: remote API, bank: ${bankId}, autoRecall: ${pluginConfig.autoRecall !== false}, autoRetain: ${pluginConfig.autoRetain !== false})`
          );
        })();
        try {
          await initPromise;
        } catch (error) {
          client = null;
          isInitialized = false;
          log.error(
            "ContextBase initialization failed; hooks will retry the configured API",
            error
          );
        }
      },

      async stop() {
        try {
          serviceGeneration++;
          preServiceController.abort();
          serviceAbortController?.abort();
          serviceAbortController = null;
          inflightRecalls.clear();
          debug("[ContextBase] Service stopping...");

          // Close retain queue
          if (retainQueueFlushTimer) {
            clearInterval(retainQueueFlushTimer);
            retainQueueFlushTimer = null;
          }
          if (retainQueue) {
            const pending = retainQueue.size();
            if (pending > 0) {
              debug(
                `[ContextBase] Service stopping with ${pending} queued retains (will resume on next start)`
              );
            }
            retainQueue.close();
            retainQueue = null;
          }

          client = null;
          clientOptions = null;
          asyncRetainOperationIdCapability = "unknown";
          banksWithDefaultsApplied.clear();
          isInitialized = false;

          stopLogger();
          debug("[ContextBase] Service stopped");
        } catch (error) {
          log.error("service stop error", error);
          throw error;
        }
      },
    });

    debug("[ContextBase] Plugin loaded successfully");

    // Register agent hooks for auto-recall and auto-retention.
    //
    // Why no module-level "already registered" guard: each plugin entry invocation
    // hands us a fresh `api` tied to a specific plugin registry. OpenClaw may call
    // the plugin entry multiple times per process (CLI vs gateway vs lazy reloads),
    // and the registry that's active when an agent actually runs is not guaranteed
    // to be the first one we saw. A process-global flag would let the first call
    // "win" and leave subsequent registries with zero contextbase hooks — which is
    // exactly how auto-recall/auto-retain silently stopped firing in 0.6.x.
    debug("[ContextBase] Registering agent hooks...");
    log.info("registering agent hooks");

    // Inbound identity capture: cache the sender and dispatch surface per session
    // before the agent runs, for banks keyed by user or channel.
    //
    // This used `before_dispatch`, which carries the same fields. OpenClaw refuses
    // to start or resume a Goal while any plugin holds `before_dispatch` (it can't
    // replay it after a restart), so the plugin blocked Goals. `message_received`
    // fires earlier on the same inbound path and is not on that list. (#5177)
    api.on("message_received", async (event: any, ctx?: PluginHookAgentContext) => {
      try {
        const sessionKey =
          ctx?.sessionKey ?? (typeof event?.sessionKey === "string" ? event.sessionKey : undefined);
        if (!sessionKey) {
          return;
        }

        // A message hook's channelId is the surface ("telegram", "webchat").
        const dispatchChannel =
          (typeof ctx?.channelId === "string" ? ctx.channelId : undefined) ||
          ctx?.messageProvider ||
          parseSessionKey(sessionKey).provider;
        const { resolvedCtx, skipReason } = resolveAndCacheIdentity({
          sessionKey,
          ctx: {
            ...ctx,
            sessionKey,
            senderId:
              (typeof event?.senderId === "string" ? event.senderId : undefined) || ctx?.senderId,
          },
          dispatchChannel,
        });

        if (skipReason) {
          debug(
            `[ContextBase] message_received marked session ${sessionKey} to skip this turn: ${formatIdentitySkipReason(skipReason)}`
          );
          logSkipOnce("dispatch", sessionKey, skipReason);
          return;
        }
        if (!resolvedCtx?.senderId || typeof resolvedCtx.senderId !== "string") {
          return;
        }

        debug(
          `[ContextBase] message_received cached identity for ${sessionKey}: ${resolvedCtx.messageProvider}/${resolvedCtx.channelId} sender=${resolvedCtx.senderId}`
        );
      } catch (error) {
        log.warn(`message_received identity cache error: ${error}`);
      }
    });

    // No `before_agent_start` registration: the callback used to call
    // `resolveAndCacheIdentity()` and emit a debug log, but `message_received`
    // already populates the identity cache earlier in the inbound path,
    // `before_prompt_build` re-resolves before recall (and can infer
    // `senderId` from prompt content when ctx is missing it), and `agent_end`
    // re-resolves before retain. Subscribing here was duplicate work on the
    // hot path. (#1354)

    // Auto-recall: Inject relevant memories before agent processes the message
    // Hook signature: (event, ctx) where event has {prompt, messages?} and ctx has agent context
    api.on("before_prompt_build", async (event: any, ctx?: PluginHookAgentContext) => {
      const recallLifecycle = captureHookLifecycle();
      const isCurrentRecall = recallLifecycle.isCurrent;
      if (!isCurrentRecall()) return;
      // Optional perf instrumentation (#1406). Captured here at hook entry so
      // the early-return paths below don't influence the measurement of slow
      // recall calls — perf lines are only emitted on the recall path.
      const perfHookStart = pluginConfig.debugPerfTiming ? Date.now() : 0;
      try {
        // Check if this provider is excluded
        if (ctx?.messageProvider && pluginConfig.excludeProviders?.includes(ctx.messageProvider)) {
          debug(`[ContextBase] Skipping recall for excluded provider: ${ctx.messageProvider}`);
          return;
        }

        // Session pattern filtering
        const sessionKey = ctx?.sessionKey;
        if (sessionKey) {
          const ignorePatterns = compileSessionPatterns(pluginConfig.ignoreSessionPatterns ?? []);
          if (ignorePatterns.length > 0 && matchesSessionPattern(sessionKey, ignorePatterns)) {
            debug(
              `[ContextBase] Skipping recall: session '${sessionKey}' matches ignoreSessionPatterns`
            );
            return;
          }
          const skipStateless = pluginConfig.skipStatelessSessions !== false;
          if (skipStateless) {
            const statelessPatterns = compileSessionPatterns(
              pluginConfig.statelessSessionPatterns ?? []
            );
            if (
              statelessPatterns.length > 0 &&
              matchesSessionPattern(sessionKey, statelessPatterns)
            ) {
              debug(
                `[ContextBase] Skipping recall: session '${sessionKey}' matches statelessSessionPatterns (skipStatelessSessions=true)`
              );
              return;
            }
          }
        }

        // Skip auto-recall when disabled (agent has its own recall tool)
        if (!pluginConfig.autoRecall) {
          debug("[ContextBase] Auto-recall disabled via config, skipping");
          return;
        }

        const sessionKeyForCache =
          ctx?.sessionKey ?? (typeof event?.sessionKey === "string" ? event.sessionKey : undefined);
        const skipTurnReason = sessionKeyForCache
          ? skipContextBaseTurnBySession.get(sessionKeyForCache)
          : undefined;
        if (skipTurnReason && !isRetryableIdentitySkipReason(skipTurnReason)) {
          debug(
            `[ContextBase] Skipping recall for session ${sessionKeyForCache}: ${formatIdentitySkipReason(skipTurnReason)}`
          );
          logSkipOnce("recall", sessionKeyForCache, skipTurnReason);
          return;
        }

        const senderIdFromPrompt = !ctx?.senderId
          ? extractSenderIdFromText(event.prompt ?? event.rawMessage ?? "")
          : undefined;
        const { resolvedCtx: resolvedCtxForRecall, skipReason: identitySkipReason } =
          resolveAndCacheIdentity({
            sessionKey: sessionKeyForCache,
            ctx,
            senderIdHint: senderIdFromPrompt,
          });
        if (identitySkipReason) {
          debug(
            `[ContextBase] Skipping recall for session ${sessionKeyForCache}: ${formatIdentitySkipReason(identitySkipReason)}`
          );
          logSkipOnce("recall", sessionKeyForCache, identitySkipReason);
          return;
        }

        const bankId = deriveBankId(resolvedCtxForRecall, pluginConfig);
        debug(
          `[ContextBase] before_prompt_build - bank: ${bankId}, channel: ${resolvedCtxForRecall?.messageProvider}/${resolvedCtxForRecall?.channelId}`
        );
        debug(`[ContextBase] event keys: ${Object.keys(event).join(", ")}`);
        debug(`[ContextBase] event.context keys: ${Object.keys(event.context ?? {}).join(", ")}`);

        // Get the user's latest message for recall — only the raw user text, not the full prompt
        // rawMessage is clean user text; prompt includes envelope, system events, media notes, etc.
        debug(
          `[ContextBase] extractRecallQuery input lengths - raw: ${event.rawMessage?.length ?? 0}, prompt: ${event.prompt?.length ?? 0}`
        );
        const extracted = extractRecallQuery(event.rawMessage, event.prompt);
        if (!extracted) {
          debug("[ContextBase] extractRecallQuery returned null, skipping recall");
          return;
        }
        if (isEphemeralOperationalText(extracted)) {
          debug("[ContextBase] Recall query is operational/ephemeral noise, skipping recall");
          return;
        }
        debug(`[ContextBase] extractRecallQuery result length: ${extracted.length}`);
        const recallContextTurns = pluginConfig.recallContextTurns ?? 1;
        const recallMaxQueryChars = pluginConfig.recallMaxQueryChars ?? 800;
        const sessionMessages = event.context?.sessionEntry?.messages ?? event.messages ?? [];
        const messageCount = sessionMessages.length;
        debug(
          `[ContextBase] event.messages count: ${messageCount}, roles: ${sessionMessages.map((m: any) => m.role).join(",")}`
        );
        if (recallContextTurns > 1 && messageCount === 0) {
          debug(
            "[ContextBase] recallContextTurns > 1 but event.messages is empty — prior context unavailable at before_agent_start for this provider"
          );
        }
        const recallRoles = pluginConfig.recallRoles ?? ["user", "assistant"];
        const composedPrompt = composeRecallQuery(
          extracted,
          sessionMessages,
          recallContextTurns,
          recallRoles
        );
        let prompt = truncateRecallQuery(composedPrompt, extracted, recallMaxQueryChars);

        // Final defensive cap
        if (prompt.length > recallMaxQueryChars) {
          prompt = prompt.substring(0, recallMaxQueryChars);
        }

        // Wait for client to be ready
        const clientGlobal = (global as any).__contextbaseClient;
        if (!clientGlobal) {
          debug("[ContextBase] Client global not available, skipping auto-recall");
          return;
        }

        await clientGlobal.waitForReady();
        if (!isCurrentRecall()) return;

        // Get client configured for this context's bank (async to handle mission setup)
        const client = await clientGlobal.getClientForContext(resolvedCtxForRecall);
        if (!isCurrentRecall()) return;
        if (!client) {
          debug("[ContextBase] Client not initialized, skipping auto-recall");
          return;
        }

        debug(`[ContextBase] Auto-recall for bank ${bankId}, full query:\n---\n${prompt}\n---`);

        // Recall with deduplication: reuse in-flight request for same bank
        const normalizedPrompt = prompt.trim().toLowerCase().replace(/\s+/g, " ");
        const queryHash = createHash("sha256").update(normalizedPrompt).digest("hex").slice(0, 16);
        const recallKey = `${bankId}::${queryHash}`;
        const existing = inflightRecalls.get(recallKey);
        let recallPromise: Promise<RecallResponse>;
        if (existing) {
          debug(`[ContextBase] Reusing in-flight recall for bank ${bankId}`);
          recallPromise = existing;
        } else {
          const recallTimeoutMs = pluginConfig.recallTimeoutMs ?? DEFAULT_RECALL_TIMEOUT_MS;
          recallPromise = client.recall(
            {
              query: prompt,
              maxTokens: pluginConfig.recallMaxTokens || 1024,
              budget: pluginConfig.recallBudget,
              types: pluginConfig.recallTypes,
              preferObservations: pluginConfig.preferObservations,
              minScores: pluginConfig.recallMinScores,
            },
            recallTimeoutMs,
            recallLifecycle.signal
          );
          inflightRecalls.set(recallKey, recallPromise);
          void recallPromise
            .catch(() => {})
            .finally(() => {
              // An old generation can settle after start() installed a successor.
              if (inflightRecalls.get(recallKey) === recallPromise)
                inflightRecalls.delete(recallKey);
            });
        }

        const recallStart = pluginConfig.debugPerfTiming ? Date.now() : 0;
        const response = await recallPromise;
        if (!isCurrentRecall()) return;
        const recallElapsedMs = pluginConfig.debugPerfTiming ? Date.now() - recallStart : 0;

        if (!response.results || response.results.length === 0) {
          if (pluginConfig.debugPerfTiming) {
            log.info(
              formatHookPerf("before_prompt_build", Date.now() - perfHookStart, {
                recall_main: `${recallElapsedMs}ms`,
                source: existing ? "reused" : "fresh",
                results: 0,
              })
            );
          }
          debug("[ContextBase] No memories found for auto-recall");
          return;
        }

        debug(
          `[ContextBase] Raw recall response (${response.results.length} results before topK):\n${response.results.map((r: any, i: number) => `  [${i}] score=${r.score?.toFixed(3) ?? "n/a"} type=${r.type ?? "n/a"}: ${JSON.stringify(r.content ?? r.text ?? r).substring(0, 200)}`).join("\n")}`
        );

        const results = pluginConfig.recallTopK
          ? response.results.slice(0, pluginConfig.recallTopK)
          : response.results;

        debug(
          `[ContextBase] After topK (${pluginConfig.recallTopK ?? "unlimited"}): ${results.length} results injected`
        );

        // Format memories as a bullet list (text + type + date + occurred window +
        // [doc:<document_id>], each part present only when the memory carries it)
        const memoriesFormatted = formatMemories(results);

        const contextMessage = `<contextbase_memories>
${pluginConfig.recallPromptPreamble || DEFAULT_RECALL_PROMPT_PREAMBLE}
Current time - ${formatCurrentTimeForRecall()}

${memoriesFormatted}
</contextbase_memories>`;

        debug(
          `[ContextBase] Auto-recall: Injecting ${results.length} memories from bank ${bankId}`
        );
        log.info(`injecting ${results.length} memories into context (bank: ${bankId})`);
        log.trackRecall(bankId, results.length);

        if (pluginConfig.debugPerfTiming) {
          log.info(
            formatHookPerf("before_prompt_build", Date.now() - perfHookStart, {
              recall_main: `${recallElapsedMs}ms`,
              source: existing ? "reused" : "fresh",
              results: results.length,
            })
          );
        }

        // Keep recalled memories outside the system prompt by default so the
        // provider can reuse its stable prompt prefix across turns. Users who
        // need system-level memory context can still opt into prepend or append.
        const position = pluginConfig.recallInjectionPosition ?? "user";
        switch (position) {
          case "append":
            return { appendSystemContext: contextMessage };
          case "user":
            return { prependContext: contextMessage };
          case "prepend":
          default:
            return { prependSystemContext: contextMessage };
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === "TimeoutError") {
          log.warn(
            `[ContextBase] Auto-recall timed out after ${pluginConfig.recallTimeoutMs ?? DEFAULT_RECALL_TIMEOUT_MS}ms, skipping memory injection`
          );
        } else if (error instanceof Error && error.name === "AbortError") {
          // An AbortError now has two sources. The deadline is handled above as a
          // TimeoutError; this branch is reached when the service was stopped or
          // restarted mid-recall, which is not a timeout — quoting recallTimeoutMs
          // there reports a deadline that never elapsed, with a number unrelated
          // to the time actually spent. (#4450)
          if (recallLifecycle.signal?.aborted) {
            debug(
              "[ContextBase] Auto-recall cancelled: service stopped, skipping memory injection"
            );
          } else {
            log.warn(
              `[ContextBase] Auto-recall aborted after ${pluginConfig.recallTimeoutMs ?? DEFAULT_RECALL_TIMEOUT_MS}ms, skipping memory injection`
            );
          }
        } else {
          log.error("auto-recall error", error);
        }
        return;
      }
    });

    // Shared retain path for `agent_end` (per-turn cadence) and `session_end`
    // (force-flush at session close, bypassing the cadence so short sessions
    // and the un-retained tail of long sessions still land on disk). See #1726.
    const runRetain = async (
      event: any,
      ctx: PluginHookAgentContext | undefined,
      retainOptions: { force?: boolean; hookName: "agent_end" | "session_end" } = {
        hookName: "agent_end",
      }
    ): Promise<void> => {
      const force = retainOptions.force === true;
      const hookName = retainOptions.hookName;
      const retainGeneration = serviceGeneration;
      const { signal: retainSignal, isCurrent: retainLifecycleIsCurrent } = captureHookLifecycle();
      if (!retainLifecycleIsCurrent()) return;
      // Optional perf instrumentation (#1406). Only emitted when an actual
      // retain RPC fires; the many early-return skip paths are not measured.
      const perfHookStart = pluginConfig.debugPerfTiming ? Date.now() : 0;
      try {
        // Avoid cross-session contamination: only use context carried by this event.
        const eventSessionKey =
          typeof event?.sessionKey === "string" ? event.sessionKey : undefined;
        const effectiveCtx =
          ctx ||
          (eventSessionKey
            ? ({ sessionKey: eventSessionKey } as PluginHookAgentContext)
            : undefined);

        // Check if this provider is excluded
        if (
          effectiveCtx?.messageProvider &&
          pluginConfig.excludeProviders?.includes(effectiveCtx.messageProvider)
        ) {
          debug(
            `[ContextBase] Skipping retain for excluded provider: ${effectiveCtx.messageProvider}`
          );
          return;
        }

        // Session pattern filtering
        const agentEndSessionKey = effectiveCtx?.sessionKey;
        if (agentEndSessionKey) {
          const ignorePatterns = compileSessionPatterns(pluginConfig.ignoreSessionPatterns ?? []);
          if (
            ignorePatterns.length > 0 &&
            matchesSessionPattern(agentEndSessionKey, ignorePatterns)
          ) {
            debug(
              `[ContextBase] Skipping retain: session '${agentEndSessionKey}' matches ignoreSessionPatterns`
            );
            return;
          }
          const statelessPatterns = compileSessionPatterns(
            pluginConfig.statelessSessionPatterns ?? []
          );
          if (
            statelessPatterns.length > 0 &&
            matchesSessionPattern(agentEndSessionKey, statelessPatterns)
          ) {
            debug(
              `[ContextBase] Skipping retain: session '${agentEndSessionKey}' matches statelessSessionPatterns`
            );
            return;
          }
        }

        const sessionKeyForLookup = effectiveCtx?.sessionKey;
        const skipTurnReason = sessionKeyForLookup
          ? skipContextBaseTurnBySession.get(sessionKeyForLookup)
          : undefined;
        if (skipTurnReason && !isRetryableIdentitySkipReason(skipTurnReason)) {
          debug(
            `[ContextBase Hook] Skipping retain for session ${sessionKeyForLookup}: ${formatIdentitySkipReason(skipTurnReason)}`
          );
          logSkipOnce("retain", sessionKeyForLookup, skipTurnReason);
          if (sessionKeyForLookup) {
            skipContextBaseTurnBySession.delete(sessionKeyForLookup);
          }
          return;
        }

        const {
          effectiveCtx: effectiveCtxForRetain,
          resolvedCtx: resolvedCtxForRetain,
          skipReason: identitySkipReason,
        } = resolveAndCacheIdentity({
          sessionKey: sessionKeyForLookup,
          ctx: effectiveCtx,
        });

        if (identitySkipReason) {
          debug(
            `[ContextBase Hook] Skipping retain for session ${sessionKeyForLookup}: ${formatIdentitySkipReason(identitySkipReason)}`
          );
          logSkipOnce("retain", sessionKeyForLookup, identitySkipReason);
          if (sessionKeyForLookup) {
            skipContextBaseTurnBySession.delete(sessionKeyForLookup);
          }
          return;
        }
        if (sessionKeyForLookup) {
          skipContextBaseTurnBySession.delete(sessionKeyForLookup);
        }

        const bankId = deriveBankId(resolvedCtxForRetain, pluginConfig);
        debug(`[ContextBase Hook] ${hookName} triggered - bank: ${bankId}`);

        // `event.success === false` is a per-agent-end signal; session_end
        // doesn't carry it and a failed last turn shouldn't block the final
        // flush of preceding successful turns. (#1726)
        if (!force && event.success === false) {
          debug("[ContextBase Hook] Agent run failed, skipping retention");
          return;
        }

        // Resolved once: `session_end` carries no transcript, so the forced flush
        // has to fetch it. Without this the guard below ended every session-close
        // flush before it began. (#4341)
        let eventMessages = event.context?.sessionEntry?.messages ?? event.messages;
        if (force && (!Array.isArray(eventMessages) || eventMessages.length === 0)) {
          eventMessages = await sessionEndMessages(event, ctx?.endedTranscript);
          if (Array.isArray(eventMessages)) {
            debug(`[ContextBase Hook] session_end: read ${eventMessages.length} messages`);
          }
        }

        if (!Array.isArray(eventMessages) || eventMessages.length === 0) {
          debug("[ContextBase Hook] No messages in event, skipping retention");
          return;
        }

        if (pluginConfig.autoRetain === false) {
          debug("[ContextBase Hook] autoRetain is disabled, skipping retention");
          return;
        }

        // Chunked retention: skip non-Nth turns and use a sliding window when firing
        const retainEveryN = pluginConfig.retainEveryNTurns ?? 1;
        const allMessages = eventMessages;
        let messagesToRetain = allMessages;
        let retainFullWindow = false;

        if (retainEveryN > 1) {
          const sessionTrackingKey = `${bankId}:${effectiveCtx?.sessionKey || "session"}`;
          // session_end is a flush, not a turn — don't increment the counter.
          const turnCount = force
            ? turnCountBySession.get(sessionTrackingKey) || 0
            : (turnCountBySession.get(sessionTrackingKey) || 0) + 1;
          if (!force) {
            setCappedMapValue(turnCountBySession, sessionTrackingKey, turnCount);
          }

          const cadenceBoundary = turnCount > 0 && turnCount % retainEveryN === 0;
          const unretainedTurns = turnCount % retainEveryN;

          if (force) {
            // session_end: only flush if there are un-retained turns since the
            // last cadence boundary. The most recent agent_end either already
            // retained (cadenceBoundary) or accumulated `unretainedTurns` turns
            // that would otherwise be lost when the session closes. (#1726)
            if (turnCount === 0 || cadenceBoundary) {
              debug(
                `[ContextBase Hook] session_end: nothing un-retained (turnCount=${turnCount}, retainEveryN=${retainEveryN}), skipping flush`
              );
              return;
            }
            const overlapTurns = pluginConfig.retainOverlapTurns ?? 0;
            const windowTurns = unretainedTurns + overlapTurns;
            messagesToRetain = sliceLastTurnsByUserBoundary(allMessages, windowTurns);
            retainFullWindow = true;
            // Reset so a subsequent session_end (if the host re-emits) doesn't
            // re-retain the same window.
            turnCountBySession.delete(sessionTrackingKey);
            debug(
              `[ContextBase Hook] session_end: forced flush of ${unretainedTurns} un-retained turns (window: ${windowTurns} turns, ${messagesToRetain.length} messages)`
            );
          } else {
            if (!cadenceBoundary) {
              const nextRetainAt = Math.ceil(turnCount / retainEveryN) * retainEveryN;
              debug(
                `[ContextBase Hook] Turn ${turnCount}/${retainEveryN}, skipping retain (next at turn ${nextRetainAt})`
              );
              return;
            }

            // Sliding window in turns: N turns + configured overlap turns.
            // We slice by actual turn boundaries (user-role messages), so this
            // remains stable even when system/tool messages are present.
            const overlapTurns = pluginConfig.retainOverlapTurns ?? 0;
            const windowTurns = retainEveryN + overlapTurns;
            messagesToRetain = sliceLastTurnsByUserBoundary(allMessages, windowTurns);
            retainFullWindow = true;
            debug(
              `[ContextBase Hook] Turn ${turnCount}: chunked retain firing (window: ${windowTurns} turns, ${messagesToRetain.length} messages)`
            );
          }
        } else if (force) {
          // retainEveryN === 1 means every agent_end already retained — the
          // session_end flush would only duplicate work. (#1726)
          debug("[ContextBase Hook] session_end: retainEveryNTurns=1, nothing to flush");
          return;
        }

        const inlineRetainTags = normalizeRetainTags(
          messagesToRetain.flatMap((msg: any) => {
            if (msg?.role !== "user") {
              return [];
            }

            const content =
              typeof msg?.content === "string"
                ? msg.content
                : Array.isArray(msg?.content)
                  ? msg.content
                      .filter(
                        (block: any) => block?.type === "text" && typeof block?.text === "string"
                      )
                      .map((block: any) => block.text)
                      .join("\n")
                  : "";

            return extractInlineRetainTags(content);
          })
        );

        const retention = prepareRetentionTranscript(
          messagesToRetain,
          pluginConfig,
          retainFullWindow
        );
        if (!retention) {
          debug("[ContextBase Hook] No messages to retain (filtered/short/no-user)");
          return;
        }
        const { transcript, messageCount } = retention;

        if (isEphemeralOperationalText(transcript)) {
          debug("[ContextBase Hook] Transcript is operational/ephemeral noise, skipping retention");
          return;
        }

        // Wait for client to be ready
        const clientGlobal = (global as any).__contextbaseClient;
        if (!clientGlobal) {
          log.warn("client global not found, skipping retain");
          return;
        }

        await clientGlobal.waitForReady();
        if (!retainLifecycleIsCurrent()) return;

        // Get client configured for this context's bank (async to handle mission setup)
        const client = await clientGlobal.getClientForContext(resolvedCtxForRetain);
        if (!retainLifecycleIsCurrent()) return;
        if (!client) {
          log.warn("client not initialized, skipping retain");
          return;
        }

        // Use the cached capability, and only pay for a /version round trip while
        // it is still unknown. Probing on every retain would put an extra
        // request in front of every turn, and the answer changes at most once
        // per server restart — the queue flush re-probes on its own timer.
        const retainOperationIdCapability =
          asyncRetainOperationIdCapability === "unknown"
            ? await refreshQueueOperationIdCapability(retainGeneration, retainSignal)
            : asyncRetainOperationIdCapability;
        if (!retainLifecycleIsCurrent()) return;
        const retainNow = Date.now();
        const retainRequest = buildRetainRequest(
          transcript,
          messageCount,
          effectiveCtxForRetain,
          pluginConfig,
          retainNow,
          {
            retentionScope: retainFullWindow ? "window" : "turn",
            windowTurns: retainFullWindow
              ? (pluginConfig.retainEveryNTurns ?? 1) + (pluginConfig.retainOverlapTurns ?? 0)
              : undefined,
            tags: inlineRetainTags,
            appendSupported: supportsUpdateModeAppend,
            operationId: createAsyncRetainOperationId(),
          }
        );

        // Retain to ContextBase
        debug(
          `[ContextBase] Retaining to bank ${bankId}, document: ${retainRequest.documentId}, chars: ${transcript.length}\n---\n${transcript.substring(0, 500)}${transcript.length > 500 ? "\n...(truncated)" : ""}\n---`
        );

        const retainStart = pluginConfig.debugPerfTiming ? Date.now() : 0;
        let retainElapsedMs = 0;
        let retainOutcome: "ok" | "queued" | "error" = "error";
        try {
          // An unknown capability does not hold up the first send: there is
          // nothing on the server yet for it to duplicate, so omitting the wire
          // field is exactly today's behaviour. The id is still allocated and
          // persisted with the request, so a *replay* can be idempotent once the
          // capability is known — that is where duplicates actually come from.
          await client.retain(retainRequest, retainOperationIdCapability, retainSignal);
          if (!retainLifecycleIsCurrent()) return;
          retainElapsedMs = pluginConfig.debugPerfTiming ? Date.now() - retainStart : 0;
          retainOutcome = "ok";
          log.trackRetain(bankId, messageCount);
          debug(
            `[ContextBase] Retained ${messageCount} messages to bank ${bankId} for session ${retainRequest.documentId}`
          );

          // After a successful retain, try flushing any queued items
          if (retainQueue) {
            flushRetainQueue(undefined, undefined, undefined, retainGeneration, retainSignal).catch(
              () => {}
            );
          }
        } catch (retainError) {
          if (!retainLifecycleIsCurrent()) return;
          retainElapsedMs = pluginConfig.debugPerfTiming ? Date.now() - retainStart : 0;
          // Queue the failed retain for later delivery
          if (retainQueue) {
            retainQueue.enqueue(bankId, retainRequest, retainRequest.metadata);
            retainOutcome = "queued";
            const pending = retainQueue.size();
            log.warn(
              `API unreachable — retain queued (${pending} pending, bank: ${bankId}): ${retainError instanceof Error ? retainError.message : retainError}`
            );
          } else {
            log.error("error retaining messages", retainError);
          }
        }

        if (pluginConfig.debugPerfTiming) {
          log.info(
            formatHookPerf(hookName, Date.now() - perfHookStart, {
              retain: `${retainElapsedMs}ms`,
              outcome: retainOutcome,
              bank: bankId,
              messages: messageCount,
            })
          );
        }
      } catch (error) {
        log.error("error retaining messages", error);
      }
    };

    // Hook signature: (event, ctx) where event has {messages, success, error?, durationMs?}
    api.on("agent_end", async (event: any, ctx?: PluginHookAgentContext) => {
      await runRetain(event, ctx, { hookName: "agent_end" });
    });

    // session_end fires once per OpenClaw session close. We force-flush so
    // short conversations (fewer turns than `retainEveryNTurns`) and the
    // un-retained tail of long conversations are not silently dropped. (#1726)
    api.on("session_end", async (event: any, ctx?: PluginHookAgentContext) => {
      await runRetain(event, ctx, { hookName: "session_end", force: true });
    });
    debug("[ContextBase] Hooks registered");
    log.info("agent hooks registered");

    // OpenClaw's own memory surfaces read through this when ContextBase holds the
    // memory slot; without it they all report "memory plugin unavailable". (#4916)
    api.registerMemoryCapability?.({
      providerRuntime: createMemoryProviderRuntime({
        providerId: "contextbase-openclaw",
        agentBank: (agentId) => agentOnlyBankId(agentId, currentPluginConfig || pluginConfig),
        recall: async (bankId, query, signal) => {
          const live = await readyClient();
          if (!live) throw new Error("ContextBase client is not initialized");
          const config = currentPluginConfig || pluginConfig;
          const response = await scopeClient(live.client, bankId).recall(
            {
              query,
              maxTokens: config.recallMaxTokens,
              budget: config.recallBudget,
              types: config.recallTypes,
            },
            config.recallTimeoutMs,
            signal
          );
          return (response.results ?? []).map((r) => ({
            id: r.id,
            text: r.text,
            score: r.scores?.final,
          }));
        },
        getMemory: async (bankId, memoryId, signal) => {
          const live = await readyClient();
          if (!live) throw new Error("ContextBase client is not initialized");
          const res = await fetch(
            `${live.options.baseUrl.replace(/\/$/, "")}/v1/default/banks/${encodeURIComponent(bankId)}/memories/${encodeURIComponent(memoryId)}`,
            { headers: authHeaders(live.options), signal }
          );
          if (res.status === 404) return null;
          if (!res.ok) throw new Error(`ContextBase memory lookup failed: HTTP ${res.status}`);
          const body = (await res.json()) as { text?: unknown };
          return typeof body.text === "string" ? body.text : null;
        },
        healthy: async () => {
          const live = await readyClient().catch(() => null);
          if (!live) return false;
          // Bounded: OpenClaw's status call waits on this, and a hung API must read
          // as unavailable rather than hang the Memory page.
          const res = await fetch(`${live.options.baseUrl.replace(/\/$/, "")}/health`, {
            headers: authHeaders(live.options),
            signal: AbortSignal.timeout(5000),
          }).catch(() => null);
          return res?.ok === true;
        },
      }),
    });
  } catch (error) {
    log.error("plugin loading error", error);
    if (error instanceof Error) {
      log.error("error stack", error.stack);
    }
    throw error;
  }
}

// Export client getter for tools

function sanitizeDocumentIdPart(value: string | undefined, fallback: string): string {
  const normalized = (value || "").trim();
  if (!normalized) return fallback;
  return (
    normalized
      .replace(/[^a-zA-Z0-9:_-]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_+|_+$/g, "") || fallback
  );
}

function getSessionDocumentBase(effectiveCtx: PluginHookAgentContext | undefined): string {
  const sessionKeyPart = sanitizeDocumentIdPart(effectiveCtx?.sessionKey, "session");
  return `openclaw:${sessionKeyPart}`;
}

function nextDocumentSequence(effectiveCtx: PluginHookAgentContext | undefined): number {
  const sequenceKey = effectiveCtx?.sessionKey || "session";
  const next = (documentSequenceBySession.get(sequenceKey) || 0) + 1;
  setCappedMapValue(documentSequenceBySession, sequenceKey, next);
  return next;
}

function extractThreadId(channelId: string | undefined): string | undefined {
  if (!channelId) return undefined;
  const match = channelId.match(/(?:^|:)topic:([^:]+)$/);
  return match?.[1];
}

export function buildRetainRequest(
  transcript: string,
  messageCount: number,
  effectiveCtx: PluginHookAgentContext | undefined,
  pluginConfig: PluginConfig,
  now = Date.now(),
  options?: {
    retentionScope?: "turn" | "window" | "manual";
    windowTurns?: number;
    turnIndex?: number;
    tags?: string[];
    /**
     * Whether the live ContextBase API supports `update_mode: 'append'`. When
     * true, the request gets a stable per-session document id and
     * `updateMode: 'append'` so each retain concatenates to the existing
     * document. When false, falls back to a unique per-turn document id so
     * prior turns aren't overwritten. Defaults to false (conservative).
     */
    appendSupported?: boolean;
    /** Stable UUID allocated before the initial asynchronous retain request. */
    operationId?: string;
  }
): RetainRequest {
  const resolvedCtx = resolveSessionIdentity(effectiveCtx);
  const parsedSession = resolvedCtx?.sessionKey ? parseSessionKey(resolvedCtx.sessionKey) : {};
  const turnIndex = options?.turnIndex ?? nextDocumentSequence(resolvedCtx);
  const retentionScope = options?.retentionScope || "turn";
  const documentBase = getSessionDocumentBase(resolvedCtx);
  const documentKind = retentionScope === "window" ? "window" : "turn";
  // Retains are session-scoped: all turns accumulate under one document id when
  // the API can append. On legacy APIs without append support, every retain on
  // the same id would silently overwrite prior turns (behavior pre-#932), so
  // fall back to per-turn ids there.
  const useSessionScopedDoc = options?.appendSupported === true;
  // The fallback id carries a per-process boot token because `turnIndex` comes
  // from an in-memory counter: without it, a host restart replays
  // `…:turn:000001` onto the previous cycle's document and `update_mode:
  // 'replace'` deletes what was there. (#3686)
  const documentId = useSessionScopedDoc
    ? documentBase
    : `${documentBase}:${documentKind}:${getDocumentIdBootToken()}:${String(turnIndex).padStart(6, "0")}`;
  const provider = effectiveCtx?.messageProvider || parsedSession.provider;
  const channelId = sanitizeChannelId(effectiveCtx?.channelId, provider) || parsedSession.channel;
  const channelType = effectiveCtx?.messageProvider;
  const threadId = extractThreadId(channelId);
  const mergedTags = normalizeRetainTags([
    ...(pluginConfig.retainTags ?? []),
    ...(options?.tags ?? []),
  ]);

  return {
    content: transcript,
    documentId: documentId,
    context:
      typeof pluginConfig.retainContext === "string" && pluginConfig.retainContext.trim().length > 0
        ? pluginConfig.retainContext.trim()
        : DEFAULT_RETAIN_CONTEXT,
    metadata: {
      retained_at: new Date(now).toISOString(),
      message_count: String(messageCount),
      source: pluginConfig.retainSource || "openclaw",
      retention_scope: retentionScope,
      turn_index: String(turnIndex),
      session_key: resolvedCtx?.sessionKey,
      agent_id: resolvedCtx?.agentId || parsedSession.agentId,
      provider,
      channel_type: channelType,
      channel_id: channelId,
      thread_id: threadId,
      sender_id: resolvedCtx?.senderId,
      ...(options?.windowTurns !== undefined ? { window_turns: String(options.windowTurns) } : {}),
    },
    tags: mergedTags.length > 0 ? mergedTags : undefined,
    ...(options?.operationId ? { operationId: options.operationId } : {}),
    updateMode: useSessionScopedDoc ? "append" : undefined,
  };
}

export function prepareRetentionTranscript(
  messages: any[],
  pluginConfig: PluginConfig,
  retainFullWindow = false
): { transcript: string; messageCount: number } | null {
  if (!messages || messages.length === 0) {
    return null;
  }

  let targetMessages: any[];
  if (retainFullWindow) {
    // Chunked retention: retain the full sliding window (already sliced by caller)
    targetMessages = messages;
  } else {
    // Default: retain only the last turn (user message + assistant responses)
    let lastUserIdx = -1;
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") {
        lastUserIdx = i;
        break;
      }
    }
    if (lastUserIdx === -1) {
      return null; // No user message found in turn
    }
    targetMessages = messages.slice(lastUserIdx);
  }

  const format = pluginConfig.retainFormat ?? "json";
  const includeToolCalls = format === "json" && pluginConfig.retainToolCalls !== false;

  if (includeToolCalls) {
    const structured = buildAnthropicStructuredMessages(targetMessages, pluginConfig);
    if (structured.length === 0) return null;
    const transcript = JSON.stringify(structured);
    if (!transcript.trim() || transcript.length < 10) return null;
    return { transcript, messageCount: structured.length };
  }

  // Role filtering (text-only path)
  const allowedRoles = new Set(pluginConfig.retainRoles || ["user", "assistant"]);
  const filteredMessages = targetMessages.filter((m: any) => allowedRoles.has(m.role));

  if (filteredMessages.length === 0) {
    return null; // No messages to retain
  }

  const normalized: Array<{ role: string; content: string; timestamp?: string }> = [];
  for (const msg of filteredMessages) {
    const role = msg.role || "unknown";
    let content = "";

    if (typeof msg.content === "string") {
      content = msg.content;
    } else if (Array.isArray(msg.content)) {
      content = msg.content
        .filter((block: any) => block.type === "text")
        .map((block: any) => block.text)
        .join("\n");
    }

    content = stripMemoryTags(content);
    content = stripInlineRetainTags(content);
    content = stripMetadataEnvelopes(content);
    content = stripInlineTimestampPrefix(content);
    content = stripRuntimeEnvelope(content).trim();

    if (content.trim()) {
      const timestamp = normalizeMessageTimestamp(msg);
      normalized.push(timestamp ? { role, content, timestamp } : { role, content });
    }
  }

  if (normalized.length === 0) return null;

  let transcript: string;
  let messageCount: number;
  if (format === "text") {
    transcript = normalized
      .map(({ role, content }) => `[role: ${role}]\n${content}\n[${role}:end]`)
      .join("\n\n");
    messageCount = normalized.length;
  } else {
    transcript = JSON.stringify(normalized);
    messageCount = normalized.length;
  }

  if (!transcript.trim() || transcript.length < 10) return null;

  return { transcript, messageCount };
}

// MCP tool name suffixes that are operational (recall/retain/search/CRUD) and
// shouldn't be retained — preserves agent reasoning without creating feedback
// loops on ContextBase's own MCP surface. Mirrors the claude-code integration.
const OPERATIONAL_TOOL_PATTERN =
  /(?:recall|retain|reflect|search|extract|create_|delete_|update_|get_|list_)/i;
const TOOL_RESULT_MAX_CHARS = 2000;

/**
 * Build an Anthropic-shaped message array from OpenClaw's session messages.
 *
 * OpenClaw stores assistant content as a block array that may contain
 * `text`, `thinking`, and `toolCall` entries, and emits tool results as
 * separate messages with `role: "toolResult"`. The Anthropic wire format
 * expected by ContextBase's Claude Code integration (and downstream consumers)
 * is: assistant messages carry `text` and `tool_use` blocks, and tool
 * results live in a following `user` message as `tool_result` blocks.
 * We translate to that shape here so stored documents are consistent
 * across integrations.
 */
function buildAnthropicStructuredMessages(
  messages: any[],
  pluginConfig: PluginConfig
): Array<{ role: string; content: any[]; timestamp?: string }> {
  const allowedRoles = new Set(pluginConfig.retainRoles || ["user", "assistant"]);
  const out: Array<{ role: string; content: any[]; timestamp?: string }> = [];

  for (const msg of messages) {
    const rawRole = msg?.role;
    if (rawRole === "toolResult") {
      const toolResultBlock = buildToolResultBlock(msg);
      if (!toolResultBlock) continue;
      // Fold tool_result into a synthetic user message (Anthropic convention),
      // merging with an immediately-preceding synthetic user if one exists so
      // consecutive tool results stay together.
      const last = out[out.length - 1];
      if (
        last &&
        last.role === "user" &&
        last.content.every((b: any) => b.type === "tool_result")
      ) {
        last.content.push(toolResultBlock);
      } else {
        out.push({ role: "user", content: [toolResultBlock] });
      }
      continue;
    }

    if (!allowedRoles.has(rawRole)) continue;

    const blocks = extractStructuredBlocks(msg.content, rawRole);
    if (blocks.length > 0) {
      const timestamp = normalizeMessageTimestamp(msg);
      out.push(
        timestamp
          ? { role: rawRole, content: blocks, timestamp }
          : { role: rawRole, content: blocks }
      );
    }
  }

  return out;
}

function normalizeMessageTimestamp(msg: any): string | undefined {
  const raw = msg?.timestamp;
  if (raw === undefined || raw === null) return undefined;
  const date =
    typeof raw === "number" ? new Date(raw) : typeof raw === "string" ? new Date(raw) : undefined;
  if (!date || Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
}

function extractStructuredBlocks(content: any, role: string): any[] {
  if (typeof content === "string") {
    const cleaned = stripRuntimeEnvelope(
      stripInlineTimestampPrefix(
        stripMetadataEnvelopes(stripInlineRetainTags(stripMemoryTags(content)))
      )
    ).trim();
    return cleaned ? [{ type: "text", text: cleaned }] : [];
  }
  if (!Array.isArray(content)) return [];

  const blocks: any[] = [];
  for (const block of content) {
    if (!block || typeof block !== "object") continue;
    const blockType = block.type;

    if (blockType === "text") {
      const cleaned = stripRuntimeEnvelope(
        stripInlineTimestampPrefix(
          stripMetadataEnvelopes(stripInlineRetainTags(stripMemoryTags(block.text ?? "")))
        )
      ).trim();
      if (cleaned) blocks.push({ type: "text", text: cleaned });
    } else if (blockType === "toolCall" && role === "assistant") {
      const name = typeof block.name === "string" ? block.name : "unknown";
      // Skip ContextBase's own MCP operational tools to avoid feedback loops.
      if (name.startsWith("mcp__") && OPERATIONAL_TOOL_PATTERN.test(name.split("__").pop() ?? ""))
        continue;
      const input = block.arguments && typeof block.arguments === "object" ? block.arguments : {};
      const id = typeof block.id === "string" ? block.id : undefined;
      const toolUse: any = { type: "tool_use", name, input };
      if (id) toolUse.id = id;
      blocks.push(toolUse);
    }
    // thinking / unknown types are dropped
  }
  return blocks;
}

function buildToolResultBlock(msg: any): any | null {
  const toolUseId = typeof msg.toolCallId === "string" ? msg.toolCallId : "";
  const raw = msg.content;
  let text = "";
  if (typeof raw === "string") {
    text = raw;
  } else if (Array.isArray(raw)) {
    text = raw
      .filter((b: any) => b && b.type === "text" && typeof b.text === "string")
      .map((b: any) => b.text)
      .join("\n");
  }
  text = text.trim();
  if (!text) return null;
  if (text.length > TOOL_RESULT_MAX_CHARS) {
    text = text.slice(0, TOOL_RESULT_MAX_CHARS) + "... (truncated)";
  }
  const block: any = { type: "tool_result", content: text };
  if (toolUseId) block.tool_use_id = toolUseId;
  return block;
}

export function sliceLastTurnsByUserBoundary(messages: any[], turns: number): any[] {
  if (!Array.isArray(messages) || messages.length === 0 || turns <= 0) {
    return [];
  }

  // Count only user messages that contain actual text content.
  // OpenClaw normalizes tool_result blocks into role:"user" messages with a
  // tool_result content block. Without this filter those synthetic messages
  // would be counted as real user turns, causing the window to exclude actual
  // user input from the retained transcript.
  function hasRealTextContent(msg: any): boolean {
    if (msg?.role !== "user") return false;
    const content = msg.content;
    if (typeof content === "string") return content.trim().length > 0;
    if (Array.isArray(content)) {
      return content.some(
        (b: any) => b?.type === "text" && typeof b?.text === "string" && b.text.trim().length > 0
      );
    }
    return false;
  }

  let userTurnsSeen = 0;
  let startIndex = -1;

  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role === "user" && hasRealTextContent(messages[i])) {
      userTurnsSeen += 1;
      if (userTurnsSeen >= turns) {
        startIndex = i;
        break;
      }
    }
  }

  if (startIndex === -1) {
    return messages;
  }

  return messages.slice(startIndex);
}

export function getClient() {
  return client;
}
