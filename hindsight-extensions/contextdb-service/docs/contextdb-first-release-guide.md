# ContextDB 首发部署与验收

> **历史快照，不适用于当前首发版本。** 下文保留当时的配置、接口、表结构和测试环境用于对照，不应照此部署或验证当前代码。当前以[首发设计](contextdb-release-design.md)、[部署合同](contextdb-deployment-contract.md)和[API验证手册](contextdb-optimized-curl-guide.md)为准；开发期旧库不自动升级。


2026-10-16。面向运维和开发者。本手册使用首发简化代码、新 UTF8 数据库；旧 V2 体验库和运行服务不变。命令是操作步骤，执行状态见 [验收报告](../REVIEW-first-release-20261016.md)。

## 1 准备一个新部署

需要 Python 3.11+、Node 22.12+ 或 24 LTS、uv、npm、jq，以及已经安装扩展文件的 PG 18。在本次简化分支的仓库根目录执行，使用 Bash：

```bash
bash
set -e
umask 077
export CODE=$(git rev-parse --show-toplevel)
export DEPLOY="$HOME/contextdb-runs/first-release-$(date +%Y%m%d-%H%M%S)-$$"
export PG_BIN=/Users/zhuqingping/Work/Database/PG/pg_18_4/bin
mkdir -p "$DEPLOY"
command -v uv node npm jq
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 22 && minor >= 12) || major === 24)) { console.error("请切换到 Node 22.12+ 或 24 LTS"); process.exit(1); }'
export NODE_BIN=$(command -v node)
"$PG_BIN/postgres" --version
export UV_PROJECT_ENVIRONMENT="$DEPLOY/venv"
cd "$CODE"
uv sync --frozen
export PY="$DEPLOY/venv/bin/python"
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service"
"$PY" -c 'import hindsight_api, hindsight_ext_contextdb'
```

换机器时修改 PG_BIN。请确认 PG 5540、API 8888、UI 9999 没有被其他服务占用；若已有服务，更换下文所有对应端口，不要停掉旧实例。

## 2 PG 与全文后端

扩展文件编译安装见 [PG 插件安装](postgresql-extensions.md)。该历史文档的 PGroonga 默认推荐不作为本次生产选型结论。

| 场景 | 配置 |
| --- | --- |
| 英文基本验证 | `native`，PG 内置全文检索 |
| 中英文验证 | `pgroonga`，Hindsight 自动配置 TokenBigram |
| 中文 BM25 对比 | `pg_search`，设置 PG_SEARCH_TOKENIZER 为 jieba；需要支持该分词器的插件版本 |

基础扩展是 vector、pg_trgm、btree_gin。pg_stat_statements 用于观测；不承担全文检索。只安装其中一个选定的第三方全文后端，尤其不要把两个使用 bm25 索引方法的插件盲目共装。

**PGroonga 生产使用前须验证崩溃、备份恢复、PITR 和主备切换；CREATE EXTENSION 不代表这些已经完成。** 本手册使用已有 PGroonga 文件验证中英文功能；如仅验证英文，把后面的 pgroonga CREATE 删除，并设置 TEXT_SEARCH=native。

下面建立独立本地 PG 集群，端口 5540，不修改已有 5432 服务。initdb 的本地 trust 认证仅用于这个隔离验证环境；生产应使用密码/TLS、私网准入与非超级用户服务角色。

```bash
export PGDATA="$DEPLOY/pg-data"
"$PG_BIN/initdb" -D "$PGDATA" --encoding=UTF8 --locale=C --auth=trust
"$PG_BIN/pg_ctl" -D "$PGDATA" -l "$DEPLOY/pg.log" \
  -o '-h 127.0.0.1 -p 5540' start
"$PG_BIN/psql" -X -h 127.0.0.1 -p 5540 -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE ROLE ctxdb_service LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;'
"$PG_BIN/createdb" -h 127.0.0.1 -p 5540 -O ctxdb_service \
  -T template0 -E UTF8 --locale=C contextdb_first_release
export DB_URL='postgresql://ctxdb_service@127.0.0.1:5540/contextdb_first_release'
"$PG_BIN/psql" -X -h 127.0.0.1 -p 5540 -d contextdb_first_release \
  -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION vector WITH SCHEMA public;' \
  -c 'CREATE EXTENSION pg_trgm WITH SCHEMA public;' \
  -c 'CREATE EXTENSION btree_gin WITH SCHEMA public;' \
  -c 'CREATE EXTENSION pgroonga;' \
  -c 'SHOW server_encoding;'
export TEXT_SEARCH=pgroonga
```

