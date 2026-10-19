
# CLI Reference

The Hindsight CLI provides command-line access to memory operations and bank management. All commands follow the [OpenAPI specification](../openapi.json), so you can use `--help` on any command to see all available options.

## Installation

```bash
curl -fsSL https://hindsight.vectorize.io/get-cli | bash
```

## Configuration

Configure the API URL:

```bash
# Set directly
agentstratum configure --api-url http://localhost:8888

# With API key for authentication
agentstratum configure --api-url http://localhost:8888 --api-key your-api-key
```

You can also run `hindsight configure` with no flags to be prompted interactively, or use environment variables (highest priority):

```bash
export HINDSIGHT_API_URL=http://localhost:8888
export HINDSIGHT_API_KEY=your-api-key
```

### Named Profiles

When you need to switch between multiple Hindsight deployments (e.g. local,
staging, production) without constantly rewriting `~/.hindsight/config`, use
named profiles. Each profile is a TOML file at
`~/.hindsight/cli-profiles/<name>.toml` and is selected per-invocation with
`-p/--profile` (or by setting `$HINDSIGHT_PROFILE`).

```bash
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
```

Profile files are written with `0600` permissions on Unix so the API key is
only readable by the owner.

**Configuration precedence** (highest first):

1. Environment variables (`HINDSIGHT_API_URL`, `HINDSIGHT_API_KEY`)
2. Named profile — explicit `-p <name>`, otherwise `$HINDSIGHT_PROFILE`
3. Shared config file (`~/.hindsight/config`, written by `hindsight configure`)
4. Default (`http://localhost:8888`)

`HINDSIGHT_API_URL` / `HINDSIGHT_API_KEY` always override profile values, which
makes it safe to use `-p` in scripts while letting CI inject credentials via
environment.

## Core Commands

### Retain (Store Memory)

Store a single memory:

```bash
agentstratum memory retain my-cli-bank "Alice works at Google as a software engineer"

# With context
agentstratum memory retain my-cli-bank "Bob loves hiking" --context "hobby discussion"

# Queue for background processing
agentstratum memory retain my-cli-bank "Meeting notes" --async

# With an event date (ISO 8601 datetime or date)
agentstratum memory retain my-cli-bank "Project launched" --timestamp 2024-01-15

# Store without a timestamp (overrides the default of "now")
agentstratum memory retain my-cli-bank "Background fact" --timestamp unset
```

### Retain Files

Bulk import from files:

```bash
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
```

### Recall (Search)

Search memories using semantic similarity:

```bash
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
```

### Reflect (Generate Response)

Generate a response using memories and bank disposition:

```bash
agentstratum memory reflect my-cli-bank "What do you know about Alice?"

# With additional context
agentstratum memory reflect my-cli-bank "Should I learn Python?" --context "career advice"

# Higher budget for complex questions
agentstratum memory reflect my-cli-bank "Summarize my week" --budget high

# Filter by fact type
agentstratum memory reflect my-cli-bank "query" \
  --fact-types world,experience \
  --exclude-mental-models
```

### Memory History

View the observation history for a specific memory unit:

```bash
agentstratum memory history my-cli-bank "$MEMORY_ID"
```

### Clear Observations

Remove all observations for a memory unit, keeping the core fact:

```bash
agentstratum memory clear-observations my-cli-bank "$MEMORY_ID"

# Skip confirmation prompt
agentstratum memory clear-observations my-cli-bank "$MEMORY_ID" -y
```

## Bank Management

### List Banks

```bash
agentstratum bank list
```

### View Disposition

```bash
agentstratum bank disposition my-cli-bank
```

### Set Disposition

```bash
agentstratum bank set-disposition my-cli-bank --skepticism 3 --literalism 4 --empathy 5
```

### View Statistics

```bash
agentstratum bank stats my-cli-bank
```

### Set Bank Name

```bash
agentstratum bank name my-cli-bank "My Assistant"
```

### Set Mission

```bash
agentstratum bank mission my-cli-bank "I am a helpful AI assistant interested in technology"
```

### Clear Observations (Bank-wide)

Remove all observations across the entire bank:

