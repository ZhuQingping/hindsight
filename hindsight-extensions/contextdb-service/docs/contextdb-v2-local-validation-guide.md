# ContextDB v2 本地验证与演示手册

> **历史快照，不适用于当前首发版本。** 下文保留当时的配置、接口、表结构和测试环境用于对照，不应照此部署或验证当前代码。当前以[首发设计](contextdb-release-design.md)、[部署合同](contextdb-deployment-contract.md)和[API验证手册](contextdb-optimized-curl-guide.md)为准；开发期旧库不自动升级。

日期：2026-10-15。面向开发者手工验证，不是自动执行脚本。配套 [v2 设计](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/member-apikey-bank-service-design-v2.md)、[部署配置清单](contextdb-v2-deployment-environment.md)。本手册的写入、权限修改和删除步骤尚未在当前体验实例执行；下文“预期”是验收标准。

## 1 当前实例和验证范围

| 项目 | 当前值 |
| --- | --- |
| API | `http://127.0.0.1:8888` |
| UI | `http://localhost:9999`；使用 localhost |
| MCP | `http://127.0.0.1:8888/mcp/` |
| PG | `127.0.0.1:5432`，用户 `zhuqingping` |
| 数据库 | `contextdb_v2_experience_20261015_104834_735ecc` |
| 实例 | `ctxdb-local-v2-experience` |
| MySQL 空间/Bank ID | `ff96608cba797f42d83865a08524d76f` |
| PG 空间/Bank ID | `40de7f2550f2b6d67f39c068487a586b` |

一个工作空间对应一个独立 PG schema 和唯一 Bank，`workspace_id = bank_id`。REST/MCP 客户端只传 Bank ID，不传 schema。用户的空间上限与 Key 的逐空间 scope 求交；同空间记忆共享，不按写入者或 Key 隔离。

验证会创建专用演示用户、Key、唯一文档，以及一个临时第三空间。不要删除现有 MySQL/PG 空间、清空其全部内容，或撤销 UI 当前使用的管理员 Key。步骤失败时停在该步；不要继续提取前一次响应的 ID。

建议演示顺序：准备环境 → 创建用户/Key → 双空间 Retain/Recall → 只读与跨空间拒绝 → UI 切换 → 修改原 Key 权限 → 临时空间创建/删除。完整验收再补 Reflect、异步任务、知识页、MCP、PG 和清理。

## 2 PG 插件和当前生产配置差额

| 用途 | 插件/能力 | 选择 |
| --- | --- | --- |
| 向量语义检索 | `vector`（pgvector） | 当前方案必需，中英文通用 |
| 实体名称模糊匹配 | `pg_trgm` | 建议安装，避免实体匹配降级 |
| 带 Bank 条件的实体复合 GIN | `btree_gin` | 建议安装；它不是中文分词器或全文搜索引擎 |
| 中文、英文混合关键词检索 | `pgroonga` | 当前选用，支持无空格中文检索 |
| 纯英文关键词检索 | PG 内置 `tsvector`、英文配置和 GIN | 不需要另装全文插件，配置 `native`；排名不是严格 BM25 |
| 真正 BM25 的备选 | `pg_search` + 集成的 `jieba` tokenizer | 中文候选；版本、索引语法和效果需独立验证，不与当前 PGroonga 同时作为主后端 |
| SQL 性能监控 | `pg_stat_statements` | 建议生产启用，不参与召回算法 |

当前推荐组合：`vector + pg_trgm + btree_gin + pgroonga + pg_stat_statements`。纯英文可将 PGroonga 换成内置全文，其他项保留。`plpgsql` 是 PG 默认语言，不是要额外选型的检索插件。vectorscale、VectorChord 等是向量后端候选，不要求全部安装。

2026-10-15 只读检查：当前库已安装 vector 0.8.6、pg_trgm 1.6、btree_gin 1.3、pg_stat_statements 1.12、PGroonga 4.1.0；**数据库编码是 SQL_ASCII，preload 为空**。因此当前实例可做基本体验，不能视为完成中英文生产验收。完整验收应在独立 UTF8 库重建实例，不要原地改编码或直接替换当前库。

源码编译安装命令见 [v1 手册第 2.3 节](postgresql-extensions.md)。这些 PG 安装步骤可以复用，v1 成员/Key 管理步骤不能复用。安装文件到 PG prefix 和在目标数据库 `CREATE EXTENSION` 是两个步骤；可迁移扩展放 public，可供其他 workspace schema 使用，但连接角色需相应 USAGE/EXECUTE 权限和正确 search_path。

生产配置另验：

