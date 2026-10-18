# ContextDB instance management

First-release simplification of the V2 experiment. Workspace = Bank ID, with one independent PostgreSQL schema per workspace. Native Recall/Retain/Reflect, REST/MCP and workers remain in use.

- [Current optimized deployment and API contract](docs/contextdb-optimized-guide.md)
- [Scenario-ordered curl validation](docs/contextdb-optimized-curl-guide.md)
- [Original first-release design](docs/contextdb-first-release-design.md) — historical three-field authorization
- [Original deployment and manual acceptance](docs/contextdb-first-release-guide.md)
- [Management OpenAPI](docs/contextdb-control-plane.openapi.yaml)
- [Original V2 README](docs/archive/contextdb-v2-original-readme.md)
- [Historical V2 deployment](docs/contextdb-v2-deployment-usage-guide.md)
- [PostgreSQL extension installation](docs/postgresql-extensions.md) — installation instructions remain useful; production backend choice requires recovery validation.

## One operator credential

Generate the operator Admin Key offline. API configuration contains only its SHA-256 digest in `CONTEXTDB_ADMIN_KEY_SHA256`. The UI server reuses `HINDSIGHT_CP_DATAPLANE_API_KEY` for the same secret and an independent `HINDSIGHT_CP_ACCESS_KEY` for login. Neither business users nor the browser receive the server Admin Key. There is no CK, administrator business user, instance registration HTTP endpoint or online recovery endpoint.

Users contain a name and status. Business Keys have one `authorization` object: `selected` lists workspace/permission pairs, while `all` has one permission applying to current and future workspaces. New permissions default to `read_write`; PATCH authorization is a complete replacement with explicit permissions, and name-only PATCH leaves authorization unchanged. They cannot call management endpoints, even when authorized for all workspaces. User disable blocks all its Keys; revocation is permanent. Normal Key lists exclude revoked rows and return a persistent masked display identifier, never the secret or digest. Permission edits retain the original secret.

Read includes Recall, Reflect and existing memory/knowledge read operations; Reflect still consumes models and can produce internal logs. Read/write adds content mutations, not resource administration. Archive export/download, webhook configuration/delivery reads and management audit remain operator-only because they can contain signing secrets and HTTP credentials. Business task status reads cannot request raw payloads, and Webhook task diagnostics are projected out of REST/MCP responses. Shared workspace contents remain shared among authorized Keys.

## Fourteen management operations

All use `/ext/contextdb/v1` and `Authorization: Bearer <operator-admin-key>`:

- `GET /admin/session`
- `GET/POST /workspaces`, `GET/DELETE /workspaces/{id}`
- `GET /operations/{id}`
- `GET/POST /users`, `PATCH/DELETE /users/{id}`
- `GET/POST /users/{id}/keys`, `PATCH/DELETE /users/{id}/keys/{key_id}`

List APIs paginate (`items,total,limit,offset`) and support name search `q`. Workspace create/delete use `Idempotency-Key` and return 202; poll the operation until terminal. PATCH uses quoted `If-Match`/ETag to prevent concurrent permission overwrites. UI manages those transport details automatically. Key plaintext appears only on creation; reads never return secret/digest. Do not automatically retry Key creation after an unknown result.

## Deployment boundary

Use a new UTF8 database and run `python -m hindsight_ext_contextdb migrate` before API/Worker startup. New installations use internal metadata structure **2**, with a singleton `deployment_info` binding and separate per-workspace Key grants; the public API remains **v1**. The original `contextdb-first-release` structure 1 supports an offline transactional upgrade with API/Worker stopped. Unknown experimental V1/V2 formats and customized legacy catalogs are rejected without modification. Existing tables retain their ownership, ACLs and IDs; native memory schemas are not migrated by this command. Future released schemas need ordered compatible migrations; JSONB extension fields do not eliminate that requirement.

Direct SQL changes to authorization are not a supported customer interface. Management writes use READ COMMITTED plus the deployment row mutex; do not infer support for arbitrary isolation levels or bypass that protocol by editing metadata tables.

Enable the existing ContextDB tenant, validator, HTTP and MCP extensions; do not configure a legacy shared MCP token. This host branch includes the transport and lifecycle hooks the extension needs; it cannot be copied onto an arbitrary upstream checkout.

Workspace management now belongs to the Hindsight UI. Cloud control and the existing node Agent continue to deploy, start, stop and upgrade the instance. No new Agent protocol or cloud Console implementation is included.

## Safety and verification

Native Bank lifecycle calls stay blocked, including for the operator key, so they cannot bypass the workspace mapping. Workspace deletion retains durable admissions, task draining, leases and unknown-executor barriers. The operator credential does not bypass these checks. A true PostgreSQL superuser or OS root cannot be isolated by same-database ACLs.

Tests use independent temporary PostgreSQL instances and stub models. Real MaaS end-to-end quality, production capacity, PostgreSQL/PGroonga disaster recovery and cloud high availability require separate acceptance. The original running experience instance is unaffected by this checkout.

Regenerate the optional management contract without starting providers or a database:

```bash
PYTHONPATH="$PWD/hindsight-extensions/contextdb-service:$PWD/hindsight-api-slim" \
  .venv/bin/python hindsight-extensions/contextdb-service/scripts/generate_openapi.py
```

Add `--check` to verify the checked-in contract. Native REST schemas and generated clients are unchanged by the optional management API.
