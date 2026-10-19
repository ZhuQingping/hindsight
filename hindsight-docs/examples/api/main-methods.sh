#!/bin/bash
# Main Methods overview examples for Hindsight CLI
# Run: bash examples/api/main-methods.sh

set -e

HINDSIGHT_URL="${CONTEXTBASE_API_URL:-http://localhost:8888}"
BANK_ID="main-methods-sh-demo-bank"

# =============================================================================
# Setup (not shown in docs)
# =============================================================================
WORKDIR=$(mktemp -d)
cd "$WORKDIR"
mkdir docs
echo "Alice: I finished the ML pipeline review. Bob: Great, let's ship it." > conversation.txt
echo "The team uses GitHub for code reviews." > docs/process.txt

# =============================================================================
# Doc Examples
# =============================================================================

# [docs:main-retain]
# Store a single fact
contextbase memory retain "$BANK_ID" "Alice joined Google in March 2024 as a Senior ML Engineer"

# Store from a file
contextbase memory retain-files "$BANK_ID" conversation.txt --context "Daily standup"

# Store multiple files
contextbase memory retain-files "$BANK_ID" docs/
# [/docs:main-retain]

# [docs:main-recall]
# Basic search
contextbase memory recall "$BANK_ID" "What does Alice do at Google?"

# Search with options
contextbase memory recall "$BANK_ID" "What happened last spring?" \
    --budget high \
    --max-tokens 8192 \
    --fact-type world,experience

# Verbose output
contextbase memory recall "$BANK_ID" "Tell me about Alice" -v
# [/docs:main-recall]

# [docs:main-reflect]
# Basic reflect
contextbase memory reflect "$BANK_ID" "Should we adopt TypeScript for our backend?"

# With higher reasoning budget
contextbase memory reflect "$BANK_ID" "Analyze our tech stack" --budget high
# [/docs:main-reflect]

# =============================================================================
# Cleanup (not shown in docs)
# =============================================================================
rm -rf "$WORKDIR"
curl -s -X DELETE "${HINDSIGHT_URL}/v1/default/banks/${BANK_ID}" > /dev/null

echo "main-methods.sh: All examples passed"
