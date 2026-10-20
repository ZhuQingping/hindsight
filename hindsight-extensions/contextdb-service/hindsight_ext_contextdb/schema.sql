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


COMMENT ON SCHEMA ctxdb_meta IS '独享ContextDB管理元数据，与原生工作空间数据分离';
COMMENT ON TABLE ctxdb_meta.deployment_info IS '独享部署绑定、结构版本及全局管理事务锁；必须恰好一行';
COMMENT ON COLUMN ctxdb_meta.deployment_info.singleton IS '固定为true，主键约束最多一行；启动校验恰好一行';
COMMENT ON COLUMN ctxdb_meta.deployment_info.instance_id IS '部署绑定的外部实例标识，最长128字符；不能由业务请求改变';
COMMENT ON COLUMN ctxdb_meta.deployment_info.cloud_tenant_id IS '部署绑定的云租户标识，最长128字符；不是共享库分区键';
COMMENT ON COLUMN ctxdb_meta.deployment_info.metadata_version IS '元数据结构有序版本，当前1；独立于API v1和原生Alembic';
COMMENT ON COLUMN ctxdb_meta.deployment_info.format_id IS '首发元数据格式标识；未知实验格式禁止自动迁移';
COMMENT ON COLUMN ctxdb_meta.deployment_info.installed_at IS '原始初始化时间；升级保留，不重置为升级时间';
COMMENT ON TABLE ctxdb_meta.workspaces IS '工作空间目录和原生schema映射；完整删除业务schema与元数据；管理审计独立保留，不复用ID';
COMMENT ON COLUMN ctxdb_meta.workspaces.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.workspaces.bank_id IS '对外可读的原生Bank标识，存续期间唯一稳定；历史空间保留原UUID标识';
COMMENT ON COLUMN ctxdb_meta.workspaces.schema_name IS '服务端生成且唯一的ctxdb_ws_加可读bank_id；删除前由管理员停止访问并等待已有工作结束';
COMMENT ON COLUMN ctxdb_meta.workspaces.description IS '客户可编辑说明，最多512字符，默认空';
COMMENT ON COLUMN ctxdb_meta.workspaces.state IS '生命周期状态；具体允许值由CHECK约束；删除成功后整行移除';
COMMENT ON COLUMN ctxdb_meta.workspaces.version IS '严格正数并发版本；修改时递增，不是产品版本';
COMMENT ON COLUMN ctxdb_meta.workspaces.created_at IS '记录创建时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.workspaces.updated_at IS '最近变更时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.workspaces.metadata IS '保留工作空间非安全JSON对象扩展；不参与授权，不接受业务客户端任意写入';
COMMENT ON TABLE ctxdb_meta.users IS '内置管理员与业务成员；普通成员只管理归属及统一启停，无独立UI登录';
COMMENT ON COLUMN ctxdb_meta.users.user_id IS '服务端生成的32位成员ID；Key成员停用或删除后不再允许新访问';
COMMENT ON COLUMN ctxdb_meta.users.name_key IS '名称经NFKC、去首尾空白及casefold后的唯一比较键；非删除用户唯一';
COMMENT ON COLUMN ctxdb_meta.users.role IS 'admin为唯一受保护系统管理员；普通创建固定member，不提供角色修改API';
COMMENT ON INDEX ctxdb_meta.users_name_unique IS '正常和停用用户共同保持规范化名称唯一；删除后可复用名称';
COMMENT ON INDEX ctxdb_meta.users_single_admin IS '数据库约束最多一个内置管理员；离线初始化和启动校验确保存在';
COMMENT ON COLUMN ctxdb_meta.users.name IS '客户可编辑名称，去首尾空白后1至64字符';
COMMENT ON COLUMN ctxdb_meta.users.status IS '成员状态active/disabled/deleted；停用可恢复，删除为墓碑';
COMMENT ON COLUMN ctxdb_meta.users.version IS '严格正数并发版本；修改时递增，不是产品版本';
COMMENT ON COLUMN ctxdb_meta.users.created_at IS '记录创建时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.users.updated_at IS '最近变更时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.users.metadata IS '保留成员非安全JSON对象扩展；不参与角色或空间授权';
COMMENT ON TABLE ctxdb_meta.api_keys IS '管理员及成员凭据的统一HMAC摘要与授权；不保存明文，吊销保留历史';
COMMENT ON COLUMN ctxdb_meta.api_keys.key_id IS '服务端生成的32位Key标识；不是完整业务凭据';
COMMENT ON COLUMN ctxdb_meta.api_keys.user_id IS '服务端生成的32位成员ID；Key成员停用或删除后不再允许新访问';
COMMENT ON COLUMN ctxdb_meta.api_keys.name IS '客户可编辑名称，去首尾空白后1至64字符';
COMMENT ON COLUMN ctxdb_meta.api_keys.digest IS '完整凭据的HMAC-SHA256摘要，固定32字节；不可还原明文';
COMMENT ON COLUMN ctxdb_meta.api_keys.access_mode IS 'all表示含未来空间的统一授权；selected使用关联表逐空间授权';
COMMENT ON COLUMN ctxdb_meta.api_keys.permission IS '只读read或读写read_write；selected Key主表为NULL，其权限在关联表';
COMMENT ON COLUMN ctxdb_meta.api_keys.revoked_at IS 'NULL表示未吊销，仍需校验成员和空间状态；非NULL永久吊销';
COMMENT ON COLUMN ctxdb_meta.api_keys.version IS '严格正数并发版本；修改时递增，不是产品版本';
COMMENT ON COLUMN ctxdb_meta.api_keys.created_at IS '记录创建时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.api_keys.updated_at IS '最近变更时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.api_keys.last_used_at IS '最近记录的使用时间；NULL表示无记录，不是完整访问审计';
COMMENT ON COLUMN ctxdb_meta.api_keys.metadata IS '保留非安全JSON对象扩展；display_suffix为服务端校验的真实凭据末6字符，不参与授权';
COMMENT ON INDEX ctxdb_meta.grants_workspace IS '按空间定位授权和关联Key，支持空间删除及外键清理';
COMMENT ON TABLE ctxdb_meta.key_workspace_permissions IS '指定空间Key的逐空间权限；仅selected模式使用';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.key_id IS '服务端生成的32位Key标识；不是完整业务凭据';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.permission IS '只读read或读写read_write；selected Key主表为NULL，其权限在关联表';
COMMENT ON TABLE ctxdb_meta.audit_events IS '成功管理变更记录；记录成功完成的同步管理变更，不包含凭据明文';
COMMENT ON COLUMN ctxdb_meta.audit_events.event_id IS '数据库生成的管理审计顺序标识';
COMMENT ON COLUMN ctxdb_meta.audit_events.request_id IS '请求追踪标识；不包含请求体和秘密';
COMMENT ON COLUMN ctxdb_meta.audit_events.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.audit_events.user_id IS '服务端生成的32位成员ID；Key成员停用或删除后不再允许新访问';
COMMENT ON COLUMN ctxdb_meta.audit_events.key_id IS '服务端生成的32位Key标识；不是完整业务凭据';
COMMENT ON COLUMN ctxdb_meta.audit_events.control_key_id IS '已认证Admin Key的公开ID，支持运维凭据轮换后的归因';
COMMENT ON COLUMN ctxdb_meta.audit_events.action IS '管理动作；成功管理变更动作，例如create_workspace/delete_workspace/create_user/update_key，审计记录管理变更';
COMMENT ON COLUMN ctxdb_meta.audit_events.result IS '管理变更事务提交结果，当前success';
COMMENT ON COLUMN ctxdb_meta.audit_events.created_at IS '记录创建时间，服务端写入';
COMMENT ON INDEX ctxdb_meta.users_page IS '支持目录分页的实际查询；不用于记忆检索';
COMMENT ON INDEX ctxdb_meta.keys_user_page IS '正常Key列表先排除吊销行再按成员和创建时间分页；非历史全量索引';
DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT c.conname,t.relname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='ctxdb_meta' LOOP
  EXECUTE format('COMMENT ON CONSTRAINT %I ON ctxdb_meta.%I IS %L',item.conname,item.relname,'管理元数据不变量：主键、归属、允许值或唯一性；迁移同步校验');
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
COMMENT ON FUNCTION ctxdb_meta.check_key_authorization() IS '事务提交前每Key校验all无逐空间记录、selected最多1000条；支持完整替换';
COMMENT ON FUNCTION ctxdb_meta.schedule_grant_check() IS '每条批量授权SQL按不同Key调度延迟校验；避免逐授权重复扫描';
