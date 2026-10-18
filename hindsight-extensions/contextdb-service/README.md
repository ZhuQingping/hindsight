# ContextDB instance management

First-release simplification of the V2 experiment. Workspace = Bank ID, with one independent PostgreSQL schema per workspace. Native Recall/Retain/Reflect, REST/MCP and workers remain in use.

The complete implementation and documentation ship on `contextdb/first-release`, as one feature commit on Hindsight `a77c1f3412a7b82f36588dffce1a8d7480e99cc7`. Earlier development branches are retired; the original V1 branch remains a separate comparison baseline.

- [Current consolidated first-release review](REVIEW-first-release-consolidated-20261018.md) — delivery branch, current checks and release boundaries
- [Historical service-night acceptance](REVIEW-service-night-20261017.md) — original snapshot evidence and production boundaries
- [Topology, MaaS and full-text research](docs/contextdb-service-research-validation.md)
- [Previous acceptance and independent reviews](REVIEW-release-hardening-20261016.md) — historical baseline; current verification scope is recorded in the optimization status
- [Current design](docs/contextdb-release-design.md)
- [Optimization decisions and documentation consistency review](docs/contextdb-optimization-status.md)
- [Current optimized deployment and API contract](docs/contextdb-optimized-guide.md)
- [Control-plane and node integration guide](docs/contextdb-service-integration-guide.md) — human deployment checklist and commands
- [Node Agent deployment contract](docs/contextdb-deployment-contract.md) — typed JSON intent, private inputs, render/init/status and container examples
- [Operations and diagnostics](docs/contextdb-operations-runbook.md)
- [Scenario-ordered curl validation](docs/contextdb-optimized-curl-guide.md)
- [Original first-release design](docs/contextdb-first-release-design.md) — historical three-field authorization
- [Historical first-release deployment and manual acceptance](docs/contextdb-first-release-guide.md) — reference only; its commands do not apply to current code
- [Management OpenAPI](docs/contextdb-control-plane.openapi.yaml)
- [Original V2 README](docs/archive/contextdb-v2-original-readme.md)
- [Historical V2 deployment](docs/contextdb-v2-deployment-usage-guide.md)
- [PostgreSQL extension installation](docs/postgresql-extensions.md) — installation instructions remain useful; production backend choice requires recovery validation.

## One operator credential

Generate the operator Admin Key offline. Offline initialization imports its HMAC-SHA256 digest into PG, using the same authenticator as business keys; role comes from PG. The UI server reuses `HINDSIGHT_CP_DATAPLANE_API_KEY` for the same secret and an independent `HINDSIGHT_CP_ACCESS_KEY` for login. Neither business users nor the browser receive the server Admin Key. The single protected administrator is stored in users/api_keys but hidden from ordinary lists/CRUD. No CK, instance registration HTTP endpoint or online recovery endpoint is introduced.

Users contain a name and status. Business Keys have one `authorization` object: `selected` lists workspace/permission pairs, while `all` has one permission applying to current and future workspaces. New permissions default to `read_write`; PATCH authorization is a complete replacement with explicit permissions, and name-only PATCH leaves authorization unchanged. They cannot call management endpoints, even when authorized for all workspaces. User disable blocks all its Keys; revocation is permanent. Normal Key lists exclude revoked rows and return a persistent masked display identifier, never the secret or digest. Permission edits retain the original secret.

Read includes Recall, Reflect and existing memory/knowledge read operations; Reflect still consumes models and can produce internal logs. Read/write adds content mutations, not resource administration. Archive export/download, historical webhook diagnostics and management audit remain operator-only because they can contain signing secrets and HTTP credentials. Native database-backed LLM trace/audit recording is disabled in this first release; diagnostic read gates do not imply new records are produced. Business task status reads cannot request raw payloads, and Webhook task diagnostics are projected out of REST/MCP responses. Shared workspace contents remain shared among authorized Keys.

## Fourteen management operations

All use `/ext/contextdb/v1` and `Authorization: Bearer <operator-admin-key>`:

- `GET /admin/identity`
- `GET/POST /workspaces`, `GET/DELETE /workspaces/{bank_id}`
- `GET /operations/{id}`
- `GET/POST /users`, `PATCH/DELETE /users/{id}`
- `GET/POST /users/{id}/keys`, `PATCH/DELETE /users/{id}/keys/{key_id}`

List APIs paginate (`items,total,limit,offset`) and support name search `q`. Workspace create/delete use `Idempotency-Key` and return 202; poll the operation until terminal. Workspace DELETE requires the identity-bound workspace ETag in `If-Match`; missing preconditions return428 and stale generations return412. PATCH uses quoted `If-Match`/ETag to prevent concurrent permission overwrites. UI manages those transport details automatically. Key plaintext appears only on creation; reads never return secret/digest. Do not automatically retry Key creation after an unknown result.

