# ContextDB 首发优化版：部署、升级与使用

当前交付分支 `contextdb/first-release`，上游基线 `a77c1f341`；代码、设计、部署和运维文档整理为同一个功能提交。首发元数据 **1**、管理 API **v1**。新空间使用可读 Bank ID 和 schema。本文保留源码部署与升级细节；夜间00a921b52快照的容器在本机Colima的OPENSSL_armcap=0兼容覆盖下通过；首发基线1须重新构建镜像，目标ECS原样启动仍未验收（见[容器实测](contextdb-service-research-validation.md#6-容器功能与同预算小样本对照)），不将本机测试等同云上交付。

[设计](contextdb-release-design.md) · [逐接口 curl](contextdb-optimized-curl-guide.md) · [OpenAPI](contextdb-control-plane.openapi.yaml) · [管控与节点集成指南](contextdb-service-integration-guide.md) · [Agent 部署合同](contextdb-deployment-contract.md) · [运维手册](contextdb-operations-runbook.md)。节点 Agent 负责实例部署/启停/升级；工作空间、成员、Key 在 UI 管理。没有 HTTP 创建实例接口。

生产接入优先使用部署合同的 JSON 意图及 `scripts/node-agent.sh validate/render/status`，避免各方自行拼接环境变量。输入 PG URI、MaaS Key 和客户指定 UI 密码均来自0600文件；输出私密配置由现有 Agent/监督器管理。下文手工源码方式适用于开发联调，不能替代目标 RDS 插件、容器或高可用验收。

## 1. 匹配的代码和环境

API、扩展、UI 来自同一份已审核源码/交付产物。记录提交、补丁或构建清单，不将扩展单独复制到任意 upstream。

```bash
export CODE='/实际的同版源码根目录'
cd "$CODE"
git rev-parse HEAD
git status --short
uv sync --frozen
export PY="$CODE/.venv/bin/python"
uv pip install --python "$PY" --no-deps -e "$CODE/hindsight-extensions/contextdb-service"
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim"
export HINDSIGHT_API_ENV_FILE=''
```

支持 Python3.11～3.14，本机验证3.11。外部 PG 不要求 pg0；内嵌/测试才安装 hindsight-api-slim[embedded-db]，发行包名 pg0-embedded、导入名 pg0，不能 pip install pg0。安装后仍预检真实模块路径。

UI 使用 Node22.12+或24及配套 npm，不能复制其他 OS/CPU 的 node_modules。允许平台 optional dependencies。配置为 .mjs，使用系统字体，不下载 Google Fonts。

```bash
node --version
npm --version
cd "$CODE"
npm ci --include=optional
"$PY" -m hindsight_ext_contextdb build-ui --source-root "$CODE"
test -f "$CODE/hindsight-control-plane/standalone/server.js"
```

## 2. PG 与插件

准备 UTF8 专用数据库及服务账号。服务账号拥有 ctxdb_meta/ctxdb_ws_*；客户 SQL 账号使用独立非超级用户。同 PG 内无法隔离真正 SUPERUSER/OS root。

先安装匹配 PG 的扩展二进制，再在目标数据库 CREATE EXTENSION。源码 pg_config、contrib、pgvector、PGroonga 编译命令见代码仓 docs/postgresql-extensions.md；Homebrew PG 插件目录不能代替源码 PG 安装目录。

```bash
# 通过 PGHOST/PGPORT/PGUSER/PGPASSFILE 安全配置已有管理连接。
# 数据库已存在时不重复 createdb，实际账号/密码按实例替换。
createdb --encoding=UTF8 --template=template0 --owner=contextdb_service contextdb_release
# 此处 PGUSER 是已获准安装插件的供应账号；凭据通过 PGPASSFILE 提供。
export PGDATABASE=contextdb_release
psql -X -v ON_ERROR_STOP=1 \
 -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;' \
 -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;' \
 -c 'CREATE EXTENSION IF NOT EXISTS btree_gin WITH SCHEMA public;' \
 -c 'SHOW server_encoding;'
```

| 场景 | 设置与依赖 |
| --- | --- |
| 英文基本全文 | TEXT_SEARCH_EXTENSION=native，三项基础扩展照常启用 |
| 中英文部署路线 | TEXT_SEARCH_EXTENSION=pgroonga，另 CREATE EXTENSION pgroonga |
| 可选 pg_search | 安装匹配 PG 的 pg_search，显式配置已安装的中文 tokenizer |
| SQL 观测 | pg_stat_statements，preload 变更需维护窗口重启；启用扩展不等于运行配置完成 |

PGroonga 是本仓已实现的中英文候选路径，不代表目标华为云 RDS 已开放或已选定云上默认值。须核实 RDS 可安装能力，以及 Groonga 的 LGPL 许可、PGroonga 的恢复/备份/复制要求。pg_search 的中文 tokenizer 同样需要实际版本支持；native+zhparser、pg_textsearch+中文配置仍需适配与质量验收，不自动降级为英文。btree_gin 不是分词器。

```bash
# 中英文路线执行，英文 native 跳过。
psql -X -v ON_ERROR_STOP=1 \
 -c 'CREATE EXTENSION IF NOT EXISTS pgroonga;' \
 -c "SELECT * FROM pgroonga_tokenize('中文检索 English', 'tokenizer', 'TokenBigram');" \
 -c 'SELECT extname,extversion,extnamespace::regnamespace FROM pg_extension ORDER BY extname;'
```

## 3. 私密持久配置及初始化

```bash
umask 077
export CONTEXTDB_DEPLOY_DIR="$HOME/.contextdb/release"
mkdir -p "$CONTEXTDB_DEPLOY_DIR"
chmod 700 "$CONTEXTDB_DEPLOY_DIR"
export SERVICE="$CODE/hindsight-extensions/contextdb-service/scripts/service.sh"
```

外部 PG 数据库与服务账号必须由管控预先创建，服务不会自行创建数据库。上面的 psql 走 PGHOST/PGPORT/PGUSER/PGPASSFILE；应用 URI 另由秘密输入提供，避免将含密码 URI 作为 psql 参数：

```bash
read -r -s -p '应用服务 PG URI: ' HINDSIGHT_API_DATABASE_URL
printf '\n'
export HINDSIGHT_API_DATABASE_URL
```

首次创建 api.env，连接串来自上述私密环境。先补齐自己的模型设置；同一部署重启不得改实例/租户 ID。下例 x 模式拒绝覆盖已有配置。

```bash
"$PY" - <<'PY'
import os, shlex
from pathlib import Path
settings = {
 'HINDSIGHT_API_DATABASE_URL': os.environ['HINDSIGHT_API_DATABASE_URL'],
 'CONTEXTDB_INSTANCE_ID': 'ctxdb-release',
 'CONTEXTDB_CLOUD_TENANT_ID': 'cloud-tenant-id',
 'HINDSIGHT_API_TENANT_EXTENSION': 'hindsight_ext_contextdb.tenant:ContextDBTenantExtension',
 'HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION': 'hindsight_ext_contextdb.validator:ContextDBOperationValidator',
 'HINDSIGHT_API_HTTP_EXTENSION': 'hindsight_ext_contextdb.http:ContextDBHttpExtension',
 'HINDSIGHT_API_MCP_EXTENSION': 'hindsight_ext_contextdb.mcp:ContextDBMCPExtension',
 'HINDSIGHT_API_MCP_ENABLED': 'true',
 'HINDSIGHT_API_MIGRATION_ISOLATION': 'false',
 'HINDSIGHT_API_WORKER_ENABLED': 'true',  # 本示例明确采用 merged；split 改 false 并独立启动 Worker
 'HINDSIGHT_API_WORKER_ID': 'ctxdb-release-worker-1',
 'HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP': 'false',
 'HINDSIGHT_API_LLM_TRACE_ENABLED': 'false',
 'HINDSIGHT_API_AUDIT_LOG_ENABLED': 'false',
 'HINDSIGHT_API_TEXT_SEARCH_EXTENSION': 'pgroonga',
 'CONTEXTDB_VALIDATION_LANGUAGE': 'multilingual',
 'HINDSIGHT_API_HOST': '0.0.0.0',
 'HINDSIGHT_API_PORT': '8888',
}
path = Path(os.environ['CONTEXTDB_DEPLOY_DIR']) / 'api.env'
with path.open('x') as out:
 out.write(''.join(f'{k}={shlex.quote(v)}\n' for k,v in settings.items()))
path.chmod(0o600)
PY
# ui.env 也仅首次创建；已有部署复用文件。
(set -o noclobber; cat > "$CONTEXTDB_DEPLOY_DIR/ui.env" <<'ENV'
HINDSIGHT_CP_CONTEXTDB_ENABLED=true
HINDSIGHT_CP_DATAPLANE_API_URL=http://127.0.0.1:8888
HINDSIGHT_CP_HOST=0.0.0.0
HINDSIGHT_CP_PORT=9999
ENV
)
chmod 600 "$CONTEXTDB_DEPLOY_DIR/ui.env"
```

服务化必须使用客户指定 UI 密码，按部署合同传 `ui_password_file`，校验至少12字符。手工开发路径也应在首次 init 前将 `HINDSIGHT_CP_ACCESS_KEY` 安全写入0600的 ui.env；仅未指定密码的开发 CLI 保留随机生成能力。初始化后以 ui-secrets.json 为持久秘密来源，不再用启动环境重生。浏览器只使用 UI 密码，不感知后台 Admin Key。

手工源码方式可在第一次 init 前执行以下命令，密码不会出现在 shell 参数或历史中；已有部署不重复追加：

```bash
"$PY" - <<'PYUI'
import getpass, os, shlex
from pathlib import Path
path = Path(os.environ['CONTEXTDB_DEPLOY_DIR']) / 'ui.env'
if any(line.startswith('HINDSIGHT_CP_ACCESS_KEY=') for line in path.read_text().splitlines()):
 raise SystemExit('已有UI密码配置，请复用原私密文件')
password = getpass.getpass('客户指定的 UI 密码: ')
if len(password) < 12 or password.startswith(('ctx_admin_', 'ctx_live_', 'ctx_ctrl_')):
 raise SystemExit('使用至少12字符且独立于API Key的密码')
with path.open('a') as out:
 out.write('HINDSIGHT_CP_ACCESS_KEY=' + shlex.quote(password) + '\n')
path.chmod(0o600)
PYUI
```

MaaS 的 LLM/Embedding/Rerank 设置沿用已验证的模型接入，写入私密 api.env，不将真实 Key 放入文档。bge-m3 新库使用1024维，不向不支持的接口发送 dimensions；维数必须匹配原库。变量定义以本分支 .env.example、hindsight_api/config.py 为准。


MaaS 可按当前已验证适配写入配置。下面从安全终端读取 Key，不回显；已有模型配置时先核对，不重复追加。仅首次配置，模型ID可按已开通服务调整。

```bash
"$PY" - <<'PY'
import getpass, os, shlex
from pathlib import Path
key = getpass.getpass('MaaS API Key: ')
if not key: raise SystemExit('需要有效模型Key')
values = {
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
path=Path(os.environ['CONTEXTDB_DEPLOY_DIR'])/'api.env'
if any(line.startswith(k+'=') for line in path.read_text().splitlines() for k in values):
 raise SystemExit('已有模型配置，请核对原文件')
with path.open('a') as out:
 out.write(''.join(f'{k}={shlex.quote(v)}\n' for k,v in values.items()))
 out.write('unset HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS HINDSIGHT_API_MCP_AUTH_TOKEN\n')
PY
```

```bash
"$SERVICE" preflight --ui-build --language multilingual
"$SERVICE" init
```

init：只读预检 → 保存三个秘密文件 → migrate 建管理表/导入管理员 HMAC → 显式迁移 public 共享原生任务表，全程不依赖 API。运行 API 必须禁用自动启动迁移，以及原生后台 LLM trace/audit 写入；新工作空间仍由受保护的生命周期显式迁移 schema。秘密文件0600、目录0700，原值不覆盖；已初始化但缺文件时拒绝重新生成，要求恢复备份。

| 文件 | 内容及使用方 |
| --- | --- |
| api.env | PG、模型、实例绑定及扩展；API/Worker |
| admin-key.json | key_id、secret，可有 sha256 交付校验；离线导入/恢复 |
| api-secrets.json | pepper，HMAC 密钥，数据库不存；API/Worker |
| ui.env | UI 开关、API URL、监听地址/端口 |
| ui-secrets.json | UI password、后台 Admin Key；仅 UI 服务端 |

初始化、管理员离线轮换和API/Worker统一使用 HINDSIGHT_API_DATABASE_URL 与同一个专用服务账号。运行期创建工作空间仍需DDL权限，不另设引导连接或只读写运行账号。PG数据库和插件由管控/数据库管理员预先准备；API/Worker不继承UI秘密。管理员与业务 Key 统一由PG中的HMAC摘要校验。

## 4. 启停与重启

以下前台命令交给已有节点 Agent/systemd/容器监督器。部署意图必须明确选择 merged 或 split；不是按未经测量的性能宣传选默认。本节手工示例使用 API 内嵌 Worker，勿重复启动独立 Worker。split 将 WORKER_ENABLED=false，另由监督器启动 Worker；共享 PG、pepper、模型及扩展，Worker 稳定 ID 在副本间唯一，健康端口默认8889。两种方案差异及决策依据见[设计2.5](contextdb-release-design.md#api-worker-deployment)。

```bash
# 终端/监督器一，前台 API（本示例明确采用 merged）
"$SERVICE" api
# 终端/监督器二，等待 API 就绪后前台 UI
"$SERVICE" ui
# 仅独立 Worker 模式，在其监督器执行：
# "$SERVICE" worker
```

脚本等待 /health/ready 最多60秒；UI 自身对暂时依赖故障最多重试30秒。错误凭据/成员身份立即失败。每次实际请求仍实时鉴权。正常停止由监督器 SIGTERM 并等待退出，不广泛 pkill。重启只执行 api/ui，不重新 init/生成 Key 或 pepper。

API/UI 默认0.0.0.0，允许其他机器访问；远端使用部署机可达地址。UI 的后端 API URL 供服务端使用；浏览器不持后台 Key。HTTPS、限流、请求体上限和防火墙由入口负责。

```bash
# 只在受控终端查看，不开启 set -x。
jq -r '.password' "$CONTEXTDB_DEPLOY_DIR/ui-secrets.json"
export ADMIN_KEY=$(jq -er '.secret' "$CONTEXTDB_DEPLOY_DIR/admin-key.json")
export API='http://127.0.0.1:8888'
curl -fsS "$API/health/ready" | jq .
curl -fsS "$API/ext/contextdb/v1/admin/identity" -H "Authorization: Bearer $ADMIN_KEY" | jq .
```

## 5. 首发基线、后续升级与管理员恢复

首发管理元数据结构版本固定为1。migrate仅初始化新库，或核对已经采用当前结构的数据库；开发期试验结构不作为已发布版本，不自动升级或直接改号。已有试验库先保留数据和配置备份，再使用新的专用数据库验证；不能仅修改metadata_version冒充结构匹配。未来正式发布结构变更时，再从版本1增加有序迁移。

**原生诊断写入检查：** 升级前使用旧版本支持的配置入口显式关闭 Bank 的 `audit_log_enabled`，核对默认模板也未开启审计。新版启动和迁移拒绝既有 `banks.config` 或默认模板中的开启值，内外部配置修改都不允许重新打开；不能通过手改元数据版本号规避。管理审计 `ctxdb_meta.audit_events` 不受此限制。

原生业务表的Alembic版本与管理元数据版本独立。下列命令仅用于已经采用首发结构的实例，在后续发行版本明确要求升级原生业务表时执行；不用于接管开发期试验库。保持服务停止，使用原服务账号连接、从目录读取实际 schema，再逐个执行同版原生迁移：

```bash
# 全部API/Worker已停止；显式加载本实例配置，不依赖之前终端的临时环境。
set -a
source "$CONTEXTDB_DEPLOY_DIR/api.env"
set +a
export HINDSIGHT_API_ENV_FILE=''
# psql 的 PGHOST/PGPORT/PGUSER/PGDATABASE/PGPASSFILE 也必须指向同一服务库。
psql -X -A -t -v ON_ERROR_STOP=1 \
 -c "SELECT 'public' UNION SELECT schema_name FROM ctxdb_meta.workspaces ORDER BY 1" \
 > "$CONTEXTDB_DEPLOY_DIR/native-schemas.list"
migration_failed=0
while IFS= read -r schema; do
 HINDSIGHT_API_TENANT_EXTENSION='' "$PY" -m hindsight_api.admin.cli run-db-migration \
  --schema "$schema" --embedding-dimension 1024 || { migration_failed=1; break; }
done < "$CONTEXTDB_DEPLOY_DIR/native-schemas.list"
test "$migration_failed" -eq 0
```

必须核对每个 schema 均成功后再恢复 API/Worker；失败时保留错误证据并修复，不执行后续启动。不要不带 `--schema` 触发未绑定引擎的租户发现，不把 RUN_MIGRATIONS_ON_STARTUP 改回 true。升级后重开进程和连接池，不复用旧结构的缓存执行计划。

实例/租户不符、秘密不匹配或不支持的结构拒绝初始化，不改版本号强行通过。保留原配置及数据备份；管理员恢复仅适用于当前首发结构。

管理员明文遗失时，数据库所有者可显式离线轮换，保留原 pepper。生成新文件、更新 PG，再备份并更新 admin-key.json 与 ui-secrets.json 的明文，启动 UI。命令不覆盖现有秘密文件。

```bash
"$PY" -m hindsight_ext_contextdb generate-admin-key --output "$CONTEXTDB_DEPLOY_DIR/admin-key-next.json"
"$PY" -m hindsight_ext_contextdb rotate-admin-key --directory "$CONTEXTDB_DEPLOY_DIR" \
 --admin-key-file "$CONTEXTDB_DEPLOY_DIR/admin-key-next.json"
```

只更新 PG 而忘记 UI 会导致 UI 拒绝启动。pepper 遗失不能通过轮换 Admin Key 恢复业务 Key，需原配置或重新签发。修改 UI 密码应同步更新 ui-secrets.json 与 input/ui-password 的源值；无需改PG/API，旧会话失效。非容器部署重启UI，Compose逐文件挂载在原子替换后须 `up -d --force-recreate ui` 重新建立挂载，不能仅普通restart；部署合同有具体说明。

## 6. 使用与验收

按 curl 手册创建两个空间/用户和逐空间 Key，验证原生 REST/MCP、管理员访问、业务 Key 管理拒绝、停用/吊销及同名重建。UI 登录仅用 password；新空间名称经 NFKC/trim/小写规范化后同时作为 bank_id，规则 `^[a-z][a-z0-9_]{0,53}$`，例如 MySQL→mysql、schema=ctxdb_ws_mysql。首版不接受中文名称、连字符或改名；这是对齐原生未加引号 schema SQL 的约束，不改写记忆算法。内部 workspace_id 仍为随机不可复用 UUID。

管理 GET/DELETE `/workspaces/{bank_id}`、原生 REST `/v1/default/banks/{bank_id}/...` 和单/多 Bank MCP 都用相同外部 bank_id。目录响应给出带双引号的 `etag="<workspace_id>:<version>"`，DELETE 必须原样传 `If-Match`，并提供 Idempotency-Key；缺少条件428、错误格式400、旧代次412。操作记录过期后，旧 ETag 仍不能误删同名新空间。

selected 授权按 bank_id 选择，服务端仍保存 workspace_id。UI 新建或编辑 Key 会同时发送所见 `workspace_id` 期望值，空间被同名替换则409并要求刷新；API 可省略该期望值，但含义是“授权当前同名对象”。旧 Key 的已有空间关联不会继承新对象，旧编辑版本也会冲突。all 仍按约定访问未来空间。

正常删除清理 schema、空间行及授权；终态操作默认保留168小时，浏览器超过24小时不重放未知写意图。空 selected 拒绝全部空间，不等于 all。签 Key 结果未知先核对列表，不透明重签。

整个 WorkerPoller 执行（含最终状态和重试写入）以及生命周期迁移都有持久准入。取消原生任务只改变队列状态，不证明旧执行者结束；删除须等它真正停止。异常/未知准入不按 TTL 清空。准入失败导致原生任务保持 processing 时，应按稳定 Worker ID 定向重启和原生恢复；清理未知记录前须证明旧写入者已停止，详见运维手册。

首版不支持原生 Webhook 配置/投递；部署将显式拒绝配置，不能承诺未携带空间代次的原生 webhook 任务可安全执行。

首版也固定 `HINDSIGHT_API_LLM_TRACE_ENABLED=false`、`HINDSIGHT_API_AUDIT_LOG_ENABLED=false`。原生 LLMTrace/Audit 使用独立后台 INSERT，未绑定工作空间完整执行期限，可能在旧空间删除后向同名新 schema 晚写；本期先明确关闭，避免给出虚假的代次隔离承诺。**LLM trace 原生缺省为 true，漏传 false 也会被启动配置校验拒绝；渲染器自动写入两项 false。** 已有 Bank 或默认模板启用 `audit_log_enabled` 也会被拒绝，内外调用均不能重新开启。

这不关闭 `ctxdb_meta.audit_events` 管理审计。UI 原生“LLM调用正文/原生审计”页面不产生新记录；JSON stdout/stderr、metrics 和 OpenTelemetry 仍可用于运行诊断，收集及分享时遵守运维手册的数据和凭据脱敏要求。原生诊断记录恢复开放需要先补齐异步写入的代次/生命周期保护。

本地功能证据与四类复核见[优化清单](contextdb-optimization-status.md)。模型连通、模型质量、中英文检索、容量、插件灾备/HA 分别验收，不能互相替代。

UI 的 build-ui 成功后写入源码/依赖锁与实际 standalone 包的指纹；托管 UI 启动强制比对，源码变化、产物缺失或部分旧文件混入均拒绝。API/Worker 托管启动也执行来源和插件预检。客户 SQL 账号不获服务 schema 读写权限，在线跨 schema DDL 不绕过服务；数据库所有者任意并发 DDL 不在隔离保证范围内。
