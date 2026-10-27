import type { Plugin } from "@elizaos/core";
import { createContextBaseEvaluator } from "./evaluator.js";
import type { ContextBasePluginOptions } from "./options.js";
import { createContextBaseProvider } from "./provider.js";

/**
 * Creates an elizaOS plugin that gives an agent long-term memory backed by
 * ContextBase.
 *
 * - A **provider** recalls relevant memories and injects them into the prompt
 *   before each model call.
 * - An **evaluator** retains conversation messages after each turn.
 *
 * Both sides default to enabled. Disable either via `recall.enabled` /
 * `retain.enabled`.
 *
 * @example
 * ```ts
 * import { createContextBasePlugin } from "contextbase-eliza";
 * import { ContextBaseClient } from "contextbase-client";
 *
 * const plugin = createContextBasePlugin({
 *   client: new ContextBaseClient({ apiKey: process.env.CONTEXTBASE_API_KEY }),
 *   recall: { budget: "high", includeEntities: true },
 *   retain: { tags: ["source:eliza"] },
 * });
 * ```
 */
export function createContextBasePlugin(options: ContextBasePluginOptions): Plugin {
  const { client, bank, recall = {}, retain = {} } = options;

  const providers =
    recall.enabled === false ? [] : [createContextBaseProvider(client, bank, recall)];
  const evaluators =
    retain.enabled === false ? [] : [createContextBaseEvaluator(client, bank, retain)];

  return {
    name: "contextbase-eliza",
    description: "ContextBase long-term memory: recall relevant memories and retain conversations.",
    providers,
    evaluators,
  };
}
