/**
 * ContextBase long-term memory for Vercel Eve agents.
 *
 * One authored file gives an Eve agent memory that just works: relevant memory
 * is recalled on the live user message before each turn, the exchange is
 * retained after, and every scope gets its own ContextBase bank.
 *
 * ```ts
 * // agent/memory/contextbase.ts
 * import { contextbaseMemory } from "contextbase-eve";
 * import { defineMemory } from "eve/memory";
 * import { byPrincipal } from "eve/memory/scope";
 *
 * export default defineMemory({
 *   description: "Long-term memory about the current user.",
 *   provider: contextbaseMemory(),
 *   scope: byPrincipal,
 * });
 * ```
 *
 * Configure via env: `CONTEXTBASE_API_KEY`, `CONTEXTBASE_API_URL` (defaults to
 * ContextBase Cloud).
 */
export { contextbaseMemory, type MemoryProviderOptions } from "./memory-provider.js";

export {
  bankFromScope,
  buildRecallContent,
  buildRecallQuery,
  completedTurn,
  resolveMemoryProvider,
  EMPTY_RECALL_CONTENT,
  RECALL_MESSAGE_ID,
  type BankResolver,
  type MemoryPhase,
  type MemoryScopeLike,
  type ResolvedMemoryProvider,
} from "./provider-core.js";

// v0.2 hooks/instructions entrypoints — deprecated, removed in the next release.
export {
  contextbaseAutoRecall,
  contextbaseRetainHook,
  type AutoMemoryOptions,
} from "./auto-memory.js";

export {
  resolveAutoMemory,
  resolveConnection,
  isContextBaseCloudUrl,
  CONTEXTBASE_CLOUD_API_URL,
  DEFAULT_RECALL_QUERY,
  DEFAULT_BANK_ID,
  type ConnectionOptions,
  type ResolvedConnection,
  type ResolvedAutoMemory,
} from "./config.js";

export {
  ContextBaseRestClient,
  ContextBaseHttpError,
  buildRecallMarkdown,
  stripSentinelBlocks,
  type RecallResult,
  type RecallResponse,
  type ReflectResponse,
  type RetainItem,
  type RecallBudget,
  type RecallOptions,
  type RetainOptions,
  type ReflectOptions,
} from "./client.js";
