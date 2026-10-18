# ContextDB v2 部署与使用手册

> **历史快照，不适用于当前首发版本。** 下文保留当时的配置、接口、表结构和测试环境用于对照，不应照此部署或验证当前代码。当前以[首发设计](contextdb-release-design.md)、[部署合同](contextdb-deployment-contract.md)和[API验证手册](contextdb-optimized-curl-guide.md)为准；开发期旧库不自动升级。


日期：2026-10-15。随 ContextDB V2 代码维护，供开发者及 AI 助手快速接手当前版本。以下区分“现有实例”和“独立新部署”，不要对已有实例重复生成 pepper 或替换数据库。新部署步骤是操作指南，尚未按本手册重新部署验收。

## 1 先识别版本和入口

| 项目 | 当前约定 |
| --- | --- |
| 代码分支 | `contextdb/service-management-v2`；完整 V2 为独立功能提交 |
| 上游基线 | `a77c1f3412a7b82f36588dffce1a8d7480e99cc7`，与 V1 共用 |
| V1 对照 | `contextdb/service-management` / `cdfc199e5f48b1d9cc9a99119b3efb761f656ef6` |
| 版本比较 | [V1/V2 分支和对比命令](version-comparison.md) |
| 设计 | [实例级用户、多空间 Key、管理员 UI](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/member-apikey-bank-service-design-v2.md) |
| 管理协议 | [18 个管理 REST 操作](contextdb-control-plane.openapi.yaml)，前缀仍是 `/ext/contextdb/v1` |
| 本机配置 | [完整显式配置清单](contextdb-v2-deployment-environment.md) |
| 操作验证 | [管理面、数据面、REST/MCP、UI、PG 用例](contextdb-v2-local-validation-guide.md) |

设计研究材料在独立研究仓维护；部署和接口行为以本分支 README、操作手册和随版 OpenAPI 为准。不要混用 v1 设计中的 `workspace_members`、单空间成员 Key 接口。v2 metadata 版本为 2，不提供 v1 原库迁移；新部署使用新空库。

当前体验实例 API `127.0.0.1:8888`，UI `localhost:9999`。配置和日志在：

```text
/Users/zhuqingping/Work/Database/Context/test/hindsight_test/contextdb-v2-experience/20261015-104834-735ecc
```

同级 `latest-run.txt` 指向当前运行目录。`runtime.json` 确认代码和数据库；`deployment.json`、`model.env`、`ui-settings.json` 保存启动配置；`api.log`、`ui.log` 排查错误；`processes.json` 记录进程。文件不是配置中心，修改文件不会自动更新已启动进程。

## 2 产品与权限模型

```text
一个云租户的独享实例
├── 唯一实例管理员（不可删除/停用）
├── 普通用户（空间上限 all 或 selected）
│   └── 多把独立 API Key（逐空间 scopes，无子 Key）
└── 多个工作空间
    └── 每空间独立 PG schema + 唯一原生 Bank
```

`workspace_id = bank_id`，schema 为 `ctxdb_ws_<32hex-id>`。空间间数据隔离，同空间内容共享。最终权限取用户空间上限与 Key 逐空间 scope 的交集；不用 tags 充当用户 ACL。

| 凭据 | 谁使用 | 能做什么 |
| --- | --- | --- |
| Console 服务 Key | 可信云管控后端 | 初始化实例、创建/删除/查询空间、管理员 Key 恢复；附可信 actor，受来源网络约束 |
| 管理员 all API Key | 管理员客户端、UI 服务端 | 全空间 REST/MCP、用户/Key 管理，包含未来空间 |
| 普通 selected API Key | Agent/业务客户端 | 授权空间及 scope 内的 REST/MCP，无用户/Key 管理能力 |
| UI 独立口令 | 管理员浏览器 | 登录 UI；不是业务 API Key，也不是 PG 密码 |
| PG 服务角色连接串 | API/Worker、bootstrap | 连接同一个 PG 数据库 |

scope：`memory.read`、`memory.write`、`knowledge.read`、`reflect`。write 和 reflect 必须包含 read；knowledge.read 不授予原始记忆/模型读取。省略 Key grants 会快照当前允许的空间且赋四类 scope；显式 `[]` 是零授权，建议业务始终显式配置 grants。

`Initial administrator` Key 首次初始化返回 secret 一次；随后列表只有元信息。它不可修改 all 授权、不会过期；可以另签 all Key 后撤销旧 Key，最后一把有效 all Key 受保护。UI 固定 Key 被撤销前必须先换配置并重启 UI。

