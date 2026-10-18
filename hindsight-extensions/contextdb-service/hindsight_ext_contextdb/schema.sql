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
    name varchar(64) NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 64 AND name !~ '^[[:space:]]*$'),
    name_key text NOT NULL,
    description text NOT NULL DEFAULT '' CHECK (length(description) <= 512),
    state text NOT NULL CHECK (state IN ('creating', 'active', 'frozen', 'deleting', 'deleted', 'failed')),
    version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    metadata jsonb NOT NULL DEFAULT '{}' CHECK(jsonb_typeof(metadata)='object')
);
CREATE UNIQUE INDEX workspaces_name_unique ON ctxdb_meta.workspaces(name_key) WHERE state<>'deleted';
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

CREATE TABLE ctxdb_meta.management_operations (
    operation_id varchar(32) PRIMARY KEY CHECK (operation_id ~ '^[0-9a-f]{32}$'),
    workspace_id varchar(32) NOT NULL,
    -- Bind a retry to the lifecycle generation that created this task. A later
    -- failed delete must not make an old failed create eligible for resurrection.
    workspace_version bigint NOT NULL DEFAULT 1 CHECK (workspace_version > 0),
    action text NOT NULL CHECK (action IN ('create_workspace', 'delete_workspace')),
    target_id varchar(32) NOT NULL CHECK ((action='create_workspace' AND target_id='') OR (action='delete_workspace' AND target_id=workspace_id)),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 128),
    request_hash varchar(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'running', 'succeeded', 'failed')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
    lease_token text,
    lease_until timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (action, target_id, idempotency_key),
    -- Terminal operation snapshots outlive the workspace row for bounded replay.
    CHECK (workspace_id ~ '^[0-9a-f]{32}$')
);
CREATE INDEX operations_pending
    ON ctxdb_meta.management_operations (state, lease_until, created_at);

