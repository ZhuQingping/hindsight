#!/bin/bash
# CLI Reference examples for Hindsight (docs/sdks/cli.mdx)
# Run: bash examples/api/cli-reference.sh

set -e

# Confirmation prompts read stdin; EOF answers "no", so the no-flag
# variants below print "Operation cancelled" instead of blocking.
exec </dev/null

export AGENTSTRATUM_API_URL="${AGENTSTRATUM_API_URL:-http://localhost:8888}"
BANK="my-cli-bank"
DEMO_BANK="cli-demo"

# The configure/profile examples write ~/.agentstratum — point HOME at a temp dir
# so running this script never touches the real user config.
REAL_HOME="$HOME"
export HOME="$(mktemp -d)"
WORK_DIR="$(mktemp -d)"
cleanup() {
  agentstratum bank delete "$BANK" -y >/dev/null 2>&1 || true
  agentstratum bank delete "$DEMO_BANK" -y >/dev/null 2>&1 || true
  rm -rf "$HOME" "$WORK_DIR"
  export HOME="$REAL_HOME"
}
trap cleanup EXIT

# Start from a clean bank
agentstratum bank delete "$BANK" -y >/dev/null 2>&1 || true
agentstratum bank delete "$DEMO_BANK" -y >/dev/null 2>&1 || true

# =============================================================================
# Configuration
# =============================================================================

# [docs:cli-configure]
# Set directly
agentstratum configure --api-url http://localhost:8888

# With API key for authentication
agentstratum configure --api-url http://localhost:8888 --api-key your-api-key
# [/docs:cli-configure]

# [docs:cli-profiles]
# Create (or overwrite) a profile
agentstratum profile create prod \
  --api-url https://api.hindsight.vectorize.io \
  --api-key hsk_...

# List and inspect profiles
agentstratum profile list
agentstratum profile show prod

# Use a profile for a single command
agentstratum -p prod bank list

# Or make it sticky for the current shell
export HINDSIGHT_PROFILE=prod
agentstratum bank list

# Remove a profile
agentstratum profile delete prod -y
# [/docs:cli-profiles]
unset HINDSIGHT_PROFILE

# =============================================================================
# Core Commands
# =============================================================================

# [docs:cli-retain]
agentstratum memory retain my-cli-bank "Alice works at Google as a software engineer"

# With context
agentstratum memory retain my-cli-bank "Bob loves hiking" --context "hobby discussion"

# Queue for background processing
agentstratum memory retain my-cli-bank "Meeting notes" --async

# With an event date (ISO 8601 datetime or date)
agentstratum memory retain my-cli-bank "Project launched" --timestamp 2024-01-15

# Store without a timestamp (overrides the default of "now")
agentstratum memory retain my-cli-bank "Background fact" --timestamp unset
# [/docs:cli-retain]

# Setup for retain-files: sample files and a "conversations" retain strategy
cd "$WORK_DIR"
mkdir -p documents/sub data
echo "Carol leads the platform team." > notes.txt
echo "The API is deployed with Helm." > documents/deploy.md
echo "Staging runs on a single node." > documents/sub/staging.md
echo "Weekly sync: we agreed to ship on Friday." > meeting-notes.txt
echo "Dave maintains the billing service." > data/billing.txt
curl -sf -X PATCH "$AGENTSTRATUM_API_URL/v1/default/banks/$BANK/config" \
  -H "Content-Type: application/json" \
  -d '{"updates": {"retain_strategies": {"conversations": {"retain_extraction_mode": "concise"}}}}' >/dev/null

# [docs:cli-retain-files]
# Single file
agentstratum memory retain-files my-cli-bank notes.txt

# Directory (recursive by default)
agentstratum memory retain-files my-cli-bank ./documents/

# With context
agentstratum memory retain-files my-cli-bank meeting-notes.txt --context "team meeting"

# With a named retain strategy (see retain_strategies in bank config)
agentstratum memory retain-files my-cli-bank ./documents/ --strategy conversations

# Background processing
agentstratum memory retain-files my-cli-bank ./data/ --async
# [/docs:cli-retain-files]

# [docs:cli-recall]
agentstratum memory recall my-cli-bank "What does Alice do?"

# With options
agentstratum memory recall my-cli-bank "hiking recommendations" \
  --budget high \
  --max-tokens 8192

# Filter by fact type
agentstratum memory recall my-cli-bank "query" --fact-type world,observation

# Filter by tags
agentstratum memory recall my-cli-bank "query" --tags work,project \
  --tags-match all

