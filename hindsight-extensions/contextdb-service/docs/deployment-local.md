# Local ContextBase (Linux x86_64)

Prepare dependencies with `bash scripts/dev/setup.sh`, configure model providers in
`.env`, then run `bash scripts/dev/start.sh`. Local startup always initializes and
uses ContextBase authentication: API/MCP clients need a scoped API Key, and the UI
requires its independent login password. Initialization errors stop startup.

`bash scripts/dev/start-api.sh` runs the authenticated API with its Worker.
`bash scripts/dev/start-control-plane.sh` connects the development UI to an already
initialized local deployment. `--port`, `--ui-port` and `--random-port` are supported
by the local launcher. API/UI hosts respect their `API_HOST` / `CP_HOST` settings.
For remote UI access, configure `CONTEXTBASE_CP_PUBLIC_ORIGIN` to its browser origin.

When `CONTEXTBASE_API_DATABASE_URL` (or the internal `HINDSIGHT_API_DATABASE_URL`)
is absent or `pg0`, startup uses embedded PostgreSQL. An explicit external PostgreSQL
URL is used directly; it never falls back to pg0 after connection/authentication failure.
External databases must already have the required extensions installed.

| Setting | Default | Purpose |
| --- | --- | --- |
| `CONTEXTDB_DEPLOY_DIR` | `$HOME/.contextbase/local` | Private persistent state and credentials |
| `CONTEXTDB_PG_DATA_DIR` | `$CONTEXTDB_DEPLOY_DIR/pgdata` | Embedded PostgreSQL data directory |

For example, set `CONTEXTDB_DEPLOY_DIR=/data/contextbase` in `.env` before starting.
Directories must be private (0700); generated secret files are 0600. The pg0 binary
cache and registry are isolated in `$CONTEXTDB_DEPLOY_DIR/pg0-home`. Run as a non-root
user. The pg0 0.15.2 Linux wheel requires x86_64 and glibc 2.35 or later.

The embedded startup enables `vector`, `pg_trgm` and `btree_gin` before running the
existing deployment preflight and metadata initialization. The default full-text
backend is native English; these bundled extensions do not add Chinese tokenization.

The launcher prints the location of `ui-secrets.json`, which contains the local UI
password. The independent administrator API Key is in `admin-key.json`; API HMAC
pepper is in `api-secrets.json`; PostgreSQL credentials are in `pg-secrets.json`.
Passwords and connection URLs are not printed by the launcher. Preserve the complete
state directory, not just `pgdata`, for restart and backup. A missing secret for an
initialized database is an error, not a request to generate a replacement.

Stopping the local launcher stops its API/Worker/UI and then its embedded PG. It
does not delete data. An explicit external PostgreSQL server is never stopped.
Only one launcher can own a deployment directory at a time. The existing
`deployment-native.md` and `deployment-docker.md` flows remain the production entrypoints.
