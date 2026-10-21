-- Run once through the deployment bootstrap command, before starting API/Worker.
-- These are control-plane metadata, not per-bank memory tables. Keeping DDL out
-- of request/startup paths avoids concurrent API replicas racing global DDL.
CREATE SCHEMA ctxdb_meta;

CREATE TABLE ctxdb_meta.deployment_info (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    instance_id varchar(128) NOT NULL CHECK (length(instance_id)>0),
    cloud_tenant_id varchar(128) NOT NULL CHECK (length(cloud_tenant_id)>0),
    metadata_version integer NOT NULL CHECK (metadata_version=1),
    format_id text NOT NULL CHECK (format_id='contextdb-first-release'),
    installed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ctxdb_meta.workspaces (
    workspace_id varchar(32) PRIMARY KEY CHECK (workspace_id ~ '^[0-9a-f]{32}$'),
    bank_id varchar(54) NOT NULL UNIQUE CHECK (bank_id ~ '^[a-z0-9][a-z0-9_]{0,53}$'),
    schema_name text NOT NULL UNIQUE CHECK (schema_name = 'ctxdb_ws_' || bank_id),
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 512),
    state text NOT NULL CHECK (state IN ('creating', 'active', 'deleting', 'failed')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata)='object')
);
CREATE INDEX workspaces_page
    ON ctxdb_meta.workspaces (created_at, workspace_id);

CREATE TABLE ctxdb_meta.users (
    user_id varchar(32) PRIMARY KEY CHECK (user_id ~ '^[0-9a-f]{32}$'),
    name varchar(64) NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 64 AND name !~ '^[[:space:]]*$'),
    name_key text NOT NULL,
    role text NOT NULL DEFAULT 'member' CHECK (role IN ('admin','member')),
    status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled','deleted')),
    version bigint NOT NULL DEFAULT 1 CHECK (version>0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata)='object')
);
CREATE UNIQUE INDEX users_name_unique ON ctxdb_meta.users(name_key) WHERE status<>'deleted';
CREATE UNIQUE INDEX users_single_admin ON ctxdb_meta.users(role) WHERE role='admin';
CREATE INDEX users_page ON ctxdb_meta.users(created_at,user_id);

CREATE TABLE ctxdb_meta.api_keys (
    key_id varchar(32) PRIMARY KEY CHECK(key_id ~ '^[0-9a-f]{32}$'),
    user_id varchar(32) NOT NULL,
    name varchar(64) NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 64 AND name !~ '^[[:space:]]*$'),
    digest bytea NOT NULL CHECK(octet_length(digest)=32),
    access_mode text NOT NULL CHECK(access_mode IN ('all','selected')),
    permission text CHECK(permission IN ('read','read_write')),
    revoked_at timestamptz,
    version bigint NOT NULL DEFAULT 1 CHECK (version>0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata)='object'),
    FOREIGN KEY(user_id) REFERENCES ctxdb_meta.users(user_id),
    CHECK((access_mode='all' AND permission IS NOT NULL) OR (access_mode='selected' AND permission IS NULL))
);
CREATE INDEX keys_user_page ON ctxdb_meta.api_keys(user_id,created_at,key_id) WHERE revoked_at IS NULL;

CREATE TABLE ctxdb_meta.key_workspace_permissions (
    key_id varchar(32) NOT NULL REFERENCES ctxdb_meta.api_keys(key_id),
    workspace_id varchar(32) NOT NULL REFERENCES ctxdb_meta.workspaces(workspace_id),
    permission text NOT NULL CHECK (permission IN ('read','read_write')),
    PRIMARY KEY (key_id,workspace_id)
);

CREATE INDEX grants_workspace ON ctxdb_meta.key_workspace_permissions(workspace_id,key_id);

