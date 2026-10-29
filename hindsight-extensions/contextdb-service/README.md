# ContextDB 独享实例服务

基于 Hindsight v1.0.0，增加工作空间、用户和 API Key 管理。记忆操作继续使用原生 REST/MCP 与内置 Worker。

**评审从[文档入口](docs/README.md)开始。** 当前团队完整设计见[DESIGN](../../docs/contextdb-management/DESIGN.md)，保留原始完整叙述并直接更新团队适配；资料仓维护来源背景和运维资料，版本关系见设计第1.4节。

实现位于 `hindsight_ext_contextdb/`，部署材料位于 `deployment/`，命令位于 `scripts/`，自研回归测试物理集中在 `tests/{python,system,ui}`；UI与系统故事继续复用宿主工程的运行环境，不复制SDK或服务桩。当前团队边界和TODO以同版完整设计为准。

管理接口的机器可读定义保留在[schemas/](schemas/contextdb-control-plane.openapi.yaml)，由代码生成并由测试校验；变更接口时更新它。

扩展专用配置示例见 [contextdb.env.example](deployment/contextdb.env.example)；运行配置由部署脚本根据 `deployment/intent.example.json` 生成。

API 由扩展自己的 `hindsight_ext_contextdb.asgi:create_app` 启动，外层准入保护同时覆盖原生 REST/MCP；部署脚本已使用此入口。直接运行原生 API 命令且配置本扩展时会拒绝启动，避免漏装保护层。原生应用仍负责初始化、内置 Worker 和关闭流程。

## PG 部署辅助脚本