-- Commit before customer/queue work starts. PG session locks disappear on a
-- disconnect; this record does not. Never expire it merely because time passed:
-- an unknown old executor must be fenced before destructive cleanup can resume.
CREATE TABLE ctxdb_meta.request_admissions (
    admission_id varchar(32) PRIMARY KEY CHECK (admission_id ~ '^[0-9a-f]{32}$'),
    workspace_id varchar(32) NOT NULL,
    owner_id text NOT NULL,
    origin text NOT NULL CHECK (origin IN ('http', 'queue', 'lifecycle')),
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'interrupted')),
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (workspace_id) REFERENCES ctxdb_meta.workspaces (workspace_id)
);
CREATE INDEX admissions_workspace
    ON ctxdb_meta.request_admissions (workspace_id);

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
COMMENT ON TABLE ctxdb_meta.workspaces IS '工作空间目录和原生schema映射；完整删除业务schema与元数据；历史操作独立保留，不复用ID';
COMMENT ON COLUMN ctxdb_meta.workspaces.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.workspaces.bank_id IS '对外可读的原生Bank标识，存续期间唯一稳定；历史空间保留原UUID标识';
COMMENT ON COLUMN ctxdb_meta.workspaces.schema_name IS '服务端生成且唯一的ctxdb_ws_加可读bank_id；名称复用前须完整清理旧执行者';
COMMENT ON COLUMN ctxdb_meta.workspaces.name IS '新空间为1至54位小写ASCII标识，创建时固定；与bank_id一致';
COMMENT ON COLUMN ctxdb_meta.workspaces.name_key IS '名称经NFKC和casefold的唯一比较键；可能比展示名更长';
COMMENT ON COLUMN ctxdb_meta.workspaces.description IS '客户可编辑说明，最多512字符，默认空';
COMMENT ON COLUMN ctxdb_meta.workspaces.state IS '生命周期状态；具体允许值由CHECK约束；deleted墓碑不得继续访问';
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
COMMENT ON TABLE ctxdb_meta.key_workspace_permissions IS '指定空间Key的逐空间权限；仅selected模式使用';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.key_id IS '服务端生成的32位Key标识；不是完整业务凭据';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.key_workspace_permissions.permission IS '只读read或读写read_write；selected Key主表为NULL，其权限在关联表';
COMMENT ON TABLE ctxdb_meta.management_operations IS 'API生命周期循环领取的工作空间异步操作及有界保留的终态幂等结果；不是原生任务队列';
COMMENT ON COLUMN ctxdb_meta.management_operations.operation_id IS '服务端生成的32位管理任务ID；供状态查询及恢复';
COMMENT ON COLUMN ctxdb_meta.management_operations.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.management_operations.workspace_version IS '创建任务所属空间生命周期代次；阻止旧失败任务复活新代空间';
COMMENT ON COLUMN ctxdb_meta.management_operations.action IS '管理动作；任务仅create_workspace/delete_workspace，审计记录管理变更';
COMMENT ON COLUMN ctxdb_meta.management_operations.target_id IS '创建为空、删除为空间ID；参与幂等作用域，不得省略';
COMMENT ON COLUMN ctxdb_meta.management_operations.idempotency_key IS '客户提交的1至128字符幂等标识；相同作用域不同请求拒绝';
COMMENT ON COLUMN ctxdb_meta.management_operations.request_hash IS '请求内容SHA256的64位十六进制摘要；用于幂等冲突检查';
COMMENT ON COLUMN ctxdb_meta.management_operations.state IS '管理任务pending/running/succeeded/failed；终态保留供查询与幂等重试，不等于空间状态';
COMMENT ON COLUMN ctxdb_meta.management_operations.attempts IS '非负领取次数；控制失败重试，不是原生任务次数';
COMMENT ON COLUMN ctxdb_meta.management_operations.lease_token IS '当前领取者的fencing令牌；NULL表示没有当前所有者';
COMMENT ON COLUMN ctxdb_meta.management_operations.lease_until IS '管理操作租约截止；允许接续不代表未知业务执行者已结束';
COMMENT ON COLUMN ctxdb_meta.management_operations.error_code IS '已清理的错误标识或等待原因；不得写入凭据或SQL诊断';
COMMENT ON COLUMN ctxdb_meta.management_operations.created_at IS '记录创建时间，服务端写入';
COMMENT ON COLUMN ctxdb_meta.management_operations.updated_at IS '最近变更时间，服务端写入';
COMMENT ON TABLE ctxdb_meta.request_admissions IS '在途请求与任务提交的持久删除屏障；正常完成删除，异常不得按TTL清除';
COMMENT ON COLUMN ctxdb_meta.request_admissions.admission_id IS '服务端生成的32位在途登记ID；仅所属执行者正常退出可删除';
COMMENT ON COLUMN ctxdb_meta.request_admissions.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.request_admissions.owner_id IS '执行进程所有者标识；恢复未知准入前必须确认旧执行者停止';
COMMENT ON COLUMN ctxdb_meta.request_admissions.origin IS 'http、queue或lifecycle执行入口；不是调度队列';
COMMENT ON COLUMN ctxdb_meta.request_admissions.state IS '在途登记active/interrupted；正常退出删除，异常保留，不能按TTL自动清空';
COMMENT ON COLUMN ctxdb_meta.request_admissions.created_at IS '记录创建时间，服务端写入';
COMMENT ON TABLE ctxdb_meta.audit_events IS '成功管理变更记录；提交成功不表示异步操作完成，不包含凭据明文';
COMMENT ON COLUMN ctxdb_meta.audit_events.event_id IS '数据库生成的管理审计顺序标识';
COMMENT ON COLUMN ctxdb_meta.audit_events.request_id IS '请求追踪标识；不包含请求体和秘密';
COMMENT ON COLUMN ctxdb_meta.audit_events.workspace_id IS '服务端生成的32位小写十六进制空间ID，用于不可复用对象身份，独立于bank_id';
COMMENT ON COLUMN ctxdb_meta.audit_events.user_id IS '服务端生成的32位成员ID；Key成员停用或删除后不再允许新访问';
COMMENT ON COLUMN ctxdb_meta.audit_events.key_id IS '服务端生成的32位Key标识；不是完整业务凭据';
COMMENT ON COLUMN ctxdb_meta.audit_events.control_key_id IS '已认证Admin Key的公开ID，支持运维凭据轮换后的归因';
COMMENT ON COLUMN ctxdb_meta.audit_events.action IS '管理动作；任务仅create_workspace/delete_workspace，审计记录管理变更';
COMMENT ON COLUMN ctxdb_meta.audit_events.result IS '管理变更事务提交结果，当前success';
COMMENT ON COLUMN ctxdb_meta.audit_events.created_at IS '记录创建时间，服务端写入';
COMMENT ON INDEX ctxdb_meta.workspaces_name_unique IS '非删除空间的规范化名称唯一；删除墓碑允许重建同名空间';
COMMENT ON INDEX ctxdb_meta.users_page IS '支持目录分页、空间排空或管理任务领取的实际查询；不用于记忆检索';
COMMENT ON INDEX ctxdb_meta.keys_user_page IS '正常Key列表先排除吊销行再按成员和创建时间分页；非历史全量索引';
DO $$ DECLARE item record; BEGIN
 FOR item IN SELECT c.conname,t.relname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='ctxdb_meta' LOOP
  EXECUTE format('COMMENT ON CONSTRAINT %I ON ctxdb_meta.%I IS %L',item.conname,item.relname,'管理元数据不变量：主键、归属、允许值或幂等唯一性；迁移同步校验');
 END LOOP;