业务 API（包括 admin/all）不能创建/删除/改名 Bank、clone 或 Bank 恢复导入；空间生命周期经 Console。UI 通过 API 访问内容，UI 不直接连 PG。

## 3 独立新部署的准备

当前 PG 已有服务不要停止。以下示例使用 **新库、API 8890、UI 9998**，避免占用体验实例。先检查这些名字和端口未被使用；不要用现有库名。

```bash
bash
umask 077
export REPO=$(git rev-parse --show-toplevel)
export DEPLOY="$HOME/contextdb-runs/contextdb-v2-new-$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$DEPLOY"
export NEW_DB=ctxdb_v2_new_$(date +%Y%m%d_%H%M%S)_$$
export PG_BIN=/Users/zhuqingping/Work/Database/PG/pg_18_4/bin
"$PG_BIN/createdb" -h 127.0.0.1 -p 5432 -U zhuqingping -T template0 -E UTF8 --locale=C "$NEW_DB"
export DB_URL="postgresql://zhuqingping@127.0.0.1:5432/$NEW_DB"
"$PG_BIN/psql" -X "$DB_URL" -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS btree_gin WITH SCHEMA public;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pgroonga;' \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;' \
  -c 'SHOW server_encoding;'
```

二进制需先安装到运行 PG 的 prefix，方法见 [PG 插件章节](postgresql-extensions.md)。PGroonga 还依赖系统 Groonga。上面的 CREATE 不启用 preload 或完成恢复验收，详见验证手册第 2 节。当前旧体验库为 SQL_ASCII，本示例明确创建 UTF8。

准备独立 Python 环境，避免同步共享 `.venv` 影响现有服务：

```bash
cd "$REPO"
export UV_PROJECT_ENVIRONMENT="$DEPLOY/venv"
uv sync --frozen
export PY="$DEPLOY/venv/bin/python"
export PYTHONPATH="$REPO/hindsight-extensions/contextdb-service${PYTHONPATH:+:$PYTHONPATH}"
"$PY" -m hindsight_ext_contextdb generate-control-key > "$DEPLOY/control-key.json"
```

`contextdb-service` 当前不是独立打包分发，使用上述 PYTHONPATH 导入自研扩展。真实交付需封装镜像/部署包并固定依赖；不要只安装上游发布包后期望自研模块自动存在。

## 4 一次性写入配置并安装 metadata

输入自己的 MaaS Key，生成一次部署配置。文件已经存在时脚本拒绝覆盖，重启用原文件。

```bash
read -r -s -p 'MaaS API Key: ' MAAS_API_KEY
printf '\n'
export MAAS_API_KEY
"$PY" - <<'PY'
import json, os, secrets, shlex
from pathlib import Path
r = Path(os.environ['DEPLOY'])
c = json.loads((r/'control-key.json').read_text())
key = os.environ['MAAS_API_KEY']
settings = {
 'CONTEXTDB_INSTANCE_ID': 'ctxdb-v2-new-local',
 'CONTEXTDB_CLOUD_TENANT_ID': 'local-cloud-tenant',
 'CONTEXTDB_KEY_PEPPER': secrets.token_urlsafe(48),
 'CONTEXTDB_CONTROL_KEYS': json.dumps([{'key_id':c['key_id'],'sha256':c['sha256']}]),
 'CONTEXTDB_CONTROL_NETWORKS': '127.0.0.1/32,::1/128',
 'CONTEXTDB_BOOTSTRAP_DATABASE_URL': os.environ['DB_URL'],
 'HINDSIGHT_API_DATABASE_URL': os.environ['DB_URL'],
 'HINDSIGHT_API_TENANT_EXTENSION': 'hindsight_ext_contextdb.tenant:ContextDBTenantExtension',
 'HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION': 'hindsight_ext_contextdb.validator:ContextDBOperationValidator',
 'HINDSIGHT_API_HTTP_EXTENSION': 'hindsight_ext_contextdb.http:ContextDBHttpExtension',
 'HINDSIGHT_API_MCP_EXTENSION': 'hindsight_ext_contextdb.mcp:ContextDBMCPExtension',
 'HINDSIGHT_API_MIGRATION_ISOLATION': 'false',
 'HINDSIGHT_API_WORKER_ENABLED': 'true',
 'HINDSIGHT_API_MCP_ENABLED': 'true',
 'HINDSIGHT_API_PORT': '8890',
 'HINDSIGHT_API_DB_POOL_MAX_SIZE': '10',
 'HINDSIGHT_API_READ_DB_POOL_MAX_SIZE': '10',
 'HINDSIGHT_API_VECTOR_EXTENSION': 'pgvector',
 'HINDSIGHT_API_TEXT_SEARCH_EXTENSION': 'pgroonga',
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
with (r/'api.env').open('x') as f:
    f.write(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in settings.items()))
print('配置已保存，凭据未输出。')
PY
source "$DEPLOY/api.env"
unset HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS
"$PY" -m hindsight_ext_contextdb migrate
```