- `pg_stat_statements` 需要 preload、PG 重启及 `compute_query_id=auto/on`。[PG 官方说明](https://www.postgresql.org/docs/18/pgstatstatements.html)
- PGroonga 物理复制/恢复需按主备分别配置 WAL resource manager；主库启用对应参数，启用该方案的备库不启用 crash-safer。[官方配置](https://pgroonga.github.io/reference/modules/pgroonga-wal-resource-manager.html)
- 官方仍将 crash-safer 标为实验功能；不能把安装或开启它当成生产恢复保证。上线前实测崩溃、备份恢复、复制和故障切换。[官方状态](https://pgroonga.github.io/reference/modules/pgroonga-crash-safer.html)

本文不执行上述重启或恢复配置。

## 3 一次性准备测试会话

在新的终端进入 bash，后续命令保持在同一会话执行。需要 curl、jq、Python 和本机 psql。

```bash
bash
umask 077
export RUN=$(cat /Users/zhuqingping/Work/Database/Context/test/hindsight_test/contextdb-v2-experience/latest-run.txt)
export CASE="$RUN/manual-validation/$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$CASE"
python3 - <<'PY'
import json, os, shlex
from pathlib import Path
r, c = Path(os.environ['RUN']), Path(os.environ['CASE'])
runtime = json.loads((r/'runtime.json').read_text())
config = json.loads((r/'deployment.json').read_text())
bootstrap = json.loads((r/'instance-bootstrap.json').read_text())
ui = json.loads((r/'ui-settings.json').read_text())
spaces = {w['name']: w for w in json.loads((r/'workspaces.json').read_text())}
assert config['CONTEXTDB_INSTANCE_ID'] == 'ctxdb-local-v2-experience'
assert runtime['database'] == 'contextdb_v2_experience_20261015_104834_735ecc'
values = {
 'API': runtime['api_url'], 'UI': runtime['ui_url'],
 'REPO': runtime['repo'], 'DB_URL': config['HINDSIGHT_API_DATABASE_URL'],
 'INSTANCE': config['CONTEXTDB_INSTANCE_ID'], 'INSTANCE_NAME': bootstrap['instance']['name'],
 'ACTOR': 'local-console-admin', 'ADMIN_KEY': ui['HINDSIGHT_CP_DATAPLANE_API_KEY'],
 'CONTROL_KEY': json.loads((r/'control-key.json').read_text())['secret'],
 'ADMIN_USER': bootstrap['admin_user']['user_id'], 'UI_PASSWORD': ui['HINDSIGHT_CP_ACCESS_KEY'],
 'WA': spaces['MySQL']['workspace_id'], 'WB': spaces['PG']['workspace_id'],
 'SA': spaces['MySQL']['schema_name'], 'SB': spaces['PG']['schema_name'],
 'DEMO': c.name, 'PG_BIN': '/Users/zhuqingping/Work/Database/PG/pg_18_4/bin',
}
(c/'session.sh').write_text(''.join('export '+k+'='+shlex.quote(v)+'\n' for k,v in values.items()))
(c/'session.sh').chmod(0o600)
print('会话已保存；没有输出凭据。')
PY
source "$CASE/session.sh"
export PY="$REPO/.venv/bin/python"
export MG=/ext/contextdb/v1
export BA="/v1/default/banks/$WA" BB="/v1/default/banks/$WB"
```

`session.sh` 和测试响应含凭据，只保留在上述私有运行目录。不要开启 `set -x`、不要将完整响应贴到公开仓库。测试请求包装器如下，屏幕输出会隐藏 secret。

```bash
cat > "$CASE/helpers.sh" <<'SH'
save_var() {
  [[ "$1" =~ ^[A-Z][A-Z0-9_]*$ ]] || return 1
  printf 'export %s=%q\n' "$1" "$2" >> "$CASE/session.sh"
  export "$1=$2"
}
req() {
  local expect="$1" method="$2" path="$3" body="$4" code
  shift 4
  local args=(-sS --max-time 300 -X "$method" -D "$CASE/last.headers" -o "$CASE/last.json" -w '%{http_code}')
  if [ -n "$body" ]; then args+=(-H 'Content-Type: application/json' --data-binary "$body"); fi
  code=$(curl "${args[@]}" "$@" "$API$path") || return 1
  printf '%s %s -> HTTP %s（预期 %s）\n' "$method" "$path" "$code" "$expect"
  [ -s "$CASE/last.json" ] || printf '{}\n' > "$CASE/last.json"
  cp "$CASE/last.json" "$CASE/response-$(date +%s)-$RANDOM.json"
  jq 'walk(if type == "object" then del(.secret,.digest,.api_key) else . end)' "$CASE/last.json" 2>/dev/null || printf '非 JSON 响应，见 last.json\n'
  [ "$code" = "$expect" ]
}
ctl() { local e="$1" m="$2" p="$3" b="$4"; shift 4; req "$e" "$m" "$MG$p" "$b" -H "X-ContextDB-Control-Key: $CONTROL_KEY" -H "X-ContextDB-Actor-Subject: $ACTOR" "$@"; }
adm() { local e="$1" m="$2" p="$3" b="$4"; shift 4; req "$e" "$m" "$MG$p" "$b" -H "Authorization: Bearer $ADMIN_KEY" "$@"; }
biz() { local k="$1" e="$2" m="$3" p="$4" b="$5"; shift 5; req "$e" "$m" "$p" "$b" -H "Authorization: Bearer $k" "$@"; }
wait_management() {
  local op="$1" i state
  for i in $(seq 1 180); do
    ctl 200 GET "/operations/$op" '' >/dev/null || return 1
    state=$(jq -r .state "$CASE/last.json")
    case "$state" in succeeded) echo '管理任务完成'; return 0;; failed) jq . "$CASE/last.json"; return 1;; esac
    sleep 2
  done
  echo '管理任务未完成，检查 error_code，不能按成功处理'; return 1
}
wait_native() {
  local key="$1" bank="$2" op="$3" i state
  for i in $(seq 1 180); do
    biz "$key" 200 GET "/v1/default/banks/$bank/operations/$op" '' >/dev/null || return 1
    state=$(jq -r .status "$CASE/last.json")
    case "$state" in completed) echo '原生任务完成'; return 0;; failed|cancelled|not_found) jq . "$CASE/last.json"; return 1;; esac
    sleep 2
  done
  echo '原生任务未完成，检查 Worker/模型日志'; return 1
}
SH
source "$CASE/helpers.sh"
```

POST 用户/Key 不是可随意重试的幂等签发操作。遇到断网或超时，先查列表确认结果；已签发 Key 的明文不能重新查询，只能撤销并另签。

## 4 前置检查与实例初始化

```bash
req 200 GET /health/ready ''
ctl 200 GET "/instances/$INSTANCE" ''
adm 200 GET /admin/session ''
ctl 200 GET '/workspaces?limit=100&offset=0' ''
ctl 200 GET "/workspaces/$WA" ''
ctl 200 GET "/workspaces/$WB" ''
biz "$ADMIN_KEY" 200 GET '/v1/default/banks?limit=100&offset=0' ''

BODY=$(jq -nc --arg i "$INSTANCE" --arg n "$INSTANCE_NAME" '{instance_id:$i,name:$n}')
ctl 201 POST /instances "$BODY"
jq -e '.admin_key == null' "$CASE/last.json"
ctl 409 POST /instances "$(jq -nc --arg i "$INSTANCE" '{instance_id:$i,name:"Different name"}')"
ctl 403 POST /instances '{"instance_id":"another-instance","name":"Wrong instance"}'
```

预期两个空间 active，Bank 列表含两个相同 ID。重复初始化不重新生成或展示管理员 secret；首次初始化新库才返回唯一管理员和 all Key。当前已有实例，不能把重复初始化返回 null 当成故障。

模型配置已经改用 MaaS，详见配置清单。当前 bge-m3 的维度为 1024，不发送 dimensions 参数。Retain/Reflect 需要真实 LLM；Recall 可能调用 embedding 和 rerank。HTTP 成功还需核对事实，不能只凭服务 ready 判定模型完整链路通过。

## 5 创建用户及不同权限 Key

```bash
adm 201 POST /users "$(jq -nc --arg n "demo-multi-$DEMO" --arg a "$WA" --arg b "$WB" '{name:$n,workspace_access:"selected",workspace_ids:[$a,$b]}')"
save_var USER_MULTI "$(jq -er .user_id "$CASE/last.json")"
adm 201 POST /users "$(jq -nc --arg n "demo-pg-$DEMO" --arg b "$WB" '{name:$n,workspace_ids:[$b]}')"
save_var USER_B "$(jq -er .user_id "$CASE/last.json")"
adm 201 POST /users "$(jq -nc --arg n "demo-all-$DEMO" '{name:$n,workspace_access:"all"}')"
save_var USER_ALL "$(jq -er .user_id "$CASE/last.json")"
adm 200 GET '/users?limit=100&offset=0' ''
adm 200 GET "/users?workspace_id=$WA&limit=100" ''
adm 200 GET "/users/$USER_MULTI" ''

MULTI_BODY=$(jq -nc --arg a "$WA" --arg b "$WB" '{name:"MySQL读写-PG只读",grants:[{workspace_id:$a,scopes:["memory.read","memory.write"]},{workspace_id:$b,scopes:["memory.read"]}]}')
adm 201 POST "/users/$USER_MULTI/keys" "$MULTI_BODY"
save_var KEY_MULTI "$(jq -er .secret "$CASE/last.json")"
save_var KEY_MULTI_ID "$(jq -er .key_id "$CASE/last.json")"
adm 201 POST "/users/$USER_MULTI/keys" "$(jq -nc --arg a "$WA" '{name:"MySQL只读",grants:[{workspace_id:$a,scopes:["memory.read"]}]}')"
save_var KEY_RO "$(jq -er .secret "$CASE/last.json")"
save_var KEY_RO_ID "$(jq -er .key_id "$CASE/last.json")"
adm 201 POST "/users/$USER_MULTI/keys" "$(jq -nc --arg a "$WA" '{name:"MySQL思考",grants:[{workspace_id:$a,scopes:["memory.read","reflect"]}]}')"
save_var KEY_REFLECT "$(jq -er .secret "$CASE/last.json")"
adm 201 POST "/users/$USER_MULTI/keys" "$(jq -nc --arg a "$WA" '{name:"MySQL知识只读",grants:[{workspace_id:$a,scopes:["knowledge.read"]}]}')"
save_var KEY_KB "$(jq -er .secret "$CASE/last.json")"
adm 201 POST "/users/$USER_B/keys" "$(jq -nc --arg b "$WB" '{name:"PG读写",grants:[{workspace_id:$b,scopes:["memory.read","memory.write"]}]}')"
save_var KEY_B "$(jq -er .secret "$CASE/last.json")"
adm 201 POST "/users/$USER_MULTI/keys" '{"name":"零授权","grants":[]}'
save_var KEY_EMPTY "$(jq -er .secret "$CASE/last.json")"
adm 201 POST "/users/$USER_ALL/keys" '{"name":"当前空间快照"}'
save_var KEY_SNAPSHOT "$(jq -er .secret "$CASE/last.json")"
save_var KEY_SNAPSHOT_ID "$(jq -er .key_id "$CASE/last.json")"
adm 200 GET "/users/$USER_MULTI/keys?limit=100" ''
jq -e 'all(.items[]; (has("secret")|not))' "$CASE/last.json"
```

**显式 `grants:[]` 为零授权。省略 grants 会快照用户当前可访问的 active/frozen 空间，赋予四种 scope；普通 selected Key 不自动包含未来新增空间。** 正式业务建议始终显式提供 grants，避免默认权限大于预期。

| Key | MySQL | PG | 用户/Key 管理 | 后续新增空间 |
| --- | --- | --- | --- | --- |
| ADMIN_KEY | 全部业务权限 | 全部业务权限 | 可以 | 自动可见 |
| KEY_MULTI | 读、写 | 只读 | 拒绝 | 拒绝 |
| KEY_RO | 只读 | 拒绝 | 拒绝 | 拒绝 |
| KEY_REFLECT | 读、Reflect | 拒绝 | 拒绝 | 拒绝 |
| KEY_KB | 知识页只读 | 拒绝 | 拒绝 | 拒绝 |
| KEY_B | 拒绝 | 读、写 | 拒绝 | 拒绝 |
| KEY_EMPTY | 拒绝 | 拒绝 | 拒绝 | 拒绝 |
| KEY_SNAPSHOT | 当前空间四种 scope | 当前空间四种 scope | 拒绝 | 拒绝 |

非法授权与认证边界：

```bash
adm 400 POST "/users/$USER_MULTI/keys" "$(jq -nc --arg a "$WA" '{name:"缺read",grants:[{workspace_id:$a,scopes:["memory.write"]}]}')"
adm 400 POST "/users/$USER_B/keys" "$(jq -nc --arg a "$WA" '{name:"超用户上限",grants:[{workspace_id:$a,scopes:["memory.read"]}]}')"
adm 403 POST "/users/$USER_MULTI/keys" '{"name":"成员不能all","access_mode":"all"}'
req 403 GET "$MG/users" '' -H "Authorization: Bearer $KEY_MULTI"
req 401 GET "$MG/workspaces" '' -H "Authorization: Bearer $ADMIN_KEY"
req 401 GET "$MG/admin/session" '' -H "Authorization: Bearer $CONTROL_KEY"
req 401 GET "$MG/workspaces" ''
biz "$KEY_EMPTY" 403 GET "$BA/documents?limit=1" ''
```

Console 管实例/工作空间，使用服务 Key 和可信 actor；管理员 all Key 管用户/Key 并访问业务；成员 Key 只访问授权业务，不能自建子 Key。UI 密码不是上述任一种 API 凭据。

## 6 双空间 Retain、Recall、Reflect

### 6.1 同步写入不同事实

```bash
save_var DOC_A "mysql-$DEMO"
save_var DOC_B "pg-$DEMO"
A_BODY=$(jq -nc --arg d "$DOC_A" --arg tag "$DEMO" '{items:[{document_id:$d,content:"蓝鲸项目 BlueWhale 的负责人是林澈，计划于2027年2月18日发布。发布前必须完成备份恢复演练。The BlueWhale project uses PostgreSQL 18.4 and requires a backup restore rehearsal before release.",tags:[$tag],context:"人工演示"}],async:false}')
B_BODY=$(jq -nc --arg d "$DOC_B" --arg tag "$DEMO" '{items:[{document_id:$d,content:"赤狐项目 RedFox 的负责人是沈舟，计划于2027年3月26日发布。该项目使用 MySQL 8.4。The RedFox owner is Shen Zhou.",tags:[$tag],context:"人工演示"}],async:false}')
biz "$KEY_MULTI" 200 POST "$BA/memories" "$A_BODY"
jq -e '.success == true and .async == false' "$CASE/last.json"
biz "$KEY_B" 200 POST "$BB/memories" "$B_BODY"
biz "$KEY_RO" 200 GET "$BA/documents/$DOC_A" ''
biz "$KEY_RO" 200 GET "$BA/documents/$DOC_A/chunks" ''
biz "$KEY_RO" 200 GET "$BA/memories/list?document_id=$DOC_A&limit=100" ''
biz "$KEY_MULTI" 200 GET "$BA/stats" ''
```

预期文档、分块、提取事实存在。事实数量、措辞和顺序不固定；另一把只读 Key 能读到同空间共享内容。

### 6.2 中文、英文与跨空间隔离

```bash
save_var RECALL '{"query":"蓝鲸项目由谁负责，何时发布，上线前要做什么？","budget":"mid","max_tokens":2048,"trace":true}'
biz "$KEY_MULTI" 200 POST "$BA/memories/recall" "$RECALL"
cp "$CASE/last.json" "$CASE/recall-mysql-cn.json"
jq -e '.results | length > 0' "$CASE/last.json"
biz "$KEY_RO" 200 POST "$BA/memories/recall" '{"query":"Who owns BlueWhale and what database check is required before release?","budget":"mid"}'
biz "$KEY_MULTI" 200 POST "$BB/memories/recall" '{"query":"赤狐项目的负责人和发布日期是什么？","budget":"mid"}'
biz "$KEY_MULTI" 200 POST "$BB/memories/recall" "$RECALL"
cp "$CASE/last.json" "$CASE/recall-pg-cross-check.json"
biz "$KEY_B" 403 POST "$BA/memories/recall" "$RECALL"
biz "$KEY_RO" 403 POST "$BB/memories/recall" "$RECALL"
biz "$KEY_B" 403 GET "$BA/documents/$DOC_A" ''
```

人工检查：MySQL 回答能支撑林澈、2027-02-18、备份恢复；PG 回答能支撑沈舟、2027-03-26。PG 查询蓝鲸可以返回弱相关事实，但不能返回 MySQL 的蓝鲸/林澈事实。同一 URL 路径规则下，目标 Bank ID 决定空间；有效 Key 的授权仍需允许它。

### 6.3 只读拒绝与 Reflect

```bash
DENIED=$(jq -nc --arg d "denied-$DEMO" '{items:[{content:"这条内容不能落库",document_id:$d}],async:false}')
biz "$KEY_RO" 403 POST "$BA/memories" "$DENIED"
biz "$KEY_MULTI" 403 POST "$BB/memories" "$DENIED"
biz "$ADMIN_KEY" 404 GET "$BA/documents/denied-$DEMO" ''
biz "$ADMIN_KEY" 404 GET "$BB/documents/denied-$DEMO" ''
biz "$KEY_RO" 403 POST "$BA/reflect" '{"query":"蓝鲸上线前应检查什么？"}'
biz "$KEY_MULTI" 403 POST "$BA/reflect" '{"query":"蓝鲸上线前应检查什么？"}'
biz "$KEY_REFLECT" 200 POST "$BA/reflect" '{"query":"根据已有记忆说明蓝鲸项目的负责人、发布日期和发布前检查，没有依据的内容请明确说明。","budget":"mid","max_tokens":2048,"include":{"facts":{}}}'
cp "$CASE/last.json" "$CASE/reflect.json"
jq -e '.text | length > 0' "$CASE/last.json"
```

Reflect 应有事实依据且不编造完成状态。`memory.write` 不自动包含 `reflect`。拒绝写入通过文档 404 和后文 SQL 再确认，不能只看错误码。

### 6.4 异步 Retain 与后台任务

```bash
save_var DOC_ASYNC "async-$DEMO"
biz "$KEY_MULTI" 200 POST "$BA/memories" "$(jq -nc --arg d "$DOC_ASYNC" '{items:[{content:"蓝鲸项目的备份恢复演练由顾宁执行。",document_id:$d}],async:true}')"
save_var RETAIN_OP "$(jq -er .operation_id "$CASE/last.json")"
wait_native "$KEY_MULTI" "$WA" "$RETAIN_OP"
biz "$KEY_RO" 200 GET "$BA/documents/$DOC_ASYNC" ''
biz "$KEY_B" 403 GET "$BA/operations/$RETAIN_OP" ''
biz "$KEY_MULTI" 200 GET "$BA/operations?limit=100" ''
```

原生任务看 `status=completed`，管理任务看 `state=succeeded`。同步写入和父任务完成后仍可能有 consolidation/知识刷新子任务，验收时检查任务列表及失败项。

### 6.5 文档替换和删除

```bash
save_var DOC_REPLACE "replace-$DEMO"
biz "$KEY_MULTI" 200 POST "$BA/memories" "$(jq -nc --arg d "$DOC_REPLACE" '{items:[{content:"ReplacementProbe 的负责人是陆川。",document_id:$d}],async:false}')"
biz "$KEY_MULTI" 200 POST "$BA/memories" "$(jq -nc --arg d "$DOC_REPLACE" '{items:[{content:"ReplacementProbe 的负责人更新为许晴。",document_id:$d}],async:false}')"
biz "$KEY_RO" 200 GET "$BA/documents/$DOC_REPLACE" ''
biz "$KEY_RO" 403 DELETE "$BA/documents/$DOC_REPLACE" ''
biz "$KEY_MULTI" 200 DELETE "$BA/documents/$DOC_REPLACE" ''
biz "$KEY_RO" 404 GET "$BA/documents/$DOC_REPLACE" ''
```

同 document_id 默认替换，原文和事实应反映更新。派生观察可能异步重建，不能用即时 Recall 一句话消失作为唯一删除标准。

## 7 知识页和文件上传

知识页属于独立 scope，不能用它绕过记忆读取授权：

```bash
biz "$KEY_MULTI" 201 POST "$BA/knowledge-base/pages" '{"name":"BlueWhale 发布检查","source_query":"总结 BlueWhale 项目的负责人、发布日期和备份恢复要求","trigger":{"mode":"full","refresh_after_consolidation":true}}'
save_var PAGE_ID "$(jq -er .page_id "$CASE/last.json")"
save_var MODEL_ID "$(jq -er .mental_model_id "$CASE/last.json")"
PAGE_OP=$(jq -er .operation_id "$CASE/last.json")
wait_native "$KEY_MULTI" "$WA" "$PAGE_OP"
biz "$KEY_KB" 200 GET "$BA/knowledge-base/tree" ''
biz "$KEY_KB" 200 GET "$BA/knowledge-base/pages/$PAGE_ID" ''
biz "$KEY_KB" 200 GET "$BA/knowledge-base/search?q=BlueWhale" ''
biz "$KEY_KB" 200 GET "$BA/knowledge-base/export" ''
biz "$KEY_KB" 403 POST "$BA/memories/recall" "$RECALL"
biz "$KEY_KB" 403 GET "$BA/mental-models/$MODEL_ID" ''
biz "$KEY_KB" 403 POST "$BA/knowledge-base/folders" '{"name":"无权创建"}'
biz "$KEY_B" 403 GET "$BA/knowledge-base/pages/$PAGE_ID" ''
```

预期生成后页面有正文且与记忆一致。可再 Retain 新事实，检查后台刷新任务及页面更新，不能只看创建成功。

可选文件转换验证：

```bash
save_var DOC_FILE "file-$DEMO"
printf 'FileProbe 的负责人是程远。\n' > "$CASE/probe.txt"
FILE_REQUEST=$(jq -nc --arg d "$DOC_FILE" '{files_metadata:[{document_id:$d}]}')
biz "$KEY_MULTI" 200 POST "$BA/files/retain" '' -F "files=@$CASE/probe.txt;type=text/plain" -F "request=$FILE_REQUEST"
cp "$CASE/last.json" "$CASE/file-operations.json"
for OP in $(jq -er '.operation_ids[]' "$CASE/file-operations.json"); do wait_native "$KEY_MULTI" "$WA" "$OP" || break; done
biz "$KEY_RO" 200 GET "$BA/documents/$DOC_FILE" ''
biz "$KEY_RO" 403 POST "$BA/files/retain" '' -F "files=@$CASE/probe.txt;type=text/plain" -F "request=$FILE_REQUEST"
```

上传接口使用 multipart。检查父子任务完成、文档和 Recall，不把上传受理当成提取成功。PDF/DOCX 可用无敏感文件另测格式转换。

## 8 原 Key 修改授权、用户停用与 Key 撤销

### 8.1 权限变更不换 secret

```bash
adm 200 GET "/users/$USER_MULTI/keys?limit=100" ''
V=$(jq -er --arg k "$KEY_MULTI_ID" '.items[]|select(.key_id==$k)|.version' "$CASE/last.json")
SHRINK=$(jq -nc --arg a "$WA" '{grants:[{workspace_id:$a,scopes:["memory.read"]}]}')
adm 200 PATCH "/users/$USER_MULTI/keys/$KEY_MULTI_ID" "$SHRINK" -H "If-Match: \"$V\""
adm 412 PATCH "/users/$USER_MULTI/keys/$KEY_MULTI_ID" "$SHRINK" -H "If-Match: \"$V\""
adm 400 PATCH "/users/$USER_MULTI/keys/$KEY_MULTI_ID" "$SHRINK"
biz "$KEY_MULTI" 403 POST "$BA/memories" "$A_BODY"
biz "$KEY_MULTI" 403 POST "$BB/memories/recall" "$RECALL"
biz "$KEY_MULTI" 200 GET "$BA/documents/$DOC_A" ''
adm 200 GET "/users/$USER_MULTI/keys?limit=100" ''
V=$(jq -er --arg k "$KEY_MULTI_ID" '.items[]|select(.key_id==$k)|.version' "$CASE/last.json")
adm 200 PATCH "/users/$USER_MULTI/keys/$KEY_MULTI_ID" "$(jq -c '{grants}' <<< "$MULTI_BODY")" -H "If-Match: \"$V\""
```

预期同一 secret 下一请求使用新权限；冲突返回 412，缺少带引号的版本返回 400。MCP 已建会话也应逐消息检查，见第 10 节。

### 8.2 用户空间上限、停用与恢复

```bash
adm 200 GET "/users/$USER_MULTI" ''
V=$(jq -er .version "$CASE/last.json")
adm 200 PATCH "/users/$USER_MULTI" "$(jq -nc --arg a "$WA" '{workspace_ids:[$a]}')" -H "If-Match: \"$V\""
biz "$KEY_MULTI" 403 POST "$BB/memories/recall" "$RECALL"
biz "$KEY_B" 200 GET "$BB/documents/$DOC_B" ''
adm 200 GET "/users/$USER_MULTI" ''
V=$(jq -er .version "$CASE/last.json")
adm 200 PATCH "/users/$USER_MULTI" "$(jq -nc --arg a "$WA" --arg b "$WB" '{workspace_ids:[$a,$b]}')" -H "If-Match: \"$V\""
V=$(jq -er .version "$CASE/last.json")
adm 200 PATCH "/users/$USER_MULTI" '{"status":"disabled"}' -H "If-Match: \"$V\""
biz "$KEY_MULTI" 401 GET "$BA/documents/$DOC_A" ''
biz "$KEY_RO" 401 GET "$BA/documents/$DOC_A" ''
biz "$KEY_B" 200 GET "$BB/documents/$DOC_B" ''
adm 200 GET "/users/$USER_MULTI" ''
V=$(jq -er .version "$CASE/last.json")
adm 200 PATCH "/users/$USER_MULTI" '{"status":"active"}' -H "If-Match: \"$V\""
biz "$KEY_MULTI" 200 GET "$BA/documents/$DOC_A" ''
```

用户缩空间后，即使 Key 历史 grants 仍列出 PG，也不能访问。停用阻断该用户所有 Key 的新请求；其他用户不受影响。恢复只恢复未撤销、未过期的 Key，不撤回已经受理的后台任务。

### 8.3 撤销一把 Key、到期和用户删除

```bash
adm 204 DELETE "/users/$USER_MULTI/keys/$KEY_RO_ID" ''
biz "$KEY_RO" 401 GET "$BA/documents/$DOC_A" ''
biz "$KEY_MULTI" 200 GET "$BA/documents/$DOC_A" ''
EXPIRES=$(python3 -c 'from datetime import datetime,timedelta,timezone; print((datetime.now(timezone.utc)+timedelta(seconds=45)).isoformat())')
adm 201 POST "/users/$USER_MULTI/keys" "$(jq -nc --arg a "$WA" --arg e "$EXPIRES" '{name:"短期验证",expires_at:$e,grants:[{workspace_id:$a,scopes:["memory.read"]}]}')"
save_var KEY_SHORT "$(jq -er .secret "$CASE/last.json")"
biz "$KEY_SHORT" 200 GET "$BA/documents?limit=1" ''
sleep 50
biz "$KEY_SHORT" 401 GET "$BA/documents?limit=1" ''
```

第 13 节删除演示用户后，名下 Key 应全部拒绝；删除用户是软删除，不能再恢复。管理员身份受保护，不测试删除正在支撑 UI 的管理员。

## 9 创建、删除临时工作空间

### 9.1 创建与幂等

```bash
save_var WC_NAME "demo-space-$DEMO"
save_var CREATE_IDEM "create-$DEMO"
WC_BODY=$(jq -nc --arg n "$WC_NAME" '{name:$n,description:"可删除的临时演示空间"}')
ctl 202 POST /workspaces "$WC_BODY" -H "Idempotency-Key: $CREATE_IDEM"
save_var WC "$(jq -er .workspace_id "$CASE/last.json")"
save_var CREATE_OP "$(jq -er .operation_id "$CASE/last.json")"
wait_management "$CREATE_OP"
ctl 200 GET "/workspaces/$WC" ''
save_var SC "$(jq -er .schema_name "$CASE/last.json")"
jq -e '.state == "active"' "$CASE/last.json"
ctl 202 POST /workspaces "$WC_BODY" -H "Idempotency-Key: $CREATE_IDEM"
jq -e --arg op "$CREATE_OP" '.operation_id == $op' "$CASE/last.json"
ctl 409 POST /workspaces '{"name":"Different body"}' -H "Idempotency-Key: $CREATE_IDEM"
ctl 409 POST /workspaces "$WC_BODY" -H "Idempotency-Key: duplicate-$DEMO"
biz "$ADMIN_KEY" 200 GET /v1/default/banks ''
biz "$KEY_SNAPSHOT" 403 GET "/v1/default/banks/$WC/documents?limit=1" ''
biz "$KEY_MULTI" 403 GET "/v1/default/banks/$WC/documents?limit=1" ''
```

预期 admin/all 和 UI 自动可见新空间；USER_ALL 的旧 selected Key 仍不能访问它。这是“用户上限 all”和“Key access_mode all”的区别。名称按 NFKC、trim、casefold 规范化唯一；本期不支持空间改名。

给原快照 Key 增加新空间，不换 secret：

```bash
adm 200 GET "/users/$USER_ALL/keys?limit=100" ''
V=$(jq -er --arg k "$KEY_SNAPSHOT_ID" '.items[]|select(.key_id==$k)|.version' "$CASE/last.json")
GRANTS=$(jq -c --arg k "$KEY_SNAPSHOT_ID" --arg c "$WC" '{grants:((.items[]|select(.key_id==$k)|.grants)+[{workspace_id:$c,scopes:["memory.read"]}])}' "$CASE/last.json")
adm 200 PATCH "/users/$USER_ALL/keys/$KEY_SNAPSHOT_ID" "$GRANTS" -H "If-Match: \"$V\""
biz "$KEY_SNAPSHOT" 200 GET "/v1/default/banks/$WC/documents?limit=1" ''
```

### 9.2 业务 API 禁止绕过空间生命周期

```bash
biz "$KEY_MULTI" 403 DELETE "$BA" ''
biz "$ADMIN_KEY" 403 DELETE "$BA" ''
biz "$ADMIN_KEY" 403 POST /v1/default/banks/00000000000000000000000000000000 '{"name":"不能直接建Bank"}'
biz "$KEY_MULTI" 403 POST "$BA/clone?target_bank_id=00000000000000000000000000000000" ''
biz "$ADMIN_KEY" 403 POST "$BA/aliases" '{"alias":"forbidden-demo-alias"}'
```

创建、删除、clone、Bank 恢复/导入、改名/alias 写入不向业务 Key 开放；普通文档写入和文件导入仍按 scope 允许。管理员可以清空内容，但此次不执行现有空间的整库清空。

### 9.3 仅删除临时空间

```bash
delete_demo_workspace() {
  ctl 200 GET "/workspaces/$WC" '' || return 1
  jq -e --arg n "$WC_NAME" '.name == $n' "$CASE/last.json" || return 1
  [ "$WC" != "$WA" ] && [ "$WC" != "$WB" ] || return 1
  save_var DELETE_IDEM "delete-$DEMO"
  ctl 202 DELETE "/workspaces/$WC" '' -H "Idempotency-Key: $DELETE_IDEM" || return 1
  save_var DELETE_OP "$(jq -er .operation_id "$CASE/last.json")"
  wait_management "$DELETE_OP"
}
delete_demo_workspace
ctl 404 GET "/workspaces/$WC" ''
biz "$ADMIN_KEY" 403 POST "/v1/default/banks/$WC/memories/recall" '{"query":"已删除空间"}'
ctl 202 DELETE "/workspaces/$WC" '' -H "Idempotency-Key: $DELETE_IDEM"
jq -e --arg op "$DELETE_OP" '.operation_id == $op' "$CASE/last.json"
biz "$ADMIN_KEY" 200 GET /v1/default/banks ''
```

预期 MySQL/PG 仍可用，临时空间不再出现在业务列表。metadata 保留 deleted 墓碑，schema/表保留，Bank 数据被清除；不以 schema 消失作为删除成功条件。同名空间可重新创建，但产生新 ID/schema，旧 Key 的旧 ID 授权不会继承。

删除必须等待请求和任务排空。若出现 interrupted/未知执行者，不删除准入记录、不用 TTL 强行放行，应先确认旧执行者已经停止。

## 10 MCP 基本功能与已建会话撤权

在第 8 节恢复 KEY_MULTI 原授权后执行。当前环境已有 fastmcp/httpx；脚本只保存在测试目录。先测试工具列表、两个 Bank 读取及 PG 写入拒绝，再在同一 MCP 会话中修改权限并立即验证，最后恢复原权限。

```bash
cat > "$CASE/mcp-check.py" <<'PY'
import asyncio, json, os
import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main():
    base, a, b = os.environ['API'], os.environ['WA'], os.environ['WB']
    user, key_id = os.environ['USER_MULTI'], os.environ['KEY_MULTI_ID']
    prefix = '/ext/contextdb/v1/users/' + user + '/keys'
    transport = StreamableHttpTransport(base + '/mcp/', headers={
        'Authorization': 'Bearer ' + os.environ['KEY_MULTI']})
    async with httpx.AsyncClient(base_url=base, headers={
        'Authorization': 'Bearer ' + os.environ['ADMIN_KEY']}) as admin:
        response = await admin.get(prefix, params={'limit': 100})
        response.raise_for_status()
        original = next(k for k in response.json()['items'] if k['key_id'] == key_id)
        changed = False
        try:
            async with Client(transport) as client:
                names = {t.name for t in await client.list_tools()}
                assert 'create_bank' not in names and 'delete_bank' not in names
                listed = await client.call_tool('list_banks', {})
                banks = json.loads(listed.content[0].text)['banks']
                assert {v['bank_id'] for v in banks} == {a, b}
                for bank, query in [(a, '蓝鲸的负责人是谁？'), (b, '赤狐的负责人是谁？')]:
                    result = await client.call_tool('recall', {'bank_id': bank, 'query': query})
                    assert not result.is_error
                    assert json.loads(result.content[0].text)['results']
                    print('Recall:', bank, '成功；事实请结合 REST 结果检查')
                refused = await client.call_tool('retain', {'bank_id': b, 'content': '无权写入'}, raise_on_error=False)
                assert refused.is_error or json.loads(refused.content[0].text).get('status') == 'error'
                response = await admin.patch(prefix + '/' + key_id,
                    headers={'If-Match': '"' + str(original['version']) + '"'},
                    json={'grants': [{'workspace_id': b, 'scopes': ['memory.read']}]})
                response.raise_for_status()
                changed = True
                refused = await client.call_tool('recall', {'bank_id': a, 'query': '撤权后的请求'}, raise_on_error=False)
                assert refused.is_error
                print('同一 MCP 会话下一请求已拒绝被撤权的空间')
        finally:
            if changed:
                response = await admin.get(prefix, params={'limit': 100})
                response.raise_for_status()
                current = next(k for k in response.json()['items'] if k['key_id'] == key_id)
                response = await admin.patch(prefix + '/' + key_id,
                    headers={'If-Match': '"' + str(current['version']) + '"'},
                    json={'grants': original['grants']})
                response.raise_for_status()
                print('已恢复原 Key 授权')

asyncio.run(main())
PY
"$PY" "$CASE/mcp-check.py"
```

补充演示可用 `/mcp/{bank_id}/` 固定空间，或多空间 `/mcp/` 配合 `X-Bank-Id` 默认值；工具参数不能绕过固定空间或 Key 范围。用户停用/Key 撤销后的旧会话下一请求也必须拒绝，可能表现为传输层 401 而非工具内错误，不能把断开后的新会话验证当成旧会话验证。

## 11 UI 验证及术语

访问 `http://localhost:9999`，登录口令从私有 `ui-settings.json` 的 `HINDSIGHT_CP_ACCESS_KEY` 查看。

1. 未登录不能进入管理页面；正确独立口令可登录。用成员 Key 作为口令不能登录。
2. MySQL/PG 都可见；切换后只展示当前空间内容。第 9 节创建临时空间后应自动可见，删除后消失。
3. 文档/记忆页面能看到本次事实；分别执行 Recall、Reflect，核对来源空间。
4. 用户页面展示实例级用户；空间筛选只影响视图，不创建重复用户。测试用户可访问多个空间。
5. Key 创建 secret 只展示一次；关闭后列表不能再次取回明文。能调整选定 Key 的逐空间权限，能撤销普通 Key。
6. 不应出现可实际创建、删除、改名 Bank 的业务入口；Console 负责空间生命周期，服务端也需拒绝绕行。
7. 浏览器不接收后台固定管理员 Key；网络面板中的 UI 请求通过服务端代理和会话认证，不能由浏览器切换固定 Key。

统一对用户显示“工作空间 / Workspace”，包括列表、切换器、空状态、设置、统计和错误提示。`bank_id`、`banks` API 路径、SDK 类型保持原生名称；接口参数展示处可写“工作空间 ID（bank_id）”。“记忆”“知识页”“知识库”是空间中的内容，不统一替换为工作空间。

`Initial administrator` 是 all 权限 API Key：可调用全部空间的 REST/MCP，管理用户/Key，并包含未来空间。它的 all 权限不可修改；管理员可在另一把有效 all Key 存在时撤销它，最后一把撤销返回 409。UI 使用这把 Key 调 API，API 再连接 PG，UI 不直接连 PG。轮换前先替换 UI 服务端 Key 并重启 UI。本次验证不撤销当前固定 Key。

## 12 PG 只读交叉验证

```bash
PGCLIENTENCODING=UTF8 "$PG_BIN/psql" -X "$DB_URL" -v ON_ERROR_STOP=1 \
  -v sa="$SA" -v sb="$SB" -v doca="$DOC_A" -v docb="$DOC_B" <<'SQL'
SHOW server_encoding;
SHOW shared_preload_libraries;
SELECT extname, extversion, extnamespace::regnamespace FROM pg_extension ORDER BY extname;
SELECT * FROM ctxdb_meta.schema_versions;
SELECT workspace_id,name,schema_name,state FROM ctxdb_meta.workspaces ORDER BY created_at;
SELECT user_id,name,role,status,workspace_access,workspace_ids,version FROM ctxdb_meta.users ORDER BY created_at;
SELECT key_id,user_id,name,access_mode,grants,expires_at,revoked_at,version FROM ctxdb_meta.api_keys ORDER BY created_at;
SELECT bank_id FROM :"sa".banks;
SELECT bank_id FROM :"sb".banks;
SELECT bank_id,id AS document_id FROM :"sa".documents WHERE id=:'doca';
SELECT bank_id,id AS document_id FROM :"sb".documents WHERE id=:'docb';
SELECT format_type(a.atttypid,a.atttypmod) AS embedding_type,n.nspname,c.relname
FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE a.attname='embedding' AND c.relname='memory_units' AND n.nspname IN (:'sa',:'sb');
SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname IN (:'sa',:'sb') ORDER BY 1,2,3;
SELECT n.nspname,c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN (:'sa',:'sb') AND NOT i.indisvalid;
SELECT action,state,workspace_id,error_code FROM ctxdb_meta.management_operations ORDER BY created_at DESC LIMIT 20;
SELECT workspace_id,origin,state,count(*) FROM ctxdb_meta.request_admissions GROUP BY 1,2,3;
SELECT action,result,user_id,key_id,workspace_id,actor_subject FROM ctxdb_meta.audit_events ORDER BY event_id DESC LIMIT 30;
SQL
```

预期 metadata 版本 2；两个 schema 各只有对应 Bank；向量类型 `vector(1024)`；索引含 HNSW、实体 trigram、PGroonga。无效索引查询应为空。实体复合 GIN 应含 `bank_id` 和 `gin_trgm_ops`，全文表达式与当前后端一致。只安装扩展不能证明实际索引已经建立，迟装插件也不会重跑旧 Alembic 迁移。

删除临时空间后，可另查其墓碑和仍存在的 schema；其 banks 应为空。管理审计不是完整业务审计。长期 active/interrupted 准入需要排查真实执行者，不能直接删行解锁。

客户 PG 权限单独验证：受限业务角色应无法读写 `ctxdb_meta` 和内核表；真正 PG SUPERUSER、操作系统 root 可以绕过这些限制，不能承诺同数据库内对 root 隐藏元数据。本机当前 zhuqingping 是服务用账号，不能替代客户受限角色验收。

## 13 管理员恢复与清理

可选管理员恢复演示：通过管控创建另一把管理员 all Key，验证后只撤销新 Key，不动当前 UI Key。

```bash
ctl 201 POST "/instances/$INSTANCE/admin-keys" "$(jq -nc --arg n "recovery-demo-$DEMO" '{name:$n}')"
save_var RECOVERY_KEY "$(jq -er .secret "$CASE/last.json")"
save_var RECOVERY_ID "$(jq -er .key_id "$CASE/last.json")"
req 200 GET "$MG/admin/session" '' -H "Authorization: Bearer $RECOVERY_KEY"
adm 204 DELETE "/users/$ADMIN_USER/keys/$RECOVERY_ID" ''
req 401 GET "$MG/admin/session" '' -H "Authorization: Bearer $RECOVERY_KEY"
```

只在演示结束且不再需要其事实时清理自己创建的文档：

```bash
biz "$ADMIN_KEY" 200 DELETE "$BA/documents/$DOC_A" ''
biz "$ADMIN_KEY" 200 DELETE "$BB/documents/$DOC_B" ''
biz "$ADMIN_KEY" 200 DELETE "$BA/documents/$DOC_ASYNC" ''
# 仅执行过文件用例时删除 DOC_FILE；知识页可在 UI 删除本次创建的页。
# biz "$ADMIN_KEY" 200 DELETE "$BA/documents/$DOC_FILE" ''
adm 204 DELETE "/users/$USER_MULTI" ''
adm 404 GET "/users/$USER_MULTI" ''
biz "$KEY_MULTI" 401 GET "$BA/documents?limit=1" ''
adm 204 DELETE "/users/$USER_B" ''
adm 204 DELETE "/users/$USER_ALL" ''
biz "$ADMIN_KEY" 200 GET /v1/default/banks ''
```

临时空间按第 9.3 节删除。没有执行的可选步骤不要盲目清理。保留原 MySQL/PG 空间及其他人的文档；不用 `DROP DATABASE`、`DROP SCHEMA` 或整 Bank 清空代替清理。

## 14 重启、备份和验收记录

重启前保存当前部署配置、pepper、管理员 Key 和数据库备份。用相同配置重新启动 API/UI 后：同一业务 Key 应仍能访问，workspace_id/schema 不变，UI 独立口令仍有效；不重新初始化 secret。实例已使用独立 worktree，不要误从旧主分支启动 v1 服务。

逻辑备份示例，保存到私有测试目录：

```bash
"$PG_BIN/pg_dump" --format=custom --no-owner --no-acl --file="$CASE/contextdb.dump" "$DB_URL"
"$PG_BIN/pg_restore" --list "$CASE/contextdb.dump" > "$CASE/backup-list.txt"
```

备份应覆盖 public 扩展依赖、ctxdb_meta 和全部 workspace schema。恢复必须使用独立库验证，不能覆盖当前体验库；恢复后还需相同 pepper/配置和可加载的插件二进制。逻辑备份成功不等于 PGroonga 物理复制或崩溃恢复通过。

| 验收项 | 记录实际结果 |
| --- | --- |
| UTF8 生产目标库、插件实际索引、preload/恢复配置 | 待验证；当前库 SQL_ASCII/preload 空 |
| 实例初始化幂等、一次返回管理员 Key | 待填 |
| 用户查询/创建/修改/删除和管理员保护 | 待填 |
| Key 创建/列表/修改/撤销、到期、用户上限 | 待填 |
| 同 Key MySQL 读写/PG 只读；不同 Key 独立 | 待填 |
| 中文/英文 Retain/Recall 和跨空间事实隔离 | 待填 |
| Reflect 事实依据、知识页 scope、文件处理 | 待填 |
| Worker 异步任务及 schema 正确 | 待填 |
| 旧 MCP 会话下一消息撤权 | 待填 |
| UI 登录、全部空间、用户/Key 管理 | 待填 |
| 空间创建/删除/幂等；业务入口拒绝绕行 | 待填 |
| PG 数据、索引、审计与受限角色 | 待填 |
| 服务重启、备份恢复、并发和崩溃恢复 | 待填 |

新增管理合同共 18 个操作，本手册覆盖 POST/GET instance、POST admin-keys、GET admin/session、POST/GET workspaces、GET/DELETE workspace、GET operation、GET/POST users、GET/PATCH/DELETE user、GET/POST keys、PATCH/DELETE key。API 前缀仍为 `/ext/contextdb/v1`，它不代表使用 v1 metadata。

常见排查：401 查凭据/撤销/到期/用户状态；403 查空间与 scope；400 查输入和 If-Match；412 重新读版本；202/异步 true 需轮询完成；500/任务失败查 API/模型/PG 日志。只修改环境文件不会影响已启动进程。本手册不将历史模拟测试结果当成本机真实 MaaS 完整验收。
