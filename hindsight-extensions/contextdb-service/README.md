# ContextDB service extension

Optional service layer for a dedicated ContextDB deployment. It adds workspace,
member and opaque API Key management without changing the default Hindsight
server. A workspace owns one Bank in one PostgreSQL schema. Members in that Bank
share its memories: this extension does **not** implement private-user memories.

Host patches, verification and merge blockers are listed in [the implementation review](REVIEW.md).
This is an extension-first implementation, not a zero-change plugin for an unpatched upstream server.

## Responsibility split

- Existing cloud control backend: authenticate the human, check cloud/target
  permissions, replace customer-supplied actor headers, call the internal APIs.
- Management extension: authenticate the dedicated control Key and connection
  peer, verify the actor's current workspace role/target, persist metadata.
- Tenant/operation extensions: authenticate member Keys, select their schema and
  Bank, enforce operation scopes on REST/MCP, discover schemas for workers.
- Lifecycle runner: initialize a schema/Bank through native migration and engine
  interfaces, persist create/delete operation status, drain admitted requests and
  accepted native tasks before Bank cleanup.

The control Key identifies a trusted backend, not a human. It must not be given to
the browser, agents or SDK consumers. Public ingress must not expose the extension
management paths. These are required deployment controls, not properties a Key's
randomness magically provides.

## Deployment

Copy `hindsight_ext_contextdb/` into the server's Python import path, just like the
other extensions in this directory. No new runtime dependency or PyPI release is
required. API and standalone Worker use the same package/version/settings.

Protected `.env` configuration example, **not a shell script**. Replace every
placeholder before use; never commit the populated file:

```dotenv
HINDSIGHT_API_TENANT_EXTENSION=hindsight_ext_contextdb.tenant:ContextDBTenantExtension
HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=hindsight_ext_contextdb.validator:ContextDBOperationValidator
HINDSIGHT_API_HTTP_EXTENSION=hindsight_ext_contextdb.http:ContextDBHttpExtension
CONTEXTDB_INSTANCE_ID=<FIXED_DEPLOYMENT_ID>
CONTEXTDB_CLOUD_TENANT_ID=<FIXED_CLOUD_TENANT_ID>
CONTEXTDB_KEY_PEPPER=<PROTECTED_RANDOM_SECRET_AT_LEAST_32_CHARACTERS>
CONTEXTDB_CONTROL_KEYS='[{"key_id":"<32_HEX>","sha256":"<64_HEX>"}]'
CONTEXTDB_CONTROL_NETWORKS=127.0.0.1/32,::1/128
HINDSIGHT_API_MIGRATION_ISOLATION=false
```

`CONTEXTDB_CONTROL_NETWORKS` defaults to loopback for local testing. Production
must explicitly allow the private control backend/proxy networks. Run this API without
`--proxy-headers`: Uvicorn can otherwise rewrite the ASGI client before the
extension checks it. Management ingress rejects `Forwarded`/`X-Forwarded-For`;
the internal proxy must strip these headers, not forward customer assertions.
Internal HTTPS/private routing is provided by existing cloud ingress. User Key
authentication is not IAM integration. Keep migration isolation disabled: this
version cannot fence a migration child that outlives its API parent.
Do **not** configure `HINDSIGHT_API_MCP_AUTH_TOKEN`: the extension rejects the old
shared-token bypass. The tenant extension also rejects a missing ContextDB operation
validator, rather than starting an unrestricted Bank service.

Deployment bootstrap, before API/Worker startup:

```bash
# Use the protected environment; do not paste DB credentials into shell history.
python -m hindsight_ext_contextdb migrate
python -m hindsight_ext_contextdb generate-control-key
```

`migrate` requires an explicit `CONTEXTDB_BOOTSTRAP_DATABASE_URL`. Run it with one
deployment owner, not every API replica. It installs global `ctxdb_meta` tables;
runtime replicas only verify schema version. `generate-control-key` deliberately
prints the new Key once for the operator: put `secret` in the control backend's
protected configuration and only `key_id`/`sha256` in API/Worker settings. Never
capture the secret in a ticket or access log. Rotate by installing a second digest,
switching the backend, verifying all replicas have reloaded and removing the old
digest. User Key APIs never manage this deployment credential. This initial version
uses one deployment pepper; changing it invalidates all existing member Keys.

## Internal API

Native extension prefix: `/ext/contextdb/v1`. An existing **internal** ingress may
alias it to `/contextdb/v1`; public ingress must deny both paths. Every operation
requires `X-ContextDB-Control-Key` and `X-ContextDB-Actor-Subject` (verified login
subject, not target member ID). Node input errors return 400; missing/invalid service
Keys return 401 before body parsing. Requests never authenticate with member Keys.

| Resource | Operations |
|---|---|
| instances | POST register the fixed existing deployment; GET by ID |
| workspaces | POST/GET; GET/PATCH/DELETE by ID; one schema and Bank per workspace |
| operations | GET durable workspace provisioning/deletion status |
| members | POST/GET; GET/PATCH/DELETE by ID; admin/member, soft deletion |
| member api-keys | POST/GET; POST `/api-keys/{key_id}/revoke` to revoke |