不要使用 `HINDSIGHT_API_TENANT_USERS` 替代动态扩展，不固定工作空间 schema，不另设 MCP 静态 Token 与业务认证混用。1024 维从 bge-m3 响应探测，dimensions 请求参数不设置。

## 5 启动 API、初始化实例和空间

在单进程本地实例启动 API（内嵌 Worker）：

```bash
cd "$REPO"
nohup "$PY" -m hindsight_api.main --host 127.0.0.1 --port 8890 > "$DEPLOY/api.log" 2>&1 &
echo "$!" > "$DEPLOY/api.pid"
curl -fsS http://127.0.0.1:8890/health/ready
```

初次启动需迁移/模型探测，ready 未通过时先等待并检查 api.log，不提交创建请求。

```bash
CONTROL_KEY=$("$PY" -c 'import json,os; print(json.load(open(os.environ["DEPLOY"]+"/control-key.json"))["secret"])')
curl --fail-with-body -sS -X POST http://127.0.0.1:8890/ext/contextdb/v1/instances \
  -H 'Content-Type: application/json' -H "X-ContextDB-Control-Key: $CONTROL_KEY" \
  -H 'X-ContextDB-Actor-Subject: local-console-admin' \
  -d '{"instance_id":"ctxdb-v2-new-local","name":"ContextDB v2 new local"}' > "$DEPLOY/instance-bootstrap.json"
```

预期 HTTP 201，首次响应包含 admin_user 和 admin_key.secret。立即保存响应；重复请求不会再次返回 secret，不覆盖首次响应文件。用服务 Key 创建空间：

```bash
curl --fail-with-body -sS -X POST http://127.0.0.1:8890/ext/contextdb/v1/workspaces \
  -H 'Content-Type: application/json' -H "X-ContextDB-Control-Key: $CONTROL_KEY" \
  -H 'X-ContextDB-Actor-Subject: local-console-admin' -H 'Idempotency-Key: create-mysql-first' \
  -d '{"name":"MySQL"}' > "$DEPLOY/create-mysql.json"
```

预期 HTTP 202；从响应取 operation_id，GET `/ext/contextdb/v1/operations/{operation_id}`，附同样管控头，轮询 state=succeeded；再 GET `/workspaces/{workspace_id}` 确认 active。创建 PG 空间时用不同名称和幂等 Key。不要调用原生 Bank 创建接口。

## 6 配置与启动 UI

独立口令和固定管理员 Key 写入专用 UI 文件；不把 MaaS/pepper 传给 UI。

```bash
"$PY" - <<'PY'
import json, os, secrets, shlex
from pathlib import Path
r = Path(os.environ['DEPLOY'])
bootstrap = json.loads((r/'instance-bootstrap.json').read_text())
settings = {
 'HINDSIGHT_CP_CONTEXTDB_ENABLED': 'true',
 'HINDSIGHT_CP_ACCESS_KEY': secrets.token_urlsafe(18),
 'HINDSIGHT_CP_DATAPLANE_API_KEY': bootstrap['admin_key']['secret'],
 'HINDSIGHT_CP_DATAPLANE_API_URL': 'http://127.0.0.1:8890',
}
with (r/'ui.env').open('x') as f:
    f.write(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in settings.items()))
print('UI 配置已保存；登录口令在私有 ui.env 中查看。')
PY
```

构建 UI 使用根依赖和已生成的 TypeScript SDK。在新终端操作，避免继承 API 的模型凭据：

```bash
# 设置本次 REPO/DEPLOY 的实际目录，不重新执行第 3 节创建新目录。
cd "$REPO"
npm ci
npm run build -w @vectorize-io/hindsight-control-plane
source "$DEPLOY/ui.env"
PORT=9998 HOSTNAME=localhost NODE_ENV=production nohup node hindsight-control-plane/standalone/server.js > "$DEPLOY/ui.log" 2>&1 &
echo "$!" > "$DEPLOY/ui.pid"
```