END $$;

-- A deferred check permits complete authorization replacement in one transaction,
-- while direct SQL cannot leave all-mode grants or oversized selected grants behind.
CREATE FUNCTION ctxdb_meta.check_key_authorization() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE candidate text; mode text; grant_count bigint; candidates text[];
BEGIN
 IF TG_OP='DELETE' THEN candidates=ARRAY[OLD.key_id];
 ELSIF TG_OP='UPDATE' THEN candidates=ARRAY[OLD.key_id,NEW.key_id];
 ELSE candidates=ARRAY[NEW.key_id]; END IF;
 FOREACH candidate IN ARRAY candidates LOOP
  -- Parent row locking also serializes direct-SQL grant edits at READ COMMITTED.
  SELECT access_mode INTO mode FROM ctxdb_meta.api_keys WHERE key_id=candidate FOR UPDATE;
  IF mode IS NULL THEN CONTINUE; END IF;
  SELECT count(*) INTO grant_count FROM ctxdb_meta.key_workspace_permissions WHERE key_id=candidate;
  IF (mode='all' AND grant_count<>0) OR (mode='selected' AND grant_count>1000) THEN
   RAISE EXCEPTION 'Invalid Key workspace authorization' USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER keys_authorization_integrity AFTER INSERT OR UPDATE ON ctxdb_meta.api_keys DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_key_authorization();
CREATE CONSTRAINT TRIGGER grants_authorization_integrity AFTER INSERT OR UPDATE OR DELETE ON ctxdb_meta.key_workspace_permissions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_key_authorization();
COMMENT ON FUNCTION ctxdb_meta.check_key_authorization() IS '事务提交前校验all无逐空间记录、selected最多1000条授权；空间清理可留下无权限的空范围；支持完整替换';
COMMENT ON TRIGGER keys_authorization_integrity ON ctxdb_meta.api_keys IS '授权完整性延迟到事务提交检查';
COMMENT ON TRIGGER grants_authorization_integrity ON ctxdb_meta.key_workspace_permissions IS '授权完整性延迟到事务提交检查';

-- Nonterminal work must reference a live workspace; terminal snapshots may outlive it.
CREATE FUNCTION ctxdb_meta.check_operation_workspace() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='management_operations' THEN
  IF NEW.state IN ('pending','running') AND NOT EXISTS(SELECT 1 FROM ctxdb_meta.workspaces WHERE workspace_id=NEW.workspace_id FOR KEY SHARE) THEN
   RAISE EXCEPTION 'Active operation requires a workspace' USING ERRCODE='23503';
  END IF;
 ELSE
  IF EXISTS(SELECT 1 FROM ctxdb_meta.management_operations WHERE workspace_id=OLD.workspace_id AND state IN ('pending','running')) THEN
   RAISE EXCEPTION 'Workspace still has active management work' USING ERRCODE='23503';
  END IF;
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER operation_workspace_integrity AFTER INSERT OR UPDATE ON ctxdb_meta.management_operations DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_operation_workspace();
CREATE CONSTRAINT TRIGGER workspace_operation_integrity AFTER DELETE ON ctxdb_meta.workspaces DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ctxdb_meta.check_operation_workspace();
COMMENT ON FUNCTION ctxdb_meta.check_operation_workspace() IS '未完成操作须引用真实工作空间；终态快照允许独立保留，供删除后查询和幂等重试';
COMMENT ON TRIGGER operation_workspace_integrity ON ctxdb_meta.management_operations IS '提交时校验未完成操作仍有目标空间';
COMMENT ON TRIGGER workspace_operation_integrity ON ctxdb_meta.workspaces IS '禁止删除仍有未完成管理操作的空间';