```bash
agentstratum bank clear-observations my-cli-bank

# Skip confirmation prompt
agentstratum bank clear-observations my-cli-bank -y
```

### Recover Consolidation

Recover from a failed or stuck consolidation:

```bash
agentstratum bank consolidation-recover my-cli-bank
```

## Document Management

```bash
# List documents
agentstratum document list my-cli-bank

# Get document details
agentstratum document get my-cli-bank "$DOCUMENT_ID"

# Replace a document's tags
agentstratum document update my-cli-bank "$DOCUMENT_ID" --tags project-x,meetings

# Delete document and its memories
agentstratum document delete my-cli-bank "$DOCUMENT_ID"
```

## Entity Management

```bash
# List entities
agentstratum entity list my-cli-bank

# Get entity details
agentstratum entity get my-cli-bank "$ENTITY_ID"
```

## Operation Management

Track and manage async operations (retain-files, consolidation, etc.):

```bash
# List operations
agentstratum operation list my-cli-bank

# Get operation status
agentstratum operation get my-cli-bank "$OPERATION_ID"

# Cancel a pending operation
agentstratum operation cancel my-cli-bank "$OPERATION_ID"

# Retry a failed operation
agentstratum operation retry my-cli-bank "$OPERATION_ID"
```

## Webhook Management

Configure event delivery hooks for bank activity:

```bash
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
```

## Knowledge Base

Manage a bank's knowledge pages — living documents organized in a folder tree. See [Knowledge Pages](../developer/api/knowledge-pages.md) for what they are and how they refresh.

```bash
# Show the folder/page tree (pages that have fallen behind are marked stale)
agentstratum knowledge-base tree my-cli-bank
```

```bash
# Create a folder, optionally nested under another
agentstratum knowledge-base create-folder my-cli-bank "Operations"
```

```bash
agentstratum knowledge-base create-folder my-cli-bank "Runbooks" --parent-id "$FOLDER_ID"
```

```bash
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
```

```bash
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
```

> **💡 Tip**
>
`hindsight fs mount --bank <bank_id>` mirrors the same knowledge base onto disk as
real markdown files, kept current by a background refresh loop — handy when you'd
rather use `grep`, `rg`, or your editor than the commands above.
## Audit Logs

Inspect the audit trail for a bank:

```bash
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
```

## Output Formats

```bash
# Pretty (default)
agentstratum memory recall my-cli-bank "query"

# JSON
agentstratum memory recall my-cli-bank "query" -o json

# YAML
agentstratum memory recall my-cli-bank "query" -o yaml
```

## Global Options

| Flag | Description |
|------|-------------|
| `-v, --verbose` | Show detailed output including request/response |
| `-o, --output <format>` | Output format: pretty, json, yaml |
| `-p, --profile <name>` | Use a named profile (see [Named Profiles](#named-profiles)) |
| `--help` | Show help |
| `--version` | Show version |

## Control Plane UI

Launch the web-based Control Plane UI directly from the CLI:

```bash
hindsight ui
```

This runs the Control Plane locally on port 9999 using the API URL from your configuration. The UI provides:

- **Memory bank management** — Browse and manage all your banks
- **Entity explorer** — Visualize the knowledge graph
- **Query testing** — Interactive recall and reflect testing
- **Operation history** — View ingestion and processing logs

> **💡 Tip**
>
The UI command requires Node.js to be installed. It automatically downloads and runs the `@vectorize-io/hindsight-control-plane` package via npx.
## Interactive Explorer

Launch the TUI explorer for visual navigation of your memory banks:

```bash
hindsight explore
```

The explorer provides an interactive terminal interface to:

- **Browse memory banks** — View all banks and their statistics
- **Search memories** — Run recall queries with real-time results
- **Inspect memory details** — Open a memory to view its text, metadata, entities, and full JSON fields
- **Inspect entities** — Explore the knowledge graph and entity relationships
- **View facts** — Browse world facts, experiences, and observations
- **Navigate documents** — See source documents and their extracted memories

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑/↓` | Navigate items |
| `Enter` | Select item / view details |
| `Tab` | Switch panels |
| `/` | Search |
| `q` | Quit |

{/* Screenshot placeholder: explore command TUI */}

## Example Workflow

```bash
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
```
