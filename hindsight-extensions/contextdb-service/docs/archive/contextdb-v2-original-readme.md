> 历史 V2 说明，保留原方案内容，仅调整本地文档链接。新部署请使用 [首发指南](../contextdb-first-release-guide.md)。

# ContextDB tenant administration

This optional extension manages a single dedicated cloud tenant/instance. Users
and workspaces are siblings. Each workspace has one immutable Bank ID and one
PostgreSQL schema. Existing native memory, knowledge, Recall/Retain/Reflect and
Worker implementations remain in use.

Versioned operational documentation:

- [Deployment and usage](../contextdb-v2-deployment-usage-guide.md)
- [Environment configuration](../contextdb-v2-deployment-environment.md)
- [Manual validation and demo](../contextdb-v2-local-validation-guide.md)
- [PostgreSQL extensions](../postgresql-extensions.md)
- [Management OpenAPI](../contextdb-control-plane.openapi.yaml)
- [V1/V2 comparison](../version-comparison.md)
- [Implementation review and verification](../../REVIEW.md)

## Deployment

Use a **new database**. Metadata version 2 deliberately refuses version 1 and
unversioned `ctxdb_meta`; it never migrates or overwrites existing metadata.

```bash
export CONTEXTDB_INSTANCE_ID=example-instance
export CONTEXTDB_CLOUD_TENANT_ID=example-cloud-tenant
export CONTEXTDB_KEY_PEPPER='deployment-secret-of-at-least-32-characters'
export CONTEXTDB_CONTROL_KEYS='[{"key_id":"CONTROL_KEY_ID","sha256":"CONTROL_KEY_SHA256"}]'
export CONTEXTDB_CONTROL_NETWORKS='127.0.0.1/32,::1/128'
export CONTEXTDB_BOOTSTRAP_DATABASE_URL='postgresql://service@localhost:PORT/new_database'
python -m hindsight_ext_contextdb migrate

export HINDSIGHT_API_TENANT_EXTENSION=hindsight_ext_contextdb.tenant:ContextDBTenantExtension
export HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=hindsight_ext_contextdb.validator:ContextDBOperationValidator
export HINDSIGHT_API_HTTP_EXTENSION=hindsight_ext_contextdb.http:ContextDBHttpExtension
export HINDSIGHT_API_MCP_EXTENSION=hindsight_ext_contextdb.mcp:ContextDBMCPExtension
export HINDSIGHT_API_MIGRATION_ISOLATION=false
```

The extension package must be on `PYTHONPATH`. Use
`python -m hindsight_ext_contextdb generate-control-key` to produce a Console
service credential; install only its digest in `CONTEXTDB_CONTROL_KEYS`.
The example identifiers above are placeholders, not working secrets.

When MCP is enabled, the ContextDB MCP extension is mandatory. A legacy
`HINDSIGHT_API_MCP_AUTH_TOKEN` is rejected, because it bypasses dynamic business
Key authentication. In this release the host must retain this branch's
transport/identity/queue-admission hooks; copying this package to an arbitrary
upstream checkout is not supported.

## Identities and permissions

- Instance registration creates one immutable administrator and a permanent
  all-space administrator Key. The first response displays the secret once;
  repeated registration never redisplays it. A Console-only recovery endpoint
  can issue another independent administrator Key after a lost response.
- Administrators create, disable, restore and soft-delete ordinary users.
  User space access is `all` or an explicit `workspace_ids` selection. `all`
  includes future spaces; it is a space ceiling, not another action ACL.
- Users may have several independent Keys. Ordinary Keys are always `selected`:
  each grant has a workspace ID and its own scopes. Omitting `grants` at creation
  snapshots the user's existing spaces; explicitly passing `[]` grants nothing.
  Neither form inherits future spaces.
- Effective permissions are the intersection of the active user's space ceiling
  and the active Key's grants. Scopes are `memory.read`, `memory.write`,
  `knowledge.read`, `reflect`; write and reflect require memory.read.
- Permission changes leave the secret unchanged. Every new REST request and MCP
  tool checks current PG metadata. Revocation is permanent; restoring a user
  restores only its unexpired, unrevoked Keys. A 401 can terminate an MCP client
  session; reconnect after restoring credentials.
