#!/bin/bash
# Quickstart examples for Hindsight CLI
# Run: bash examples/api/quickstart.sh

set -e

HINDSIGHT_URL="${CONTEXTBASE_API_URL:-http://localhost:8888}"

# =============================================================================
# Doc Examples
# =============================================================================

# [docs:quickstart-full]
# Retain: Store information
contextbase memory retain my-bank "Alice works at Google as a software engineer"

# Recall: Search memories
contextbase memory recall my-bank "What does Alice do?"

# Reflect: Generate response
contextbase memory reflect my-bank "Tell me about Alice"
# [/docs:quickstart-full]


# =============================================================================
# Cleanup (not shown in docs)
# =============================================================================
curl -s -X DELETE "${HINDSIGHT_URL}/v1/default/banks/my-bank" > /dev/null

echo "quickstart.sh: All examples passed"