服务角色拥有这个专用数据库，由它创建服务 schema；不要将该账号或 PG 超级用户账号交给业务客户。客户如有 SQL 访问需求，应另建非超级用户、非 schema 所有者账号。

已有 PG/RDS 可省略 initdb/pg_ctl，提前建立新的 UTF8 库、安装所需扩展，设置 DB_URL。生产统计插件、PGroonga WAL 与复制配置由数据库运维单独完成，不在应用启动时自动更改。

## 3 离线生成一个 Admin Key 和配置

仅首次生成；已有文件不覆盖。部署凭据与 UI 登录密码存放在私有目录，不提交仓库。

```bash
(set -o noclobber; "$PY" -m hindsight_ext_contextdb generate-admin-key \
  > "$DEPLOY/admin-key.json")
read -r -s -p 'MaaS API Key: ' MAAS_API_KEY
printf '\n'
export MAAS_API_KEY
```

保存下面 Python 内容到 `$DEPLOY/configure.py` 后执行；也可整段粘贴。它只生成本地配置，不调用模型：

```bash
cat > "$DEPLOY/configure.py" <<'PY'
import json
import os
import secrets
import shlex
from pathlib import Path

root = Path(os.environ['DEPLOY'])
admin = json.loads((root / 'admin-key.json').read_text())
key = os.environ['MAAS_API_KEY']
api = {
    'CONTEXTDB_INSTANCE_ID': 'ctxdb-first-release',
    'CONTEXTDB_CLOUD_TENANT_ID': 'local-cloud-tenant',
    'CONTEXTDB_KEY_PEPPER': secrets.token_urlsafe(48),
    'CONTEXTDB_BOOTSTRAP_DATABASE_URL': os.environ['DB_URL'],
    'HINDSIGHT_API_DATABASE_URL': os.environ['DB_URL'],
    'HINDSIGHT_API_TENANT_EXTENSION': 'hindsight_ext_contextdb.tenant:ContextDBTenantExtension',
    'HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION': 'hindsight_ext_contextdb.validator:ContextDBOperationValidator',
    'HINDSIGHT_API_HTTP_EXTENSION': 'hindsight_ext_contextdb.http:ContextDBHttpExtension',
    'HINDSIGHT_API_MCP_EXTENSION': 'hindsight_ext_contextdb.mcp:ContextDBMCPExtension',
    'HINDSIGHT_API_MCP_ENABLED': 'true',
    'HINDSIGHT_API_MIGRATION_ISOLATION': 'false',
    'HINDSIGHT_API_WORKER_ENABLED': 'true',
    'HINDSIGHT_API_DB_POOL_MAX_SIZE': '10',
    'HINDSIGHT_API_TEXT_SEARCH_EXTENSION': os.environ['TEXT_SEARCH'],
    'HINDSIGHT_API_LLM_PROVIDER': 'openai',
    'HINDSIGHT_API_LLM_BASE_URL': 'https://api.modelarts-maas.com/v2',
    'HINDSIGHT_API_LLM_MODEL': 'deepseek-v4.1-flash',
    'HINDSIGHT_API_LLM_API_KEY': key,
    'HINDSIGHT_API_EMBEDDINGS_PROVIDER': 'openai',
    'HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL': 'https://api.modelarts-maas.com/v1',
    'HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL': 'bge-m3',
    'HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY': key,
    'HINDSIGHT_API_RERANKER_PROVIDER': 'siliconflow',
    'HINDSIGHT_API_RERANKER_SILICONFLOW_BASE_URL': 'https://api.modelarts-maas.com/v1',
    'HINDSIGHT_API_RERANKER_SILICONFLOW_MODEL': 'bge-reranker-v2-m3',
    'HINDSIGHT_API_RERANKER_SILICONFLOW_API_KEY': key,
}
if api['HINDSIGHT_API_TEXT_SEARCH_EXTENSION'] == 'pg_search':
    api['HINDSIGHT_API_TEXT_SEARCH_EXTENSION_PG_SEARCH_TOKENIZER'] = 'jieba'
ui = {
    'HINDSIGHT_CP_CONTEXTDB_ENABLED': 'true',
    'HINDSIGHT_CP_ACCESS_KEY': secrets.token_urlsafe(24),
    'HINDSIGHT_CP_DATAPLANE_API_KEY': admin['secret'],
    'HINDSIGHT_CP_DATAPLANE_API_URL': 'http://127.0.0.1:8888',
}
for name in ['api.env', 'ui.env', 'operator.env', 'admin.curl']:
    if (root / name).exists():
        raise SystemExit(f'{name} 已存在，重启时直接复用，不重新生成')
operator = {name: os.environ[name] for name in ['CODE', 'DEPLOY', 'PG_BIN', 'PY', 'PYTHONPATH', 'DB_URL', 'NODE_BIN']}
for name, values in [('api.env', api), ('ui.env', ui), ('operator.env', operator)]:
    with (root / name).open('x') as f:
        f.write(''.join(f'export {k}={shlex.quote(v)}\n' for k, v in values.items()))
with (root / 'admin.curl').open('x') as f:
    f.write(f'header = "Authorization: Bearer {admin["secret"]}"\n')
print('配置已保存，凭据未输出。')
PY
"$PY" "$DEPLOY/configure.py"
unset MAAS_API_KEY
source "$DEPLOY/api.env"
unset HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS HINDSIGHT_API_MCP_AUTH_TOKEN
"$PY" -m hindsight_ext_contextdb migrate
"$PG_BIN/psql" -X "$DB_URL" -v ON_ERROR_STOP=1 \
  -c 'TABLE ctxdb_meta.schema_versions;' -c 'TABLE ctxdb_meta.instances;'
```