CREATE TABLE ctxdb_meta.audit_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id text NOT NULL,
    workspace_id varchar(32) CHECK (workspace_id IS NULL OR workspace_id ~ '^[0-9a-f]{32}$'),
    user_id varchar(32) CHECK (user_id IS NULL OR user_id ~ '^[0-9a-f]{32}$'),
    key_id varchar(32) CHECK (key_id IS NULL OR key_id ~ '^[0-9a-f]{32}$'),
    control_key_id text NOT NULL,
    action text NOT NULL,
    result text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_workspace_time
    ON ctxdb_meta.audit_events (workspace_id, created_at);


COMMENT ON SCHEMA ctxdb_meta IS 'Dedicated-instance management metadata, separate from native workspace data.';
COMMENT ON TABLE ctxdb_meta.deployment_info IS 'Deployment identity, metadata format, and management transaction lock; exactly one row is required.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.singleton IS 'Always true; the primary key permits at most one row and startup requires exactly one.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.instance_id IS 'External instance identifier bound at deployment, up to 128 characters; not request-editable.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.cloud_tenant_id IS 'External cloud tenant identifier, up to 128 characters; not a shared-database partition key.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.metadata_version IS 'Ordered metadata schema version, currently 1; independent of API v1 and native Alembic revisions.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.format_id IS 'First-release metadata format; unknown experimental formats require explicit handling.';
COMMENT ON COLUMN ctxdb_meta.deployment_info.installed_at IS 'Original initialization time; preserved across future upgrades.';
COMMENT ON TABLE ctxdb_meta.workspaces IS 'Workspace directory and native schema mapping; successful deletion removes both, while audit history retains the original identity.';
COMMENT ON COLUMN ctxdb_meta.workspaces.workspace_id IS 'Server-generated 32-character lowercase hex identity; never reused and independent of bank_id.';
COMMENT ON COLUMN ctxdb_meta.workspaces.bank_id IS 'Readable native Bank identifier, unique and stable during this workspace lifetime.';
COMMENT ON COLUMN ctxdb_meta.workspaces.schema_name IS 'Unique server-generated ctxdb_ws_ plus bank_id; stop access and wait for existing work before deletion.';
COMMENT ON COLUMN ctxdb_meta.workspaces.description IS 'Editable description, at most 512 characters; defaults to an empty string.';
COMMENT ON COLUMN ctxdb_meta.workspaces.state IS 'Lifecycle state: creating, active, deleting, or failed; successful deletion removes the row.';
COMMENT ON COLUMN ctxdb_meta.workspaces.version IS 'Positive optimistic-concurrency version, incremented on change; not a product version.';
COMMENT ON COLUMN ctxdb_meta.workspaces.created_at IS 'Server-assigned record creation time.';
COMMENT ON COLUMN ctxdb_meta.workspaces.updated_at IS 'Most recent record update time.';
COMMENT ON COLUMN ctxdb_meta.workspaces.metadata IS 'Reserved non-security JSON object; not used for authorization or freely writable by business callers.';
COMMENT ON TABLE ctxdb_meta.users IS 'Built-in administrator and business members; members own API Keys and have no independent UI login.';
COMMENT ON COLUMN ctxdb_meta.users.user_id IS 'Server-generated 32-character member identity; disabled or deleted members cannot authenticate.';
COMMENT ON COLUMN ctxdb_meta.users.name_key IS 'NFKC-normalized, trimmed, case-folded name; unique among non-deleted users.';
COMMENT ON COLUMN ctxdb_meta.users.role IS 'admin is the single protected administrator; ordinary creation always uses member and role changes are not exposed.';
COMMENT ON INDEX ctxdb_meta.users_name_unique IS 'Normalized user names remain unique while active or disabled; names can be reused after deletion.';
COMMENT ON INDEX ctxdb_meta.users_single_admin IS 'At most one built-in administrator; offline initialization and startup checks require one.';
COMMENT ON COLUMN ctxdb_meta.users.name IS 'Editable user name, 1 to 64 characters after trimming.';
COMMENT ON COLUMN ctxdb_meta.users.status IS 'active, disabled, or deleted; disabling is reversible and deletion retains a tombstone.';
COMMENT ON COLUMN ctxdb_meta.users.version IS 'Positive optimistic-concurrency version, incremented on change; not a product version.';
COMMENT ON COLUMN ctxdb_meta.users.created_at IS 'Server-assigned record creation time.';
COMMENT ON COLUMN ctxdb_meta.users.updated_at IS 'Most recent record update time.';
COMMENT ON COLUMN ctxdb_meta.users.metadata IS 'Reserved non-security JSON object; not used for role or workspace authorization.';
COMMENT ON TABLE ctxdb_meta.api_keys IS 'Unified administrator/member credential digests and grants; no plaintext credentials; revoked Keys retain history.';
COMMENT ON COLUMN ctxdb_meta.api_keys.key_id IS 'Server-generated 32-character public Key identifier; not the complete credential.';
COMMENT ON COLUMN ctxdb_meta.api_keys.user_id IS 'Owning member identity; authentication also checks member status.';
COMMENT ON COLUMN ctxdb_meta.api_keys.name IS 'Editable Key name, 1 to 64 characters after trimming.';
COMMENT ON COLUMN ctxdb_meta.api_keys.digest IS 'HMAC-SHA256 of the complete credential, exactly 32 bytes; plaintext cannot be recovered.';
COMMENT ON COLUMN ctxdb_meta.api_keys.access_mode IS 'all grants one permission to current and future workspaces; selected uses per-workspace grant rows.';
COMMENT ON COLUMN ctxdb_meta.api_keys.permission IS 'read or read_write for all mode; NULL for selected mode, whose permissions are in the grant table.';
COMMENT ON COLUMN ctxdb_meta.api_keys.revoked_at IS 'NULL means not revoked, subject to member/workspace checks; non-NULL means permanently revoked.';
COMMENT ON COLUMN ctxdb_meta.api_keys.version IS 'Positive optimistic-concurrency version, incremented on change; not a product version.';
COMMENT ON COLUMN ctxdb_meta.api_keys.created_at IS 'Server-assigned record creation time.';
COMMENT ON COLUMN ctxdb_meta.api_keys.updated_at IS 'Most recent record update time.';
COMMENT ON COLUMN ctxdb_meta.api_keys.last_used_at IS 'Most recently recorded use; NULL means no use recorded, not a complete access audit.';
COMMENT ON COLUMN ctxdb_meta.api_keys.metadata IS 'Reserved non-security JSON object; display_suffix is the validated last 6 credential characters and is not used for authorization.';
COMMENT ON INDEX ctxdb_meta.grants_workspace IS 'Find grants and related Keys by workspace for deletion and foreign-key cleanup.';
COMMENT ON TABLE ctxdb_meta.key_workspace_permissions IS 'Per-workspace Key permissions, used only by selected mode.';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.key_id IS 'Public identifier of the Key receiving this grant.';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.workspace_id IS 'Immutable workspace identity; a same-name replacement does not inherit this grant.';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.permission IS 'Permission in this workspace: read or read_write.';
COMMENT ON TABLE ctxdb_meta.audit_events IS 'Successful management changes; committed atomically with metadata changes and contains no plaintext credentials.';
COMMENT ON COLUMN ctxdb_meta.audit_events.event_id IS 'Database-generated sequential management audit identifier.';
COMMENT ON COLUMN ctxdb_meta.audit_events.request_id IS 'Request correlation identifier; excludes request bodies and secrets.';
COMMENT ON COLUMN ctxdb_meta.audit_events.workspace_id IS 'Target workspace identity, retained independently after workspace deletion; NULL when not applicable.';
COMMENT ON COLUMN ctxdb_meta.audit_events.user_id IS 'Target member identity; NULL when not applicable.';
COMMENT ON COLUMN ctxdb_meta.audit_events.key_id IS 'Target Key identity for issuance, update, or revocation; NULL for unrelated management changes.';
COMMENT ON COLUMN ctxdb_meta.audit_events.control_key_id IS 'Public identifier of the acting authenticated administrator Key, including after credential rotation.';
COMMENT ON COLUMN ctxdb_meta.audit_events.action IS 'Management action, such as create_workspace, delete_workspace, create_user, or update_key.';
COMMENT ON COLUMN ctxdb_meta.audit_events.result IS 'Committed management result; currently success.';
COMMENT ON COLUMN ctxdb_meta.audit_events.created_at IS 'Server-assigned record creation time.';
COMMENT ON INDEX ctxdb_meta.users_page IS 'Supports user-directory pagination; unrelated to memory retrieval.';
COMMENT ON INDEX ctxdb_meta.keys_user_page IS 'Non-revoked Key listing by member and creation order; not an index over full history.';
DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT c.conname,t.relname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='ctxdb_meta' LOOP
  EXECUTE format('COMMENT ON CONSTRAINT %I ON ctxdb_meta.%I IS %L',item.conname,item.relname,'Metadata invariant: primary key, ownership, allowed values, or uniqueness; checked during initialization.');
 END LOOP;