- Administrator all Keys cannot be narrowed or expire. Multiple administrator
  Keys permit manual rotation, but the last active all Key cannot be revoked.
  Selected administrator Keys remain business credentials and cannot manage users.
- Ordinary users have no self-service Key management, child Keys or UI login.
  Shared Bank content is shared among its authorized users; Key ownership does
  not introduce personal/private memory ACLs.

## Management APIs

All endpoints have prefix `/ext/contextdb/v1`. Lists return
`items,total,limit,offset`; resource reads/updates emit quoted version `ETag`, and
PATCH requires the matching `If-Match`. Conflicts return 412. Key views expose
metadata only, never secrets or digests. Mutations and successful audit events
commit in the same transaction.

**Console-only:** `X-ContextDB-Control-Key` and trusted
`X-ContextDB-Actor-Subject`, from configured private networks. Disable proxy-header
trust on this ingress and strip forwarded identity headers.

- `POST /instances`, `GET /instances/{instance_id}`
- `POST /instances/{instance_id}/admin-keys` — administrator recovery/rotation
- `POST /workspaces`, `GET /workspaces`, `GET /workspaces/{workspace_id}`
- `DELETE /workspaces/{workspace_id}`, `GET /operations/{operation_id}`

Workspace POST/DELETE require `Idempotency-Key` and return a flat operation with
`operation_id` and `workspace_id`. Poll until succeeded. Names use trimmed NFKC
casefold uniqueness per instance and cannot be changed; IDs are never reused.

**Active administrator all Key only:** `Authorization: Bearer <admin-key>`.
Console credentials cannot call these routes.

- `GET /admin/session`
- `GET/POST /users`, `GET/PATCH/DELETE /users/{user_id}`
- `GET/POST /users/{user_id}/keys`
- `PATCH/DELETE /users/{user_id}/keys/{key_id}`

User inputs use `name,workspace_access,workspace_ids`; Key inputs use
`name,expires_at?,access_mode,grants:[{workspace_id,scopes}]`. Key DELETE means
irreversible revoke. User DELETE is instance-wide soft deletion, not removal
from one workspace.

## Native API, MCP and UI

Native Bank URLs remain unchanged. A single Key can address different authorized
Bank IDs; trusted request-local routing resolves each to its registered schema.
Clients cannot select a schema. Bank lists aggregate authorized schemas before
global search/order/pagination. MCP tools use actual `bank_id`, or a fixed
`/mcp/{bank_id}` endpoint; fixed endpoints cannot override their Bank.

The UI uses an independent `HINDSIGHT_CP_ACCESS_KEY` login password and a fixed
administrator `HINDSIGHT_CP_DATAPLANE_API_KEY`. Browser member Keys are not login
credentials. The ContextDB UI mode requires both values and verifies
`GET /admin/session`. One UI can show every registered Bank without changing its
server Key. Workspace creation/deletion belongs to the cloud Console; native
Bank creation/deletion/clone/import/alias changes and name edits are refused.
Administrator Bank config and content management remain available.

## Deletion and database privileges

Existing durable HTTP/tool and queue admissions, processing-task drain, operation
leases and unknown-executor barriers remain. Deletion closes new operations,
waits for accepted work, deletes Bank data, and retains the schema/tables and
workspace tombstone. Interrupted/unknown admissions do not expire by a timer;
manual recovery requires fencing the old executor. This release does not claim
automatic multi-process migration fencing or production failover validation.

The customer-visible SQL account must be a non-superuser that does not own the
service database/schemas or inherit the service role. Bootstrap and native schema
migration should run as the protected service owner. For an existing service-owned
schema, a DBA can remove broad access with:

```sql
REVOKE ALL ON SCHEMA ctxdb_meta FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ctxdb_meta FROM PUBLIC;
-- For every registered ctxdb_ws_<id> schema:
-- REVOKE ALL ON SCHEMA ctxdb_ws_<id> FROM PUBLIC;
-- REVOKE ALL ON ALL TABLES IN SCHEMA ctxdb_ws_<id> FROM PUBLIC;
```

These statements are deployment examples, not proof a customer's cloud `root`
role is restricted. A genuine PostgreSQL SUPERUSER, a role able to become the
service owner, or OS root **cannot be isolated by same-database ACL/RLS**.
Production Huawei RDS role privileges require separate verification.