metadata 版本为 1，format_id 为 contextdb-first-release，实例已绑定。无需调用实例注册 API，也无需等待服务启动才能获得 Admin Key。format_id 用于识别首发格式，即使旧实验也曾标记版本 1，仍会被拒绝；不要修改版本行强行复用旧库。

MaaS bge-m3 返回 1024 维，**不要设置 EMBEDDINGS_OPENAI_DIMENSIONS**，以免发送不支持的 dimensions 参数。openai/siliconflow 是兼容协议适配器，实际请求地址都是 MaaS。pepper 必须持久保存，修改它会使已有业务 Key 无效。

## 4 启动 API 与 UI

API 终端复用已有配置，不重新生成凭据：

```bash
source "$DEPLOY/operator.env"
source "$DEPLOY/api.env"
unset HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS HINDSIGHT_API_MCP_AUTH_TOKEN
cd "$CODE"
"$PY" -m hindsight_api.main --host 0.0.0.0 --port 8888
```

此验证部署使用 API 内嵌 Worker；生产是否分离 Worker 取决于容量与进程托管，不由这份手册承诺高可用。另开终端，将 DEPLOY 设置为刚才输出的实际目录：

```bash
export DEPLOY='/替换为刚才的部署目录'
source "$DEPLOY/operator.env"
export PATH="$(dirname "$NODE_BIN"):$PATH"
curl -fsS http://127.0.0.1:8888/health/ready
cd "$CODE"
npm ci
env -u PORT npm run build -w @vectorize-io/hindsight-control-plane
env -i HOME="$HOME" PATH="$PATH" DEPLOY="$DEPLOY" CODE="$CODE" NODE_BIN="$NODE_BIN" \
  bash -c 'source "$DEPLOY/ui.env"; export HOSTNAME=0.0.0.0 PORT=9999; cd "$CODE/hindsight-control-plane"; exec "$NODE_BIN" standalone/server.js'
```

UI 进程只继承专用 UI 配置，不继承数据库、模型 Key 或 pepper。浏览器打开 `http://服务器IP:9999`；应用访问 `http://服务器IP:8888`。放通对应网络端口，多机器可访问；正式网络入口配置 HTTPS。PG 仍只监听本机，业务客户端不直接连接数据库。

运维在本机查看登录密码：

```bash
(source "$DEPLOY/ui.env"; printf '%s\n' "$HINDSIGHT_CP_ACCESS_KEY")
```

管理员只用该密码登录；登录页为 `/login`，用户管理页为 `/users`，语言由 UI 设置决定。不要手工添加 `/en` 或 `/zh` 路径前缀；不要将 ui.env/admin-key.json/admin.curl 发给业务用户。

## 5 UI 验收：两空间、两用户、三把 Key

1. 工作空间列表创建 **MySQL** 和 **PG**，等待 active；切换空间应分别看到自己的内容。
2. 打开 **用户管理**，创建用户 **应用 A**、**应用 B**。创建时仅填写名称，不配置空间权限。
3. 应用 A 创建 `A-多空间`：指定 MySQL、PG，读写。再创建 `A-只读`：指定 MySQL，只读。
4. 应用 B 创建 `B-全部空间`：全部空间，读写。新建第三个空间后应自动可访问。
5. 检查 Key 表只显示名称、范围、权限、状态等元信息；新 Key 明文仅成功签发时展示一次。
6. 修改 `A-多空间` 的范围，只保留 MySQL；Key 明文不变，下一次访问 PG 被拒绝。
7. 停用应用 A，其两把 Key 的新请求均被拒绝；恢复用户后，未撤销 Key 恢复可用。
8. 撤销 `A-只读` 后不可恢复；普通 Key 无法登录 UI，也无法管理资源。UI 页面不展示内部 Admin Key、四个英文 scope 或用户层 ACL。

