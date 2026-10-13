-- Run once through the deployment bootstrap command, before starting API/Worker.
-- These are control-plane metadata, not per-bank memory tables. Keeping DDL out
-- of request/startup paths avoids concurrent API replicas racing global DDL.
CREATE SCHEMA IF NOT EXISTS ctxdb_meta;

CREATE TABLE IF NOT EXISTS ctxdb_meta.schema_versions (
    version integer PRIMARY KEY,
    installed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ctxdb_meta.instances (
    instance_id text PRIMARY KEY,
    cloud_tenant_id text NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (instance_id, cloud_tenant_id)
);

CREATE TABLE IF NOT EXISTS ctxdb_meta.workspaces (
    workspace_id text PRIMARY KEY,
    instance_id text NOT NULL,
    cloud_tenant_id text NOT NULL,
    schema_name text NOT NULL UNIQUE CHECK (schema_name ~ '^ctxdb_ws_[0-9a-f]{32}$'),
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 512),
    state text NOT NULL CHECK (state IN ('creating', 'active', 'frozen', 'deleting', 'deleted', 'failed')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (instance_id, cloud_tenant_id)
        REFERENCES ctxdb_meta.instances (instance_id, cloud_tenant_id),
    UNIQUE (instance_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS workspaces_instance_page
    ON ctxdb_meta.workspaces (instance_id, created_at, workspace_id);

CREATE TABLE IF NOT EXISTS ctxdb_meta.workspace_members (
    member_id text PRIMARY KEY,
    workspace_id text NOT NULL REFERENCES ctxdb_meta.workspaces (workspace_id),
    member_name text NOT NULL CHECK (length(member_name) BETWEEN 1 AND 64),
    iam_subject text CHECK (length(iam_subject) BETWEEN 1 AND 256),
    role text NOT NULL CHECK (role IN ('admin', 'member')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deleted')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (role <> 'admin' OR iam_subject IS NOT NULL),
    UNIQUE (workspace_id, member_id)
);
-- Keep historical bindings unique after soft deletion; recycling identities is
-- an explicit future workflow, not an accidental way to inherit old Key audit.
CREATE UNIQUE INDEX IF NOT EXISTS members_login_unique
    ON ctxdb_meta.workspace_members (workspace_id, iam_subject) WHERE iam_subject IS NOT NULL;
CREATE INDEX IF NOT EXISTS members_workspace_page
    ON ctxdb_meta.workspace_members (workspace_id, created_at, member_id);

CREATE TABLE IF NOT EXISTS ctxdb_meta.api_keys (
    key_id text PRIMARY KEY CHECK (key_id ~ '^[0-9a-f]{32}$'),
    workspace_id text NOT NULL,
    member_id text NOT NULL,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 64),
    digest bytea NOT NULL CHECK (octet_length(digest) = 32),
    scopes text[] NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    FOREIGN KEY (workspace_id, member_id)
        REFERENCES ctxdb_meta.workspace_members (workspace_id, member_id),
    UNIQUE (workspace_id, member_id, key_id),
    CHECK (expires_at > created_at),
    CHECK (cardinality(scopes) BETWEEN 1 AND 4),
    CHECK (scopes <@ ARRAY['memory.read', 'memory.write', 'knowledge.read', 'reflect']::text[]),
    CHECK (NOT scopes && ARRAY['memory.write', 'reflect']::text[] OR 'memory.read' = ANY(scopes))
);
CREATE INDEX IF NOT EXISTS keys_member_page
    ON ctxdb_meta.api_keys (workspace_id, member_id, created_at, key_id);

CREATE TABLE IF NOT EXISTS ctxdb_meta.management_operations (
    operation_id text PRIMARY KEY,
    workspace_id text NOT NULL,
    instance_id text NOT NULL,
    -- Bind a retry to the lifecycle generation that created this task. A later
    -- failed delete must not make an old failed create eligible for resurrection.
    workspace_version bigint NOT NULL DEFAULT 1 CHECK (workspace_version > 0),
    actor_subject text NOT NULL,
    action text NOT NULL CHECK (action IN ('create_workspace', 'delete_workspace')),
    target_id text NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    request_hash text NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    lease_token text,
    lease_until timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (instance_id, actor_subject, action, target_id, idempotency_key),
    FOREIGN KEY (instance_id, workspace_id)
        REFERENCES ctxdb_meta.workspaces (instance_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS operations_pending
    ON ctxdb_meta.management_operations (instance_id, state, lease_until, created_at);

-- Commit before customer/queue work starts. PG session locks disappear on a
-- disconnect; this record does not. Never expire it merely because time passed:
-- an unknown old executor must be fenced before destructive cleanup can resume.
CREATE TABLE IF NOT EXISTS ctxdb_meta.request_admissions (
    admission_id text PRIMARY KEY,
    instance_id text NOT NULL,
    workspace_id text NOT NULL,
    owner_id text NOT NULL,
    origin text NOT NULL CHECK (origin IN ('http', 'queue')),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'interrupted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (instance_id, workspace_id)
        REFERENCES ctxdb_meta.workspaces (instance_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS admissions_workspace
    ON ctxdb_meta.request_admissions (instance_id, workspace_id);

CREATE TABLE IF NOT EXISTS ctxdb_meta.key_requests (
    workspace_id text NOT NULL,
    member_id text NOT NULL,
    actor_subject text NOT NULL,
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    request_hash text NOT NULL,
    key_id text NOT NULL,
    PRIMARY KEY (workspace_id, member_id, actor_subject, idempotency_key),
    FOREIGN KEY (workspace_id, member_id)
        REFERENCES ctxdb_meta.workspace_members (workspace_id, member_id),
    FOREIGN KEY (workspace_id, member_id, key_id)
        REFERENCES ctxdb_meta.api_keys (workspace_id, member_id, key_id)
);

CREATE TABLE IF NOT EXISTS ctxdb_meta.audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL,
    instance_id text NOT NULL,
    cloud_tenant_id text NOT NULL,
    workspace_id text,
    member_id text,
    key_id text,
    control_key_id text NOT NULL,
    actor_subject text NOT NULL,
    action text NOT NULL,
    result text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS audit_workspace_time
    ON ctxdb_meta.audit_events (instance_id, workspace_id, created_at);

INSERT INTO ctxdb_meta.schema_versions (version) VALUES (1) ON CONFLICT DO NOTHING;
