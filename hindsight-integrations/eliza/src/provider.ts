import type { Provider } from "@elizaos/core";
import type { ContextBaseClient, RecallResult } from "./client.js";
import { type BankResolver, type RecallOptions, resolveBank } from "./options.js";

const DEFAULT_HEADING = "# Relevant long-term memories";

/** Render recalled memories as a markdown bullet list for prompt inclusion. */
function formatMemories(results: RecallResult[], heading: string): string {
  const lines = results
    .map((r) => r.text?.trim())
    .filter((text): text is string => Boolean(text))
    .map((text) => `- ${text}`);
  if (lines.length === 0) return "";
  return `${heading}\n${lines.join("\n")}`;
}

/**
 * Builds the recall provider. On every turn it queries ContextBase with the
 * incoming message text and injects the relevant memories into the agent's
 * prompt context. Recall failures are swallowed so a memory-service outage
 * never blocks the agent from responding.
 */
export function createContextBaseProvider(
  client: ContextBaseClient,
  bank: BankResolver | undefined,
  options: RecallOptions = {}
): Provider {
  const heading = options.heading ?? DEFAULT_HEADING;

  return {
    name: "CONTEXTBASE_MEMORY",
    description:
      "Long-term memories recalled from ContextBase that are relevant to the current message.",
    dynamic: false,
    get: async (_runtime, message) => {
      const query = message.content?.text?.trim();
      if (!query) {
        return { text: "", values: {}, data: {} };
      }

      try {
        const response = await client.recall(resolveBank(bank, message), query, {
          types: options.types,
          maxTokens: options.maxTokens,
          budget: options.budget,
          includeEntities: options.includeEntities,
        });
        const results = response.results ?? [];
        const text = formatMemories(results, heading);
        return {
          text,
          values: { contextbaseMemoryCount: results.length },
          data: { contextbase: response },
        };
      } catch (error) {
        return {
          text: "",
          values: { contextbaseMemoryCount: 0 },
          data: { contextbaseError: error instanceof Error ? error.message : String(error) },
        };
      }
    },
  };
}