# Pin results to a specific time
agentstratum memory recall my-cli-bank "query" --query-timestamp "2026-01-15T00:00:00Z"

# Show trace information
agentstratum memory recall my-cli-bank "query" --trace
# [/docs:cli-recall]

# [docs:cli-reflect]
agentstratum memory reflect my-cli-bank "What do you know about Alice?"

# With additional context
agentstratum memory reflect my-cli-bank "Should I learn Python?" --context "career advice"

# Higher budget for complex questions
agentstratum memory reflect my-cli-bank "Summarize my week" --budget high

# Filter by fact type
agentstratum memory reflect my-cli-bank "query" \
  --fact-types world,experience \
  --exclude-mental-models
# [/docs:cli-reflect]

# A real memory unit id for history / clear-observations
MEMORY_ID=$(agentstratum memory list "$BANK" -o json | jq -r '.items[0].id')

# [docs:cli-memory-history]
agentstratum memory history my-cli-bank "$MEMORY_ID"
# [/docs:cli-memory-history]

# [docs:cli-memory-clear-observations]
agentstratum memory clear-observations my-cli-bank "$MEMORY_ID"

# Skip confirmation prompt
agentstratum memory clear-observations my-cli-bank "$MEMORY_ID" -y
# [/docs:cli-memory-clear-observations]

# =============================================================================
# Bank Management
# =============================================================================

# [docs:cli-bank-list]
agentstratum bank list
# [/docs:cli-bank-list]

# [docs:cli-bank-disposition]
agentstratum bank disposition my-cli-bank
# [/docs:cli-bank-disposition]

# [docs:cli-bank-set-disposition]
agentstratum bank set-disposition my-cli-bank --skepticism 3 --literalism 4 --empathy 5
# [/docs:cli-bank-set-disposition]

# [docs:cli-bank-stats]
agentstratum bank stats my-cli-bank
# [/docs:cli-bank-stats]

# [docs:cli-bank-name]
agentstratum bank name my-cli-bank "My Assistant"
# [/docs:cli-bank-name]

# [docs:cli-bank-mission]
agentstratum bank mission my-cli-bank "I am a helpful AI assistant interested in technology"
# [/docs:cli-bank-mission]

# [docs:cli-bank-clear-observations]
agentstratum bank clear-observations my-cli-bank

# Skip confirmation prompt
agentstratum bank clear-observations my-cli-bank -y
# [/docs:cli-bank-clear-observations]

# [docs:cli-bank-consolidation-recover]
agentstratum bank consolidation-recover my-cli-bank
# [/docs:cli-bank-consolidation-recover]

# =============================================================================
# Document Management
# =============================================================================

agentstratum memory retain "$BANK" "Carol is a project manager" --doc-id meeting-2024-01-15 >/dev/null
DOCUMENT_ID="meeting-2024-01-15"

# [docs:cli-documents]
# List documents
agentstratum document list my-cli-bank

# Get document details
agentstratum document get my-cli-bank "$DOCUMENT_ID"

# Replace a document's tags
agentstratum document update my-cli-bank "$DOCUMENT_ID" --tags project-x,meetings

# Delete document and its memories
agentstratum document delete my-cli-bank "$DOCUMENT_ID"
# [/docs:cli-documents]

# =============================================================================
# Entity Management
# =============================================================================

ENTITY_ID=$(agentstratum entity list "$BANK" -o json | jq -r '.items[0].id')

# [docs:cli-entities]
# List entities
agentstratum entity list my-cli-bank

# Get entity details
agentstratum entity get my-cli-bank "$ENTITY_ID"
# [/docs:cli-entities]

# =============================================================================
# Operation Management
# =============================================================================

# A pending async operation to inspect and cancel, then retry
OPERATION_ID=$(agentstratum memory retain "$BANK" "Erin joined the team" --async -o json | jq -r '.operation_id')

# [docs:cli-operations]
# List operations
agentstratum operation list my-cli-bank

# Get operation status
agentstratum operation get my-cli-bank "$OPERATION_ID"

# Cancel a pending operation
agentstratum operation cancel my-cli-bank "$OPERATION_ID"

# Retry a failed operation
agentstratum operation retry my-cli-bank "$OPERATION_ID"
# [/docs:cli-operations]

# =============================================================================
# Webhook Management
# =============================================================================