构建时不设置 PORT，输出默认 .next；运行时端口使用 9998。完整 standalone 包包含 static/public，不只复制 server.js。UI 日志确认 ready 后访问 `http://localhost:9998`；当前旧体验 UI 使用 `localhost:9999`。本机 Next 国际化路由用 127.0.0.1 访问可能发生重定向循环，因此 UI 统一使用 localhost；后端 API 地址继续用 127.0.0.1。

UI 登录仅输入独立口令。ContextDB 模式的英文和中文界面使用 Workspace/工作空间；原生模式继续使用 Bank。其他语言暂保留原翻译。

## 7 使用接口

管理员 UI 创建用户，配置用户空间上限，再创建 Key，明确每空间 scopes。Key secret 一次显示，应立即保存在应用密钥配置中。

业务 REST 使用 `Authorization: Bearer <业务 API Key>`：

```text
POST /v1/default/banks/{bank_id}/memories          Retain
POST /v1/default/banks/{bank_id}/memories/recall   Recall
POST /v1/default/banks/{bank_id}/reflect           Reflect
GET  /v1/default/banks                            授权空间列表
```

Retain 示例 body：

```json
{"items":[{"content":"蓝鲸项目负责人是林澈。","document_id":"bluewhale-intro"}],"async":false}
```

Recall 示例 body：`{"query":"蓝鲸项目由谁负责？","budget":"mid"}`。Reflect 需 reflect scope，示例 body：`{"query":"根据已有记忆解释蓝鲸项目的信息。","include":{"facts":{}}}`。

异步 Retain 返回 operation_id 后，GET `/v1/default/banks/{bank_id}/operations/{operation_id}`，等待 status=completed。接受请求不代表后台已完成。

MCP 使用 `/mcp/` 和同样 Bearer；调用 `retain`/`recall`/`reflect` 时传 bank_id。`/mcp/{bank_id}/` 固定一个空间；不提供 schema。权限变化对原 Key、旧 MCP 会话下一请求生效。

用户/Key 管理使用管理员 all Bearer 调 `/ext/contextdb/v1/users` 等接口；更新用户和 Key 必须携带 `If-Match: "<version>"`。完整命令、权限矩阵及 18 个管理操作见验证手册，不再维护第二份接口合同。

## 8 排查和交付边界

| 现象 | 优先检查 |
| --- | --- |
| ModuleNotFoundError: hindsight_ext_contextdb | 当前代码是否完整 v2；PYTHONPATH；Python 环境 |
| 启动拒绝 metadata | 是否新库、schema_versions 是否仅 2；不要覆盖 v1 表 |
| 401 | Key 是否正确、用户是否停用、Key 是否撤销/到期；UI 密码和 API Key 是否混淆 |
| 403 | 用户空间上限、Key grants/scopes、目标 Bank 是否已登记 active |
| 400 / 412 | 请求体、带引号的 If-Match / 旧版本冲突 |
| 无法中文检索 | UTF8、全文后端、实际 PGroonga 索引、中文业务样本；不要只查 pg_extension |
| MaaS Embedding 400 | 是否误设置 dimensions；模型/地址/Key |
| 任务 pending/failed | Worker 开关、API 日志、模型配额/请求错误、PG 连接预算 |
| UI 503/无法进入 | UI 独立口令、固定 Key 是否 admin/all、后端地址、后端 admin/session |
| 删除长期阻塞 | 在途任务与持久准入；未知执行者先 fencing，不直接删 metadata |

重新启动使用原配置文件、原 pepper、同一个数据库。停止服务前按运行记录确认进程归属，正常终止自己的 API/UI，等待排空；不使用宽泛 pkill，不停止已有 PG。多副本、HA、RDS 特权角色、容量、故障恢复仍需生产联调，本地测试不能代替。

新库 PG 权限应区分服务角色与客户受限角色；真正 SUPERUSER/root 可以访问和修改服务对象，无法仅靠同库 schema ACL 防止。

交接给 AI 时先提供：代码目录/分支/脏状态、上述设计与三份手册、运行目录、操作范围和可执行的验证项。凭据通过私有运行文件提供，不粘贴到任务文档。AI 应先查现状再操作，不能把“手册有命令”视为已获准清库、改生产配置或提交推送。