以下 API 操作供联调和检查，与 UI 调用同一组接口。先建立私有 curl 凭据文件（Admin 已在第 3 节生成），不要把明文 Key 写入终端历史。按提示粘贴 UI 刚生成的业务 Key：

```bash
source "$DEPLOY/operator.env"
export API=http://127.0.0.1:8888
for name in multi readonly all; do
  read -r -s -p "$name 业务 Key: " business_key
  printf '\n'
  printf 'header = "Authorization: Bearer %s"\n' "$business_key" > "$DEPLOY/$name.curl"
done
unset business_key
curl -fsS --config "$DEPLOY/admin.curl" "$API/ext/contextdb/v1/workspaces" \
  > "$DEPLOY/workspaces.json"
export MYSQL_ID=$(jq -er '.items[] | select(.name=="MySQL") | .workspace_id' "$DEPLOY/workspaces.json")
export PG_ID=$(jq -er '.items[] | select(.name=="PG") | .workspace_id' "$DEPLOY/workspaces.json")
```

UI 创建空间后，不要重复执行下面同名创建示例；它用于全新实例的 API 联调。将 NAME 分别设为 MySQL、PG。每次新操作使用不同幂等 Key；网络超时重试同一操作时复用同一个值。

```bash
wait_operation() {
  local operation_id="$1" state deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    curl -fsS --config "$DEPLOY/admin.curl" "$API/ext/contextdb/v1/operations/$operation_id" \
      > "$DEPLOY/operation.json" || return 1
    state=$(jq -er '.state' "$DEPLOY/operation.json") || return 1
    case "$state" in
      succeeded) return 0 ;;
      failed) jq '{state,error_code}' "$DEPLOY/operation.json" >&2; return 1 ;;
    esac
    sleep 2
  done
  printf '等待超时：任务可能仍在执行，请继续查询原 operation_id=%s\n' "$operation_id" >&2
  return 1
}
NAME=MySQL
IDEMPOTENCY=$("$PY" -c 'import secrets; print(secrets.token_hex(16))')
curl -fsS --config "$DEPLOY/admin.curl" -X POST "$API/ext/contextdb/v1/workspaces" \
  -H 'Content-Type: application/json' -H "Idempotency-Key: $IDEMPOTENCY" \
  -d "$(jq -nc --arg name "$NAME" '{name:$name}')" > "$DEPLOY/create-$NAME.json"
OP_ID=$(jq -er '.operation_id' "$DEPLOY/create-$NAME.json")
wait_operation "$OP_ID" || exit 1
```

初次创建可能需要初始化索引。failed 或长时间 running 时先检查日志与任务状态，不将空间当作成功；不要并发重跑 migrate 或按超时擅自解除删除屏障。

## 6 REST 基本功能与权限

在 UI 中完成第 5 节第 3、4 步后、修改权限前执行。下列成功请求会调用真实 MaaS 并产生费用；自动化 stub 测试不能代替它们。

```bash
curl -fsS --config "$DEPLOY/multi.curl" -X POST "$API/v1/default/banks/$MYSQL_ID/memories" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"content":"BlueWhale 项目的数据库是 MySQL，负责人是林舟。","document_id":"demo-mysql"}],"async":false}'
curl -fsS --config "$DEPLOY/multi.curl" -X POST "$API/v1/default/banks/$PG_ID/memories" \
  -H 'Content-Type: application/json' \
  -d '{"items":[{"content":"RedFox 项目的数据库是 PostgreSQL，负责人是周宁。","document_id":"demo-pg"}],"async":false}'
curl -fsS --config "$DEPLOY/readonly.curl" -X POST "$API/v1/default/banks/$MYSQL_ID/memories/recall" \
  -H 'Content-Type: application/json' -d '{"query":"BlueWhale 负责人和数据库是什么？","budget":"mid"}'
curl -fsS --config "$DEPLOY/readonly.curl" -X POST "$API/v1/default/banks/$MYSQL_ID/reflect" \
  -H 'Content-Type: application/json' -d '{"query":"根据记忆说明 BlueWhale 项目信息。","budget":"mid"}'
```

