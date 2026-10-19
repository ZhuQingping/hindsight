# contextbase-embed

ContextBase embedded CLI - local memory operations with automatic daemon management.

This package provides a simple CLI for storing and recalling memories using ContextBase's memory engine. It automatically manages a background daemon for fast operations - no manual server setup required.

## How It Works

`contextbase-embed` uses a background daemon architecture for optimal performance:

1. **First command**: Automatically starts a local daemon (first run downloads dependencies and loads ML models - can take 1-3 minutes)
2. **Subsequent commands**: Near-instant responses (~1-2s) since daemon is already running
3. **Auto-shutdown**: Daemon automatically exits after 5 minutes of inactivity

The daemon runs on `localhost:8888` and uses an embedded PostgreSQL database (pg0) - everything stays local on your machine.

## Distribution configuration

The operator must provide `CONTEXTBASE_EMBED_PACKAGE` (embed Python package spec) and `CONTEXTBASE_EMBED_API_PACKAGE` (API Python package spec) before automatic installation. Optional Web startup requires `CONTEXTBASE_EMBED_CP_PACKAGE`. No production registry name or domain is assumed. The engine translates public `CONTEXTBASE_API_*` settings only at its internal process boundary; profile files and CLI output use the public names.

The CLI auto-installer remains pending until the operator confirms its distribution source. It currently exits with an explicit pending message and does not make a network request. Python engine installation through the configured package spec is retained.

## Installation

```bash
pip install "$CONTEXTBASE_EMBED_PACKAGE"
# or with uvx (no install needed)
uvx --from "$CONTEXTBASE_EMBED_PACKAGE" contextbase-embed --help
```

## Quick Start

```bash
# Interactive setup (configures default profile)
contextbase-embed configure

# Or set your LLM API key manually
export OPENAI_API_KEY=sk-...

# Store a memory (bank_id = "default")
contextbase-embed memory retain default "User prefers dark mode"

# Recall memories
contextbase-embed memory recall default "What are user preferences?"
```

All commands use the "default" profile unless you specify a different one with `--profile` or `CONTEXTBASE_EMBED_PROFILE`.

## Commands

### configure

Configure the default profile or create/update named profiles:

```bash
# Interactive setup for default profile
contextbase-embed configure

# Create/update named profile with single command
contextbase-embed configure --profile my-app \
  --env CONTEXTBASE_API_LLM_PROVIDER=openai \
  --env CONTEXTBASE_API_LLM_API_KEY=sk-xxx

# Create/update named profile interactively
contextbase-embed configure --profile staging
```

This will:
- Let you choose an LLM provider (OpenAI, Groq, Google, Ollama, GitHub Copilot)
- Configure credentials when the provider requires them
- Set the model
- Start the daemon with your configuration

### memory retain

Store a memory:

```bash
contextbase-embed memory retain default "User prefers dark mode"
contextbase-embed memory retain default "Meeting on Monday" --context work
contextbase-embed memory retain myproject "API uses JWT authentication"
```

### memory recall

Search memories:

```bash
contextbase-embed memory recall default "user preferences"
contextbase-embed memory recall default "upcoming events"
```

Use `-o json` for JSON output:
```bash
contextbase-embed memory recall default "user preferences" -o json
```

### memory reflect

Get contextual answers that synthesize multiple memories:

```bash
contextbase-embed memory reflect default "How should I set up the dev environment?"
```

### bank list

List all memory banks:

```bash
contextbase-embed bank list
```

### profile

Manage configuration profiles:

```bash
# List all profiles with status
contextbase-embed profile list

# Show current active profile
contextbase-embed profile show

# Set active profile (persists across commands)
contextbase-embed profile set-active my-app

# Clear active profile (revert to default)
contextbase-embed profile set-active --none

# Delete a profile
contextbase-embed profile delete my-app
```

### daemon

Manage the background daemon:

```bash
contextbase-embed daemon status    # Check if daemon is running
contextbase-embed daemon start     # Start the daemon
contextbase-embed daemon stop      # Stop the daemon
contextbase-embed daemon logs      # View last 50 lines of logs
contextbase-embed daemon logs -f   # Follow logs in real-time
contextbase-embed daemon logs -n 100  # View last 100 lines
```

## Configuration

### Interactive Setup

Run `contextbase-embed configure` for a guided setup that saves to `~/.contextbase/embed`.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONTEXTBASE_EMBED_PROFILE` | Profile name to use (overrides active profile) | None (uses default profile) |
| `CONTEXTBASE_API_LLM_API_KEY` | LLM API key (or use `OPENAI_API_KEY`); required only when the selected provider uses an API key | Provider-dependent |
| `CONTEXTBASE_API_LLM_PROVIDER` | LLM provider (`openai`, `groq`, `gemini`, `ollama`, `github-copilot`) | `openai` |
| `CONTEXTBASE_API_LLM_MODEL` | LLM model | `gpt-4o-mini` |
| `CONTEXTBASE_EMBED_API_URL` | Use external API server instead of starting local daemon | None (starts local daemon) |
| `CONTEXTBASE_EMBED_API_TOKEN` | Authentication token for external API (sent as Bearer token) | None |
| `CONTEXTBASE_EMBED_API_DATABASE_URL` | Database URL for daemon | `pg0://contextbase-embed` |
| `CONTEXTBASE_EMBED_DAEMON_LOG_MAX_BYTES` | Rotate the daemon log at startup at this size; `0` disables rotation | `10485760` (10 MiB) |
| `CONTEXTBASE_EMBED_DAEMON_LOG_BACKUP_COUNT` | Retained backups; `0` truncates a full log at startup | `3` |

