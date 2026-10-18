# ContextDB 首发优化版：部署、升级与使用

2026-10-16。对应分支 contextdb/release-hardening-20261016-182619，内部元数据3、管理 API v1。原8890/9998体验服务尚未升级，不能拿旧服务验证新合同。

[设计](contextdb-release-design.md) · [逐接口 curl](contextdb-optimized-curl-guide.md) · [OpenAPI](contextdb-control-plane.openapi.yaml)。节点 Agent 负责实例部署/启停/升级；工作空间、成员、Key 在 UI 管理。没有 HTTP 创建实例接口。

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
createdb --encoding=UTF8 --template=template0 contextdb_release
export HINDSIGHT_API_DATABASE_URL='postgresql://服务账号:URL编码密码@PG地址:5432/contextdb_release'
psql -X "$HINDSIGHT_API_DATABASE_URL" -v ON_ERROR_STOP=1 \
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

本期中英文路线沿用现有 PGroonga 资料；插件崩溃恢复、备份/复制/切换另行验收。本地模拟模型与内嵌 PG 测试不证明中文质量或生产灾备通过。btree_gin 不是分词器。

```bash
# 中英文路线执行，英文 native 跳过。
psql -X "$HINDSIGHT_API_DATABASE_URL" -v ON_ERROR_STOP=1 \
 -c 'CREATE EXTENSION IF NOT EXISTS pgroonga;' \
 -c "SELECT * FROM pgroonga_tokenize('中文检索 English');" \
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

首次创建 api.env，连接串来自上一步环境。先补齐自己的模型设置；同一部署重启不得改实例/租户 ID。下例 x 模式拒绝覆盖已有配置。

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
 'HINDSIGHT_API_WORKER_ENABLED': 'true',
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

首次 init 前可在 ui.env 设置 HINDSIGHT_CP_ACCESS_KEY 自定义密码；否则随机生成。初始化后以 ui-secrets.json 为持久秘密来源，不再用启动环境重生。

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

init：只读预检 → 保存三个秘密文件 → migrate 建表/导入管理员 HMAC，全程不依赖 API。秘密文件0600、目录0700，原值不覆盖；已初始化但缺文件时拒绝重新生成，要求恢复备份。

| 文件 | 内容及使用方 |
| --- | --- |
| api.env | PG、模型、实例绑定及扩展；API/Worker |
| admin-key.json | key_id、secret，可有 sha256 交付校验；离线导入/恢复 |
| api-secrets.json | pepper，HMAC 密钥，数据库不存；API/Worker |
| ui.env | UI 开关、API URL、监听地址/端口 |
| ui-secrets.json | UI password、后台 Admin Key；仅 UI 服务端 |

运行时不配置 ADMIN_KEY_SHA256。同一账号复用 HINDSIGHT_API_DATABASE_URL；仅离线 DDL 账号不同才选填 CONTEXTDB_BOOTSTRAP_DATABASE_URL，并核对同一目标数据库。API/Worker 启动不继承离线覆盖或 UI 秘密。

## 4. 启停与重启

以下前台命令交给已有节点 Agent/systemd/容器监督器。默认 API 内嵌 Worker，不另起 worker。独立模式设 WORKER_ENABLED=false，并配置 Worker 自身端口，仍共享 PG、pepper、模型和扩展。

```bash
# 终端/监督器一，前台 API（默认内嵌 Worker）
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

## 5. 首发旧结构升级与管理员恢复

本次不自动修改旧体验库。升级前备份数据库及完整私密目录，停该实例全部写入者，以原元数据所有者执行。支持已知1→2→3、2→3；保留 ID、原业务摘要、审计、原生记忆和 pepper，旧管理员导入 PG。旧版的 ADMIN_KEY_SHA256 仅用于离线核对原管理员秘密。

先把已有 Admin Secret、pepper、UI密码按上述 JSON 模型保存到目录；不为旧实例调用 prepare 补生秘密。

```bash
set -a
source "$CONTEXTDB_DEPLOY_DIR/api.env"
# 旧结构升级时由原配置加载已有校验值：
# export CONTEXTDB_ADMIN_KEY_SHA256='原来的64位SHA256'
set +a
"$PY" -m hindsight_ext_contextdb migrate --directory "$CONTEXTDB_DEPLOY_DIR" \
 --admin-key-file "$CONTEXTDB_DEPLOY_DIR/admin-key.json"
```

定制 catalog、绑定不符、规范化重名/保留名冲突拒绝且回滚，不改版本号强行通过。旧 deleted 残留只登记安全清理任务，API 启动后由原生命周期执行器回收；未知准入/外部依赖仍阻止清理。

管理员明文遗失时，数据库所有者可显式离线轮换，保留原 pepper。生成新文件、更新 PG，再备份并更新 admin-key.json 与 ui-secrets.json 的明文，启动 UI。命令不覆盖现有秘密文件。

```bash
"$PY" -m hindsight_ext_contextdb generate-admin-key --output "$CONTEXTDB_DEPLOY_DIR/admin-key-next.json"
"$PY" -m hindsight_ext_contextdb rotate-admin-key --directory "$CONTEXTDB_DEPLOY_DIR" \
 --admin-key-file "$CONTEXTDB_DEPLOY_DIR/admin-key-next.json"
```

只更新 PG 而忘记 UI 会导致 UI 拒绝启动。pepper 遗失不能通过轮换 Admin Key 恢复业务 Key，需原配置或重新签发。修改 UI 密码应更新 ui-secrets.json 并重启 UI；无需改 PG/API，旧会话失效。

## 6. 使用与验收

按 curl 手册创建两个空间/用户和逐空间 Key，验证原生 REST/MCP、管理员访问、业务 Key 管理拒绝、停用/吊销及同名重建。UI 登录仅用 password；页面展示名称，原生 bank_id=workspace_id。

GET 详情按名称，DELETE/授权按 UUID。正常删除清理 schema、空间行及授权；终态操作默认保留168小时，浏览器超过24小时不重放未知写意图。空 selected 拒绝全部空间，不等于 all。签 Key 结果未知先核对列表，不透明重签。

本地功能证据与四类复核见优化清单/验收报告。模型连通、模型质量、中英文检索、容量、插件灾备/HA 分别验收，不能互相替代。

UI 的 build-ui 成功后写入源码/依赖锁与实际 standalone 包的指纹；托管 UI 启动强制比对，源码变化、产物缺失或部分旧文件混入均拒绝。API/Worker 托管启动也执行来源和插件预检。客户 SQL 账号不获服务 schema 读写权限，在线跨 schema DDL 不绕过服务；数据库所有者任意并发 DDL 不在隔离保证范围内。

旧结构兼容清理的恢复边界：旧 deleted 墓碑的自动清理若三次失败，保持 deleted 和原版本，不通过普通 DELETE 将它改为 deleting，避免与同名新空间冲突。数据库所有者须在停止该实例写入、确认具体依赖/执行者故障解除后离线重排原清理任务；不清空准入、不直接强制 DROP。此边界仅用于历史残留，正常新版空间的 failed 删除可按原 Idempotency-Key 明确重试。