预期各返回 200；MySQL 的结果应包含 BlueWhale、林舟，不应混入 PG 空间的 RedFox、周宁。中文全文检索效果另外比较，不用一次问答代替质量测评。

拒绝用例不加 curl `-f`，直接检查 HTTP 状态（错误体会输出，不输出 Key）：

```bash
curl -sS --config "$DEPLOY/readonly.curl" -w '\nHTTP %{http_code}\n' \
  -X POST "$API/v1/default/banks/$MYSQL_ID/memories" \
  -H 'Content-Type: application/json' -d '{"items":[{"content":"不应写入"}],"async":false}'
curl -sS --config "$DEPLOY/readonly.curl" -w '\nHTTP %{http_code}\n' \
  -X POST "$API/v1/default/banks/$PG_ID/memories/recall" \
  -H 'Content-Type: application/json' -d '{"query":"RedFox"}'
curl -sS --config "$DEPLOY/all.curl" -w '\nHTTP %{http_code}\n' "$API/ext/contextdb/v1/users"
```

三个均应 403：只读不能 Retain、指定空间不能越界、全部空间业务 Key 也不是管理员。停用用户、改 Key 范围、撤销后，重复对应请求应立即体现新授权；已接受的后台任务不会因此自动取消。

业务 Key 可以读取记忆、文档、知识和授权的执行 trace；归档导出/下载、Webhook 配置与投递读取仍仅运维可用，因为原生归档可能包含运维密钥。只读不等于可以调用全部原生 GET 接口。

MCP 使用同一业务 Bearer Key 和 bank_id；只读 Key 可 Recall/Reflect，Retain 被拒绝，越界空间被拒绝。不存在额外共享 MCP Token。真实 MCP 客户端的最终验收单独记录。

## 7 删除与 PG 核对

创建无业务数据的临时空间，等待 active，再通过 UI 确认删除；UI 应显示删除中，完成后从正常列表消失。API 联调可以用：

```bash
# TEMP_ID 填临时空间 ID，不能填要保留的 MySQL/PG。
TEMP_ID='替换为临时空间ID'
DELETE_IDEMPOTENCY=$("$PY" -c 'import secrets; print(secrets.token_hex(16))')
curl -fsS --config "$DEPLOY/admin.curl" -X DELETE "$API/ext/contextdb/v1/workspaces/$TEMP_ID" \
  -H "Idempotency-Key: $DELETE_IDEMPOTENCY" > "$DEPLOY/delete.json"
# 在同一个操作终端复用第 5 节 wait_operation；新终端先复制该函数。
OP_ID=$(jq -er '.operation_id' "$DEPLOY/delete.json")
wait_operation "$OP_ID" || exit 1
"$PG_BIN/psql" -X "$DB_URL" -v ON_ERROR_STOP=1 \
  -c 'SELECT version FROM ctxdb_meta.schema_versions;' \
  -c 'SELECT name,state,schema_name FROM ctxdb_meta.workspaces ORDER BY created_at;' \
  -c 'SELECT extname,extversion FROM pg_extension ORDER BY extname;' \
  -c "SELECT schemaname,indexname FROM pg_indexes WHERE schemaname LIKE 'ctxdb_ws_%' ORDER BY 1,2;"
```

预期版本 1；MySQL/PG 对应不同 schema，映射 Bank ID 等于 workspace_id。删除保留元数据墓碑与 schema/空表，不以 DROP schema 作为验收标准。删除期间禁止新访问，并等待已接受任务排空；未知执行者须先停止，不能按时间自动清除保护。

## 8 重启与交付边界

前台运行可在各自终端 Ctrl-C；重启直接复用 operator.env、api.env、ui.env，不重新生成 pepper/Admin Key/UI 密码。本次临时 PG 在 API/UI 已停止后可由其操作者停止：

```bash
"$PG_BIN/pg_ctl" -D "$DEPLOY/pg-data" -m fast stop
```

这不是旧 5432 实例；不删除数据目录。正式环境将第 4 节前台命令交给现有节点 Agent/systemd 等托管，管控仍负责实例资源与进程，工作空间由 UI 管理。

运维 Admin Key 轮换：离线生成新值，同步更新 API 的 SHA-256 与 UI 固定 Key，协调重启；业务 Key 不变。不提供在线恢复或双 Key 过渡。产品首发兼容承诺从当前元数据版本 1 开始；未来 JSONB 扩展字段可放非安全属性，关系与约束变化仍需有序迁移；当前没有实现未来版本的通用升级工具。