WEBHOOK_ID=$(agentstratum webhook create "$BANK" https://example.com/setup-hook -o json | jq -r '.id')

# [docs:cli-webhooks]
# List webhooks
agentstratum webhook list my-cli-bank

# Create a webhook (defaults to consolidation.completed events)
agentstratum webhook create my-cli-bank https://example.com/hook

# Create with specific events and signing secret
agentstratum webhook create my-cli-bank https://example.com/hook \
  --event-types retain.completed,consolidation.completed \
  --secret my-hmac-secret

# Update a webhook
agentstratum webhook update my-cli-bank "$WEBHOOK_ID" --url https://new-url.com

# View delivery history
agentstratum webhook deliveries my-cli-bank "$WEBHOOK_ID"

# Delete a webhook
agentstratum webhook delete my-cli-bank "$WEBHOOK_ID" -y
# [/docs:cli-webhooks]

# =============================================================================
# Knowledge Base
# =============================================================================

# [docs:cli-kb-tree]
# Show the folder/page tree (pages that have fallen behind are marked stale)
agentstratum knowledge-base tree my-cli-bank
# [/docs:cli-kb-tree]

# [docs:cli-kb-create-folder]
# Create a folder, optionally nested under another
agentstratum knowledge-base create-folder my-cli-bank "Operations"
# [/docs:cli-kb-create-folder]
FOLDER_ID=$(agentstratum knowledge-base tree "$BANK" -o json | jq -r '[.. | objects | select(.kind? == "folder" and .name? == "Operations")][0].id')

# [docs:cli-kb-create-subfolder]
agentstratum knowledge-base create-folder my-cli-bank "Runbooks" --parent-id "$FOLDER_ID"
# [/docs:cli-kb-create-subfolder]

# [docs:cli-kb-create-page]
# Create a page — content is generated in the background
agentstratum knowledge-base create-page my-cli-bank \
  "Deploying the API" \
  "How is the API deployed?" \
  --parent-id "$FOLDER_ID" \
  --tags ops,type:runbook

# Build a page from raw facts instead of the observation-only default
agentstratum knowledge-base create-page my-cli-bank "Recent Incidents" \
  "What incidents happened recently?" \
  --fact-types experience,world --mode full
# [/docs:cli-kb-create-page]
PAGE_ID=$(agentstratum knowledge-base tree "$BANK" -o json | jq -r '[.. | objects | select(.kind? == "page" and .name? == "Recent Incidents")][0].id')
NODE_ID="$FOLDER_ID"

# [docs:cli-kb-manage]
# Read a page as a markdown document
agentstratum knowledge-base get-page my-cli-bank "$PAGE_ID"

# Hybrid search (full-text + vector) over whole pages
agentstratum knowledge-base search my-cli-bank "how do we deploy" --limit 5

# Rename, move, or reconfigure a node
agentstratum knowledge-base update my-cli-bank "$NODE_ID" --name "New name"
agentstratum knowledge-base update my-cli-bank "$PAGE_ID" --source-query "New question?"

# Export the whole knowledge base as a markdown bundle
agentstratum knowledge-base export my-cli-bank

# Delete a folder or page and everything under it
agentstratum knowledge-base delete my-cli-bank "$NODE_ID" -y
# [/docs:cli-kb-manage]

# =============================================================================
# Audit Logs
# =============================================================================

# [docs:cli-audit]
# List audit entries
agentstratum audit list my-cli-bank

# Filter by action and transport
agentstratum audit list my-cli-bank --action recall --transport mcp

# Filter by date range
agentstratum audit list my-cli-bank \
  --start-date "2026-04-01T00:00:00Z" \
  --end-date "2026-04-10T00:00:00Z"

# Pagination
agentstratum audit list my-cli-bank --limit 50 --offset 100
# [/docs:cli-audit]

# =============================================================================
# Output Formats
# =============================================================================

# [docs:cli-output]
# Pretty (default)
agentstratum memory recall my-cli-bank "query"

# JSON
agentstratum memory recall my-cli-bank "query" -o json

# YAML
agentstratum memory recall my-cli-bank "query" -o yaml
# [/docs:cli-output]

# =============================================================================
# Example Workflow
# =============================================================================

# [docs:cli-workflow]
# Configure API URL
agentstratum configure --api-url http://localhost:8888

# Store some memories
agentstratum memory retain cli-demo "Alice works at Google"
agentstratum memory retain cli-demo "Bob is a data scientist"
agentstratum memory retain cli-demo "Alice and Bob are colleagues"

# Search memories
agentstratum memory recall cli-demo "Who works with Alice?"

# Generate a response
agentstratum memory reflect cli-demo "What do you know about the team?"

# Check bank disposition
agentstratum bank disposition cli-demo
# [/docs:cli-workflow]

echo "cli-reference.sh: All examples passed"