END $$;

-- Check once per affected Key/statement, rather than once per grant row.
-- Checks stay deferred so an authorization can be replaced atomically. Usage-only
-- updates do not schedule authorization checks. PK/FK/CHECK still cover each row.
CREATE FUNCTION ctxdb_meta.check_key_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE mode text; grant_count bigint;
BEGIN
 SELECT access_mode INTO mode FROM ctxdb_meta.api_keys WHERE key_id=NEW.key_id FOR UPDATE;
 IF mode IS NULL THEN RETURN NULL; END IF;
 SELECT count(*) INTO grant_count FROM ctxdb_meta.key_workspace_permissions WHERE key_id=NEW.key_id;
 IF (mode='all' AND grant_count<>0) OR (mode='selected' AND grant_count>1000) THEN
  RAISE EXCEPTION 'Invalid Key workspace authorization' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER keys_authorization_insert AFTER INSERT ON ctxdb_meta.api_keys DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_key_authorization();
CREATE CONSTRAINT TRIGGER keys_authorization_update AFTER UPDATE OF access_mode ON ctxdb_meta.api_keys DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_key_authorization();
CREATE FUNCTION ctxdb_meta.schedule_grant_check() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 -- Transition tables contain every changed grant, including bulk INSERT/DELETE.
 -- Touch the parent once per distinct Key to schedule its deferred final check.
 IF TG_OP='INSERT' THEN
  UPDATE ctxdb_meta.api_keys SET access_mode=access_mode WHERE key_id IN (SELECT key_id FROM new_grants);
 ELSIF TG_OP='DELETE' THEN
  UPDATE ctxdb_meta.api_keys SET access_mode=access_mode WHERE key_id IN (SELECT key_id FROM old_grants);
 ELSE
  UPDATE ctxdb_meta.api_keys SET access_mode=access_mode WHERE key_id IN (SELECT key_id FROM old_grants UNION SELECT key_id FROM new_grants);
 END IF;
 RETURN NULL;
END $$;
CREATE TRIGGER grants_authorization_insert AFTER INSERT ON ctxdb_meta.key_workspace_permissions REFERENCING NEW TABLE AS new_grants FOR EACH STATEMENT EXECUTE FUNCTION ctxdb_meta.schedule_grant_check();
CREATE TRIGGER grants_authorization_delete AFTER DELETE ON ctxdb_meta.key_workspace_permissions REFERENCING OLD TABLE AS old_grants FOR EACH STATEMENT EXECUTE FUNCTION ctxdb_meta.schedule_grant_check();
CREATE TRIGGER grants_authorization_update AFTER UPDATE ON ctxdb_meta.key_workspace_permissions REFERENCING OLD TABLE AS old_grants NEW TABLE AS new_grants FOR EACH STATEMENT EXECUTE FUNCTION ctxdb_meta.schedule_grant_check();
COMMENT ON FUNCTION ctxdb_meta.check_key_authorization() IS 'Deferred per-Key validation: all has no grant rows and selected has at most 1000; supports full replacement.';
COMMENT ON FUNCTION ctxdb_meta.schedule_grant_check() IS 'Schedules deferred checks once per distinct Key in a bulk grant statement, avoiding per-grant scans.';
