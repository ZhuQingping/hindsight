#!/bin/bash
# Recall API examples for Hindsight CLI
# Run: bash examples/api/recall.sh

set -e

HINDSIGHT_URL="${CONTEXTBASE_API_URL:-http://localhost:8888}"

# =============================================================================
# Setup (not shown in docs)
# =============================================================================
contextbase memory retain my-bank "Alice works at Google as a software engineer"
contextbase memory retain my-bank "Alice loves hiking on weekends"

# =============================================================================
# Doc Examples
# =============================================================================

# [docs:recall-basic]
contextbase memory recall my-bank "What does Alice do?"
# [/docs:recall-basic]


# [docs:recall-with-options]
contextbase memory recall my-bank "hiking recommendations" \
  --budget high \
  --max-tokens 8192
# [/docs:recall-with-options]


# [docs:recall-fact-type]
contextbase memory recall my-bank "query" --fact-type world,observation
# [/docs:recall-fact-type]


# [docs:recall-trace]
contextbase memory recall my-bank "query" --trace
# [/docs:recall-trace]


# [docs:recall-budget-levels]
# Quick lookup
contextbase memory recall my-bank "Alice's email" --budget low

# Deep exploration
contextbase memory recall my-bank "How are Alice and Bob connected?" --budget high
# [/docs:recall-budget-levels]


# [docs:recall-token-budget]
# Fill up to 4K tokens of context with relevant memories
contextbase memory recall my-bank "What do I know about Alice?" --max-tokens 4096

# Smaller budget for quick lookups
contextbase memory recall my-bank "Alice's email" --max-tokens 500
# [/docs:recall-token-budget]


# [docs:recall-source-facts]
# Recall observations with source facts
contextbase memory recall my-bank "What patterns have I learned about Alice?" \
  --fact-type observation
# [/docs:recall-source-facts]


# [docs:recall-with-tags]
# Filter recall to only memories tagged for a specific user
contextbase memory recall my-bank "What feedback did the user give?" \
  --tags "user:alice"
# [/docs:recall-with-tags]


# [docs:recall-tags-strict]
# Strict: only memories that have matching tags (excludes untagged)
contextbase memory recall my-bank "What did the user say?" \
  --tags "user:alice" --tags-match any_strict
# [/docs:recall-tags-strict]


# [docs:recall-tags-all]
# AND matching: require ALL specified tags to be present
contextbase memory recall my-bank "What bugs were reported?" \
  --tags "user:alice,bug-report" --tags-match all_strict
# [/docs:recall-tags-all]


# [docs:recall-tags-any]
contextbase memory recall my-bank "communication preferences" \
  --tags "user:alice" --tags-match any
# [/docs:recall-tags-any]


# [docs:recall-tags-any-strict]
contextbase memory recall my-bank "communication preferences" \
  --tags "user:alice" --tags-match any_strict
# [/docs:recall-tags-any-strict]


# [docs:recall-tags-all-mode]
contextbase memory recall my-bank "communication tools" \
  --tags "user:alice,team" --tags-match all
# [/docs:recall-tags-all-mode]


# [docs:recall-tags-all-strict]
contextbase memory recall my-bank "communication tools" \
  --tags "user:alice,team" --tags-match all_strict
# [/docs:recall-tags-all-strict]


# =============================================================================
# Cleanup (not shown in docs)
# =============================================================================
curl -s -X DELETE "${HINDSIGHT_URL}/v1/default/banks/my-bank" > /dev/null

echo "recall.sh: All examples passed"