Instance registration does not provision cloud compute/RDS or create a product
hierarchy above workspaces. The cloud control backend already owns that lifecycle.
All growing collections use bounded `limit`/`offset` and return `total`. PATCH
requires quoted version `If-Match`. Space create/delete requires `Idempotency-Key`.
Member Key creation returns the full Key exactly once; replay reports the original
Key ID with 409, never the secret. Lists omit digests and secrets. All responses
use no-store and carry a request ID (204 uses `X-Request-ID`).
Workspace names are control metadata; renaming does not currently synchronize
the native Bank's initial display label or change its ID/schema.

The initial workspace creator becomes its bound administrator. Administrators may
manage members and their Keys; members may manage only their own Keys via the cloud
control backend. Login bindings are verified by that backend, not revalidated via
IAM by this extension. The last active bound administrator cannot be removed.

First-use sequence through the trusted control backend: register the configured
instance, create a workspace, poll its management operation until `succeeded`
and the workspace is `active`, then create members and issue their Keys. Do not
send business retain/recall requests while the workspace is still being created.

## Customer and worker interfaces

Keep native REST paths and MCP endpoints. Connect MCP to `/mcp/<workspace_id>/`;
pass the member Key as Bearer. No client-global configuration is required or changed.

- `memory.read`: same-Bank memory reads/recall, not only the member's memories.
- `memory.write`: retain and supported memory/document/model/directive edits;
  requires `memory.read`. It does not grant Bank deletion/configuration/aliases.
- `reflect`: reflect, with `memory.read` also required.
- `knowledge.read`: native knowledge-page reads/search/export. It does not turn
  recall into a knowledge-only query or grant memory recall.

Tool filtering only controls discovery; engine validators enforce calls too. Scope
and workspace/member/Key state are checked from PG, without an authorization cache.
Freeze/revocation rejects new authentications, but does not cancel admitted requests
or previously queued tasks. Worker discovery includes inactive draining spaces;
periodic submissions into those spaces are refused. Purpose-limited lifecycle calls
are separate from ordinary `internal=True` worker contexts. These are server-side
request contexts, not issued short-lived tokens or customer-supplied headers.
Lifecycle contexts also carry a current management-operation ID/token, checked
against PG; a purpose label alone does not grant Bank management. Stateful MCP
restores identity and admission from each authenticated HTTP message's trusted
ASGI scope, not from the session's initial Key or client identity headers.

## Storage and operations

`schema.sql` defines the independent metadata model. Bank memory tables remain
upstream-owned. Backups/restores must include `ctxdb_meta` as well as all workspace
schemas; native per-Bank backup alone is not a complete ContextDB service backup.
Schema separation isolates tables/indexes, not CPU, I/O, WAL or recovery resources.
Admission and control metadata use separate connection pools to the **same RDS
PG**, not another MetaPG component. They keep held drain locks from exhausting the
native work pool. Budget their connections across every API/Worker replica, along
with native pools and migration connections; pool limits are not PG resource
isolation or a tested production capacity recommendation.

Migration and metadata transactions are not one atomic operation. Lease tokens
fence metadata completion and short template queue writes, not native DDL: a
running migration thread is not cancellable, and upstream migration serialization
still applies. No schema or DSN
comes from a customer request. Deletion clears the Bank after drain and retains
the schema/table structure and deleted metadata as a tombstone; it does not DROP
an entire schema/database or reuse that workspace identity.

A committed `request_admissions` record exists before HTTP/queue work starts.
Normal completion removes it; interrupted/unknown execution retains it. PG row
locks disappear on session loss, but these records survive and block Bank cleanup.
An accepted DELETE may therefore remain waiting: `error_code=waiting_for_admissions`
or `waiting_for_tasks` describes its gate, not a failed or completed deletion.
There is no automatic timeout or customer override for an unknown executor. Recovery
requires a trusted maintenance window that fences/stops old API/Worker processes
and their PG work sessions before resolving the corresponding records. Do not
clear records based only on age or a missing PID. Automated fenced recovery and
production connection/capacity testing remain integration work.

The metadata DDL is an unpublished initial schema, not an in-place upgrader for
older local prototypes. A future released version needs explicit versioned migrations.

The current metadata audit records successful management changes and Key
ownership. It is not a complete audit of failed authentication, all business
requests or lifecycle execution outcomes; those need separate production planning.

## Verification

From the repository root with a host development environment:

```bash
PYTHONPATH=hindsight-extensions/contextdb-service .venv/bin/python -m pytest \
  hindsight-extensions/contextdb-service/tests -q
PYTHONPATH=hindsight-system-tests:hindsight-extensions/contextdb-service \
  .venv/bin/python -m pytest hindsight-system-tests/tests/test_10*_contextdb*.py -q
```

Tests use unique temporary pg0 instances and synthetic Keys/providers; they never
reuse the default dev database. Blackbox stories use the published Python and MCP
clients and run with both embedded and standalone Workers. Optional dependencies
for tests include pg0-embedded; the server runtime remains PostgreSQL-only here.
See the research repository's verification record and PG design for scoped expert
review outcomes and remaining production integration gates; passing these tests
is not production acceptance.