The size is checked only when a daemon starts, so a single uninterrupted run is never truncated and can
grow past `MAX_BYTES` — and at the next start that whole file is kept as the first backup. Retained size
is therefore around `MAX_BYTES × (BACKUP_COUNT + 1)` (40 MiB by default) only for daemons that restart
regularly; a daemon left running for weeks keeps whatever it wrote. Restart it, or lower
`CONTEXTBASE_EMBED_DAEMON_IDLE_TIMEOUT`, to keep the bound meaningful.

**Using an External API Server:**

To connect to an existing ContextBase API server instead of starting the local daemon:

```bash
export CONTEXTBASE_EMBED_API_URL=http://your-server:8000
export CONTEXTBASE_EMBED_API_TOKEN=your-api-token  # Optional, if API requires auth
contextbase-embed memory recall default "query"
```

**Custom Database:**

To use an external PostgreSQL database instead of the embedded pg0 database (useful when running as root or in containerized environments):

```bash
export CONTEXTBASE_EMBED_API_DATABASE_URL=postgresql://user:password@localhost:5432/dbname
contextbase-embed daemon start
```

**Note:** All banks share a single database. Bank isolation happens within the database via the `bank_id` parameter passed to CLI commands.

### Configuration Profiles

Profiles let you maintain multiple independent configurations (e.g., different API endpoints, LLM providers, or projects). Each profile runs its own daemon on a unique port (8889-9888).

**The Default Profile:**

When you run `contextbase-embed configure` without specifying a profile, it configures the "default" profile. This uses the backward-compatible configuration at `~/.contextbase/embed` and runs on port 8888.

**Creating Named Profiles:**

```bash
# Create a profile with single command
contextbase-embed configure --profile my-app \
  --env CONTEXTBASE_API_LLM_PROVIDER=openai \
  --env CONTEXTBASE_API_LLM_API_KEY=sk-xxx \
  --env CONTEXTBASE_API_LLM_MODEL=gpt-4o-mini

# Create a profile interactively
contextbase-embed configure --profile staging
```

**Using Profiles:**

```bash
# Option 1: Environment variable (recommended for apps)
CONTEXTBASE_EMBED_PROFILE=my-app contextbase-embed memory retain default "text"

# Option 2: CLI flag
contextbase-embed --profile my-app memory recall default "query"

# Option 3: Set as active (persists across commands)
contextbase-embed profile set-active my-app
contextbase-embed memory recall default "query"  # Uses my-app profile

# Clear active profile (revert to default)
contextbase-embed profile set-active --none
```

**Profile Management:**

```bash
# List all profiles with status
contextbase-embed profile list

# Show active profile
contextbase-embed profile show

# Delete a profile
contextbase-embed profile delete my-app
```

**Profile Resolution Priority:**
1. `CONTEXTBASE_EMBED_PROFILE` environment variable (highest)
2. `--profile` CLI flag
3. Active profile from `~/.contextbase/active_profile` file
4. Default profile (lowest)

**Note:** If a profile is specified but doesn't exist, the command will fail with an error. Profiles must be explicitly created using `contextbase-embed configure --profile <name>`.

### Files

**Default Profile:**
| Path | Description |
|------|-------------|
| `~/.contextbase/embed` | Configuration file for default profile |
| `~/.contextbase/daemon.log` | Daemon logs for default profile |
| `~/.contextbase/daemon.lock` | Daemon lock file (PID) for default profile |

**Named Profiles:**
| Path | Description |
|------|-------------|
| `~/.contextbase/profiles/<name>.env` | Configuration file for profile |
| `~/.contextbase/profiles/<name>.log` | Daemon logs for profile |
| `~/.contextbase/profiles/<name>.lock` | Daemon lock file (PID) for profile |
| `~/.contextbase/profiles/metadata.json` | Profile metadata (ports, timestamps) |
| `~/.contextbase/active_profile` | Active profile name (when set with `profile set-active`) |

## Use with AI Coding Assistants

This CLI is designed to work with AI coding assistants like Claude Code, Cursor, and Windsurf. Install the ContextBase skill:

```bash
# Install the plugin from the distribution approved by your service operator.
```

This will configure the LLM provider and install the skill to your assistant's skills directory.

## Troubleshooting

**Daemon won't start:**
```bash
# Check logs for errors
contextbase-embed daemon logs

# Stop any stuck daemon and restart
contextbase-embed daemon stop
contextbase-embed daemon start
```

**Slow first command:**
This is expected - the first command needs to download dependencies, start the daemon, and load ML models. First run can take 1-3 minutes depending on network speed. Subsequent commands will be fast (~1-2s).

**Change configuration:**
```bash
# Re-run configure (automatically restarts daemon)
contextbase-embed configure
```

## License

Apache 2.0