## Deployment boundary

Initialization, offline administrator rotation and API/Worker all use `HINDSIGHT_API_DATABASE_URL` and the same service role; there is no separate bootstrap URL. Provision the database and extensions before starting the service.

Use a new UTF8 database and run `scripts/service.sh init` (see deployment guide) before API/Worker startup. The first published metadata structure is **1**, with a singleton `deployment_info` binding and separate per-workspace Key grants; the public API remains **v1**. Initialization creates the current schema in a new database and is repeatable with the same identity and secrets. Unreleased development schemas are rejected without modification, even if an old layout was labelled1; do not relabel an existing database. Preserve development data separately and validate the release against a new dedicated database. Future released changes must add ordered migrations from this v1 baseline. The metadata command does not upgrade native memory tables; native schema changes require a documented offline upgrade with all writers stopped. JSONB extension fields do not eliminate that requirement.

Direct SQL changes to authorization are not a supported customer interface. Management writes use READ COMMITTED plus the deployment row mutex; do not infer support for arbitrary isolation levels or bypass that protocol by editing metadata tables.

Enable the existing ContextDB tenant, validator, HTTP and MCP extensions; do not configure a legacy shared MCP token. This host branch includes the transport and lifecycle hooks the extension needs; it cannot be copied onto an arbitrary upstream checkout.

New workspace names normalize to lowercase ASCII `^[a-z][a-z0-9_]{0,53}$` and are the stable external `bank_id`, e.g. `MySQL` becomes `mysql`, with schema `ctxdb_ws_mysql`. Hyphens/Chinese display names are not accepted in this first release because native migrations contain unquoted schema SQL. Internal immutable UUID `workspace_id` remains the authorization/lifecycle identity. Selected grant inputs use `bank_id`; the UI additionally sends the observed `workspace_id` expectation so a stale picker cannot authorize a same-name successor.

Runtime requires `HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false`; explicit workspace provisioning migrations have a durable generation guard. Full WorkerPoller execution, including final status writes, also has a durable admission: cancelling a queue row alone does not prove the writer stopped. Native webhook configuration/delivery is unsupported in this first release; deployment configuration is rejected rather than leaving untagged jobs stuck. Native fire-and-forget LLMTrace/Audit INSERTs also do not carry the workspace execution lifetime: set `HINDSIGHT_API_LLM_TRACE_ENABLED=false` and `HINDSIGHT_API_AUDIT_LOG_ENABLED=false` explicitly. The native trace default is true, so omitting its override is rejected; the renderer supplies both false. The extension forbids `audit_log_enabled` overrides for internal and external callers, and rejects enabled audit in existing banks or default templates before startup/migration. `ctxdb_meta.audit_events` management auditing remains enabled. Native UI trace/audit pages produce no new records; JSON runtime logs, metrics and OpenTelemetry remain available.

Workspace management now belongs to the Hindsight UI. Cloud control and the existing node Agent continue to deploy, start, stop and upgrade the instance. The existing node Agent consumes the local JSON/file/foreground-command contract; no new always-running Agent daemon or cloud Console implementation is introduced. Both merged and split worker configurations require an explicit deployment choice; see the integration guide.

## Safety and verification

Native Bank lifecycle calls stay blocked, including for the operator key, so they cannot bypass the workspace mapping. Workspace deletion retains durable admissions, task draining, leases and unknown-executor barriers, then physically removes the owned schema, workspace row and selected grants. Independent terminal operation snapshots have bounded retention (168h by default). The operator credential does not bypass these checks. A true PostgreSQL superuser or OS root cannot be isolated by same-database ACLs.

Current verification includes isolated real PostgreSQL, native Hindsight/ContextDB system suites, UI and bounded real MaaS probes; see the optimization status for snapshot-specific counts. The night snapshot container passed local checks with the documented CPU override; current-source images still need rebuilding. Production capacity, target RDS Chinese full-text availability, PostgreSQL/PGroonga disaster recovery and cloud high availability remain separate acceptance items. Unreleased development databases are not adopted or upgraded; initialize a new dedicated database. Native-schema offline migration applies only to an already supported release structure.

Regenerate the optional management contract without starting providers or a database:

```bash
PYTHONPATH="$PWD/hindsight-extensions/contextdb-service:$PWD/hindsight-api-slim" \
  .venv/bin/python hindsight-extensions/contextdb-service/scripts/generate_openapi.py
```

Add `--check` to verify the checked-in contract. Native REST schemas and generated clients are unchanged by the optional management API.