SQL 保留为可执行文件，README 说明用途；完整操作步骤见资料仓的[PG 准备与权限边界](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/deployment/contextdb-service-integration-guide.md#pg-preparation)。不在 README 复制 SQL 正文。

| 脚本 | 用途与执行时机 |
| --- | --- |
| [prepare-pg.sql](deployment/prepare-pg.sql) | 首次部署前，由管控/PG 管理员创建专用服务账号、UTF8 数据库，并在目标库启用 vector、pg_trgm、btree_gin。要求数据库端已有插件安装文件和足够的管理权限；遇到同名角色或库即停止，不用于接管已有库。它不创建 ContextDB 管理表。 |
| [pg-role-boundary.sql](deployment/pg-role-boundary.sql) | 客户需要普通 SQL 账号直连 PG 时，由 PG 管理员针对 ctxdb_meta 和每个工作空间 schema 配置权限，防止该账号直接读写服务数据。角色、数据库和目标 schema 必须预先存在；新增空间也需按部署策略配置。 |

两个脚本均不由 API 启动或 `service.sh init` 自动执行。后者的权限示例不负责 API 工作空间授权，也无法限制真正的 PG 超级用户、服务对象所有者或底层主机管理员。仅通过 API 使用服务、未开放客户 SQL 账号时，无须执行该权限示例。

## 测试入口

在仓库根目录准备依赖后，按运行环境分别执行；不要把三类测试放进同一个pytest环境。

```sh
# 插件元数据/策略/部署测试；默认只收集 tests/python
cd hindsight-extensions/contextdb-service
uv run pytest -v
# 或明确指定，旧的 pytest tests/ 命令请改为这个入口
uv run pytest tests/python -v

# 系统故事物理在插件，仍使用原system-test依赖、SDK、server和模型桩
cd ../../hindsight-system-tests
uv run --frozen --group contextdb pytest -c ../hindsight-extensions/contextdb-service/pytest-system.ini ../hindsight-extensions/contextdb-service/tests/system -v

# 扩展专属UI测试由原Control Plane的同一Vitest配置收集
cd ..
npm test --workspace=hindsight-control-plane
npm run lint --workspace=hindsight-control-plane
```

`tests/python/support`保存合成身份、管理ASGI装配、生命周期double和PG资源owner；`tests/system/support`保存独立部署/客户端/UI进程owner。conftest仅提供pytest fixture包装，故障清理直接测试普通owner。原生词条、原生API和普通系统故事保留宿主位置；原生system conftest与插件系统配置只共用 `hindsight_system_tests.pytest_plugin` 中的模型替身、规则重置及未匹配/格式错误校验；原生服务器、客户端与Bank fixture保留原conftest，不复制测试框架。

生产UI故事需要同源码构建的standalone与ContextDB manifest。正式构建使用 `python -m hindsight_ext_contextdb build-ui --source-root <checkout>`；从system环境调用CLI时显式设置 `PYTHONPATH=<checkout>/hindsight-extensions/contextdb-service`。已有 `CONTEXTDB_UI_SERVER`/`CONTEXTDB_TEST_NODE_BIN`可选择隔离产物和Node。产物和源码一致性只在UI fixture启动前校验一次。普通本地无产物时仍可跳过；独立CI job直接运行112故事，再执行 `python scripts/check_production_ui.py <junit-report.xml>`，要求两个Worker参数项完整通过且零跳过；路径按当前工作目录调整。无需额外开关。

CP的TypeScript配置、ESLint根目录调用、Prettier、knip和CI触发范围均包含插件UI测试；不维护第二个Node项目、Vitest配置或依赖锁。`tests/contracts`的跨语言合同检查需要Node，单独在有Node的CI步骤运行，不属于默认插件Python收集。


### Bank配置读取的字段权限

`GET /v1/default/banks/{bank_id}/config`保留正常读取能力。自研ASGI传输层在原生认证/操作校验完成后，把`overrides`投影到已过滤`config`的可见字段集合，使用宿主公开响应模型校验JSON；GET、PATCH和DELETE配置响应使用同一路径。当前业务Key得到200和两个空对象，Admin保留允许配置的读写/重置；普通MCP `get_bank`读取基本信息不变。只处理配置响应，原生引擎、方法和存储均不修改，不重放权限钩子或新增授权查询。

实现位于插件`transport.py::_bank_config_json`和既有纯ASGI中间件；复用任务诊断的定点JSON缓冲机制，不引入BaseHTTPMiddleware、不缓冲Retain/MCP/SSE。回归位于插件`tests/python/test_transport.py`及`tests/system/test_114_contextdb_diagnostic_credentials.py::test_business_bank_config_hides_overrides_without_rejecting_reads`，覆盖空/部分字段、分块/压缩/错误响应、单次认证查询及双Worker真实SDK/MCP。

## 初始化及管理体验修复（2026-10-21阶段记录）

`service.sh init`持久化秘密文件、初始化/核验ctxdb_meta六表、管理员及四个原生共享维护函数，不再迁移public业务表。创建空间时才初始化ctxdb_ws_<bank_id>。public继续保存vector等扩展对象，不删除public schema，也不自动清理旧开发库；更新脚本不得重新执行ContextDB的public全量业务迁移。纯原生过渡部署说明不受此规则替代。

管理元数据的表、字段、索引、约束与函数Description统一英文；audit_events.key_id是目标Key，control_key_id是操作者Admin Key。只更新COMMENT，元数据版本、DDL结构、权限和业务数据不变。

chunk详情由扩展transport使用原生codec解析Bank并进入现有授权上下文；原生接口与SDK不变。管理UI补齐GET错误状态、空间q搜索及UUID草稿保持、当前语言日期与管理导航；Secret保留到用户明确关闭，离页/卸载/切换用户仍清理，不持久化或自动重签，复制反馈防迟到。

团队ProductRuntime、productFetch、proxy、Host/Origin及磁盘会话不变。公共配置使用CONTEXTBASE优先、HINDSIGHT兼容的既有合同，显式空值也具有优先级。目标旧HEAD遗漏的49d727664配置读取/健康探测修复在本轮补齐；SEC-01已有投影不重复实现。逐项适配、实际测试和未验收范围统一见[完整设计](../../docs/contextdb-management/DESIGN.md)、[检视记录](../../docs/contextdb-management/CODE-REVIEW.md)与[验证记录](../../docs/contextdb-management/VALIDATION.md)。


## MCP与共享维护函数（2026-10-27）

MCP适配器先认证当前消息的目标空间，将其登记schema用于原生工具筛选、审计配置读取和执行；root工具目录按每个可见空间的原生配置与权限筛选后求并集。没有跨请求身份缓存，未改变业务Key配置字段投影。

`service.sh init`复用原生revision `c8b4e2a71f95`安装四个共享维护函数，不补建public业务表。函数默认位于public，也可使用事先创建的配置schema；离线CLI与API/Worker保持CONTEXTBASE优先、HINDSIGHT兼容及显式空值规则，不加载父`.env`。已声明外部接管的函数不覆盖，须满足原生签名、返回列及EXECUTE权限。已有部署在维护窗口保留配置/秘密文件重复init即可补齐；本轮未操作现有部署。完整部署与错误边界见[设计§5.5.4](../../docs/contextdb-management/DESIGN.md)，实际测试与限制见[验证第17章](../../docs/contextdb-management/VALIDATION.md)。

## 召回使用统计（Issue #38）

统计客户通过REST/MCP直接召回的最终记忆和知识页，记录次数与最大UTC采集时间。设计、权限、数据生命周期及性能边界见[DESIGN第7章](../../docs/contextdb-management/DESIGN.md#7-记忆与知识召回统计)，接口定义见[OpenAPI](schemas/contextdb-control-plane.openapi.yaml)。

### 配置与权限

| 配置 | 默认值 | 作用与要求 |
| --- | --- | --- |
| `CONTEXTDB_RECALL_USAGE_ENABLED` | `false` | API插件唯一统计开关，仅接受小写 `true` / `false`；修改后重启API/UI，并刷新已打开页面 |
| 部署intent的 `recall_usage_enabled` | `false` | 严格JSON布尔值；Agent render据此生成api.env，启用时设为 `true`，不是字符串 `"true"` |
| `capabilities.recall_usage` | 由API返回 | UI读取的能力字段，不是可配置变量；未加载插件、缺字段、关闭或读取失败时隐藏统计 |

不增加独立UI统计开关。关闭时停止采集、刷盘、统计GC和知识响应观察，UI不显示字段或刷新按钮，也不请求usage；既有统计保留，重新开启继续累计，不补算关闭期间。统计GET沿用空间及内容读取权限：管理员、获授权的只读/读写业务Key均可读；刷新只重新GET，不要求写权限，不计数或强制刷盘。匿名/无效Key为401，无目标空间读取权限为403；关闭时已授权请求为404 `usage_disabled`。UI仍仅支持管理员登录。

### 已有实例升级

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

### 最小使用示例

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

### UI示例与验证依据

- [记忆表格与知识页截图](../../docs/contextdb-management/VALIDATION.md#202-chrome实际验证)。
- [统计开启与关闭截图](../../docs/contextdb-management/VALIDATION.md#222-关键合同与chrome)。
- [完整特性回归](../../docs/contextdb-management/VALIDATION.md)；内部检索排除补证见同文第27章。截图为对应验收版本记录，不代表本次文档发布重新部署。
