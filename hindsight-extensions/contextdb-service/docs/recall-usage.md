# 召回使用统计运维

统计客户通过REST/MCP直接召回的最终记忆和知识页，记录次数与最大UTC采集时间。设计、权限、数据生命周期及性能边界见[DESIGN第7章](../../../docs/contextdb-management/DESIGN.md#7-记忆与知识召回统计)，接口定义见[OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)。

## 配置与权限

| 配置 | 默认值 | 作用与要求 |
| --- | --- | --- |
| `CONTEXTDB_RECALL_USAGE_ENABLED` | `false` | API插件唯一统计开关，仅接受小写 `true` / `false`；修改后重启API/UI，并刷新已打开页面 |
| 部署intent的 `recall_usage_enabled` | `false` | 严格JSON布尔值；Agent render据此生成api.env，启用时设为 `true`，不是字符串 `"true"` |
| `capabilities.recall_usage` | 由API返回 | UI读取的能力字段，不是可配置变量；未加载插件、缺字段、关闭或读取失败时隐藏统计 |

不增加独立UI统计开关。关闭时停止采集、刷盘、统计GC和知识响应观察，UI不显示字段或刷新按钮，也不请求usage；既有统计保留，重新开启继续累计，不补算关闭期间。统计GET沿用空间及内容读取权限：管理员、获授权的只读/读写业务Key均可读；刷新只重新GET，不要求写权限，不计数或强制刷盘。匿名/无效Key为401，无目标空间读取权限为403；关闭时已授权请求为404 `usage_disabled`。UI仍仅支持管理员登录。

## 已有实例升级

1. 备份数据库、当前API/UI产物、部署配置及秘密文件；停止新业务访问，等待已接受请求、Worker任务和统计刷盘结束，再停止API/Worker/UI。`--offline`不会替操作方完成停服或排空。
2. 使用匹配版本的API和插件。原生schema若需要版本升级，先按该版本部署流程完成；下面的命令只创建/升级插件统计表，不迁移原生内容表或public业务表。
3. 在新版代码仓根目录，用原部署的api.env加载数据库连接与实例身份，再执行：

```bash
# 示例部署目录；替换为原实例的私有目录，保留原配置及秘密文件。
(
  set -eu
  export CONTEXTDB_DEPLOY_DIR='/srv/contextdb'
  set -a
  . "$CONTEXTDB_DEPLOY_DIR/api.env"
  set +a
  export PYTHON_DOTENV_DISABLED=1
  export PYTHONPATH="$PWD/hindsight-extensions/contextdb-service:$PWD/hindsight-api-slim"
  "${CONTEXTDB_PYTHON:-./.venv/bin/python}" -m hindsight_ext_contextdb upgrade-usage --offline \
    --directory "$CONTEXTDB_DEPLOY_DIR" \
    --admin-key-file "$CONTEXTDB_DEPLOY_DIR/admin-key.json"
)
```

`--directory`读取原api-secrets.json中的pepper，不会代替加载api.env；`--admin-key-file`使用既有管理员凭据。不要重新生成实例身份、pepper、UI密码或API Key。

| 升级前状态 | 处理结果 |
| --- | --- |
| 已有工作空间，没有统计表 | 在登记空间schema补建ctxdb_usage_stats；原记忆/知识及管理数据保留 |
| 早期统计表包含workspace_id | 校验主键和全部行的空间身份/Bank后去掉冗余列，保留次数和时间 |
| 已是当前结构 | 可以重复执行，既有统计保持 |
| 身份不匹配、异常主键或空间状态不允许 | 中止并报告；不合并异代数据、不清空统计 |

4. 在原部署配置中启用 `CONTEXTDB_RECALL_USAGE_ENABLED=true`；采用Agent render时同步设置intent的 `recall_usage_enabled: true`，按原部署流程生成配置，复用秘密文件。启动匹配的API/Worker/UI并刷新页面，验证原数据、原凭据、REST/MCP召回及统计展示。

新空间创建时自动provision插件表；既有空间必须显式升级，重复执行init/migrate不等于upgrade-usage。升级不会补算历史召回：现存对象无统计记录时为0/null，启用后开始累计。普通升级不执行reset-usage，后者用于规定的内容恢复场景，会清空统计。

升级按空间分别提交，不保证整实例原子性。中途失败时保持停服，检查原因后重跑；已经完成的空间可重复处理。需要止损时可关闭统计并保留数据；若回退到依赖旧统计表结构的代码，需使用与旧版本匹配的数据库备份，不提供自动降级DDL。

## 内容恢复后的统计重置

仅在单个工作空间 schema 的内容恢复完成后、重新开放业务前执行。
先停止新访问，排空 API/Worker 和统计任务，并停止相关服务；
将下例部署目录和 `BANK_ID` 替换为确认过的原实例与已登记工作空间：

```bash
(
  set -eu
  export CONTEXTDB_DEPLOY_DIR='/srv/contextdb'
  set -a
  . "$CONTEXTDB_DEPLOY_DIR/api.env"
  set +a
  BANK_ID='example'
  export PYTHON_DOTENV_DISABLED=1
  export PYTHONPATH="$PWD/hindsight-extensions/contextdb-service:$PWD/hindsight-api-slim"
  "${CONTEXTDB_PYTHON:-./.venv/bin/python}" -m hindsight_ext_contextdb reset-usage --offline \
    --directory "$CONTEXTDB_DEPLOY_DIR" \
    --admin-key-file "$CONTEXTDB_DEPLOY_DIR/admin-key.json" \
    --bank-id "$BANK_ID"
)
```

命令需在匹配源码的仓库根目录运行，并加载原 `api.env` 的 PG URL 和实例身份。
`--directory` 只加载 pepper 等秘密，不能代替运行配置；
`--offline` 是操作方对停服排空前提的声明，不会自行停服或排空。
重置会清空目标空间的整个统计表，包括恢复带入的其他 Bank 行，保留原生内容。
普通版本升级使用 `upgrade-usage`，不执行统计重置。
恢复完成后验证原数据、原凭据及 REST/MCP，再重新开放业务。
完整数据生命周期与失败边界见[统计设计](../../../docs/contextdb-management/DESIGN.md#7-记忆与知识召回统计)。

## 最小使用示例

前提：统计已启用，目标工作空间已经创建，并有可召回的记忆或知识页。使用有该空间读取权限的Key即可；下例不要求写权限。命令需要Bash、curl和jq，查询内容应替换为实际数据中的主题。

```bash
export API_URL='http://127.0.0.1:8891'  # 替换为自己的服务地址
export BANK_ID='example'                # 已存在的bank_id
export API_KEY='<已有的管理员或业务Key>'

# 直接Recall：最终返回的记忆，每次调用每对象计一次。
RECALL_RESPONSE="$(curl --fail-with-body -sS \
  "$API_URL/v1/default/banks/$BANK_ID/memories/recall" \
  -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
  --data '{"query":"What database does our project use?","types":["world","observation"],"budget":"low","max_tokens":1024}')"
printf '%s\n' "$RECALL_RESPONSE" | jq '.results[] | {id,text}'
MEMORY_ID="$(printf '%s' "$RECALL_RESPONSE" | jq -er '.results[0].id')"

# 仅在上一条成功取得ID后执行。只读GET，不增加次数、不强制刷盘。
curl --fail-with-body -sS -G \
  "$API_URL/ext/contextdb/v1/workspaces/$BANK_ID/usage" \
  -H "Authorization: Bearer $API_KEY" \
  --data-urlencode 'object_type=memory' --data-urlencode "ids=$MEMORY_ID" | jq .
```

返回包含 `bank_id`、`object_type` 和 `items[{object_id,recall_count,last_recalled_at}]`。统计异步落库，第一次GET可能仍为0/null或旧值，稍后重新GET即可，不要为了等统计而重复Recall。最终结果为空时不会产生统计，应先调整查询并确认内容存在。最多100个ID一批，使用重复的 `ids` 参数。

知识页使用同一方式：

```bash
SEARCH_RESPONSE="$(curl --fail-with-body -sS -G \
  "$API_URL/v1/default/banks/$BANK_ID/knowledge-base/search" \
  -H "Authorization: Bearer $API_KEY" --data-urlencode 'q=database' --data-urlencode 'limit=5')"
printf '%s\n' "$SEARCH_RESPONSE" | jq '.results[] | {id,name}'
PAGE_ID="$(printf '%s' "$SEARCH_RESPONSE" | jq -er '.results[0].id')"

# 仅在成功取得页面ID后执行；使用page_id，不使用mental_model_id。
curl --fail-with-body -sS -G \
  "$API_URL/ext/contextdb/v1/workspaces/$BANK_ID/usage" \
  -H "Authorization: Bearer $API_KEY" \
  --data-urlencode 'object_type=knowledge_page' --data-urlencode "ids=$PAGE_ID" | jq .
```

MCP的 `recall` / `search_knowledge_base` 使用同一统计口径，没有新增usage MCP工具；统计查询使用上述REST接口。consolidation、Reflect内部检索和知识页后台生成/刷新均不计入，次数和最后召回时间都保持原值。UI在记忆表格、记忆详情及知识页详情显示统计；知识目录不逐页请求，当前页最多100个记忆一次批量GET。异常退出可丢失尚未提交的内存增量，指标不用于无损计费或审计。

## UI示例与验证依据

- 页面示例：[记忆表格](../../../docs/contextdb-management/screenshots/recall-usage-memory.jpg)、[知识页](../../../docs/contextdb-management/screenshots/recall-usage-knowledge.jpg)。
- 开关示例：[统计开启](../../../docs/contextdb-management/screenshots/recall-usage-enabled.jpg)、[统计关闭](../../../docs/contextdb-management/screenshots/recall-usage-disabled.jpg)。
- [验证入口](../../../docs/contextdb-management/VALIDATION.md)说明当前测试方式；系统故事需要覆盖直接召回计数与内部检索排除。截图为页面示例，不代表当前提交重新执行了浏览器验收。
