# ContextDB 独享实例服务

基于 Hindsight 增加实例内的工作空间、用户和 API Key 管理，继续使用原生记忆 REST/MCP 与内置 Worker。它是服务端 Python 扩展，不是 PostgreSQL 扩展，也不提供新的记忆算法。当前 ContextBase 产品以托管服务交付，客户接入已有服务即可。

| 你要完成的任务 | 从这里开始 |
| --- | --- |
| 第一次部署插件并让 Agent 使用 | 按下面的[阅读顺序](#reading-order)完成部署、管理配置和业务验证 |
| 应用或 Agent 连接已有服务 | [业务接入](#business-quickstart)：端点、业务 Key、bank_id 与客户端 |
| 管理员创建空间、用户和 Key | [管理员操作](#admin-quickstart)：UI 登录及交付顺序 |
| 运营者部署或更新实例 | [部署总览](docs/deployment.md)：选择宿主进程或 Docker，准备、配置、初始化与验证 |
| 贡献者理解设计、检视或开发 | [设计与开发](#development)：唯一设计、扩展点、契约与测试 |

<a id="reading-order"></a>

## 第一次使用：按什么顺序读

如果你要把 `contextdb-service` 部署起来给自己的 Agent 使用，按下面四步走。你可以同时承担部署者和管理员，无需先判断自己属于哪类读者。

| 顺序 | 阅读与操作 | 完成后应得到什么 |
| --- | --- | --- |
| 1 | 阅读本页下方的[支持范围与版本](#支持范围与版本)及三种凭据说明 | 知道插件提供什么，区分 UI 密码、Admin Key 和业务 Key |
| 2 | 先读[部署总览](docs/deployment.md)，选择[宿主进程](docs/deployment-native.md)或[Docker](docs/deployment-docker.md)，按所选指南做到健康和身份检查 | API 和管理 UI 可访问，实例身份检查通过；此时还不算业务验证成功 |
| 3 | 回到本页[管理员操作](#admin-quickstart)，登录 UI，创建空间、用户和业务 Key | 得到测试空间的 bank_id、对外端点和有读写权限的业务 Key |
| 4 | 继续读[业务接入](#business-quickstart)，选择一种客户端，写入事实并召回 | 确认业务身份和模型调用可用，完成首次使用 |

完成这四步即可开始使用，不必继续顺读接口参考、检视记录和历史资料。之后需要启停或更新时再看[对应部署方式和维护规则](docs/deployment.md#8-停止重启与版本更新)，想了解原理或参与开发时再读[设计与开发](#development)。

如果服务已经由别人部署好：管理员从第 3 步开始；已经拿到端点、业务 Key 和 bank_id 的应用使用者直接从第 4 步开始。

**English:** This server extension adds instance users, workspace-scoped API keys and schema isolation. Hosted customers use the [Coding Agents npm client](../../hindsight-integrations/coding-agents/README.public.md) or the existing SDKs. Operators use the [deployment guide](docs/deployment.md); contributors start with the [architecture](../../docs/contextdb-management/DESIGN.md#overview). `ContextBase` is the product name, `contextdb-service` the extension directory, `hindsight-ext-contextdb-service` the Python project name, and `hindsight_ext_contextdb` the import module. These names do not imply a standalone PyPI installation path.

## 支持范围与版本

本页及部署指南对应同一 checkout 的 API、扩展和 `contextbase-control-plane`，包括 Bank REST 管理工作空间的行为；不能把社区上游镜像或较早团队版本当作匹配产物。完整版本关系与能力边界见[唯一 DESIGN](../../docs/contextdb-management/DESIGN.md#overview)。历史 PR、基线与验收记录是开发证据，不是首次使用前置知识。

一个实例使用一个 PG 数据库；Workspace 与 Bank 一对一，每空间独立 schema。用户与空间同属实例，权限配置在 Key 上；不同用户获授权访问同一空间时共享内容。对象关系见[设计 1.2](../../docs/contextdb-management/DESIGN.md#12-工作空间用户与-key)。

| 凭据 | 使用者与用途 |
| --- | --- |
| UI 密码 | 管理员登录管理 UI，不用于 API 调用 |
| Admin Key | UI 服务端和受控运维管理实例，不交给业务应用 |
| 业务 Key | 应用/Agent 按授权访问 REST/MCP，不能登录管理 UI |

凭据持久化与恢复规则见[设计 2.2](../../docs/contextdb-management/DESIGN.md#22-三种凭据及保存位置)。

<a id="business-quickstart"></a>

## 业务接入：已有服务的客户

向服务提供者取得 API Endpoint、独立的 MCP Endpoint（使用 MCP 时）、业务 Key 和已授权的 `bank_id`。业务 Key 不会自动创建空间；只读 Key 可 Recall，但首次写入需要读写授权。无需准备 PG、读取 Admin Key 或部署 UI。

- **Coding Agents**：按[客户安装指南](../../hindsight-integrations/coding-agents/README.public.md)使用 `npx @huaweicloud/contextbase-coding-agents@latest`，配置服务端点、业务 token 和 bank_id；安装后重启宿主 Agent。正式复现可固定具体版本。
- **Python / Node.js**：使用提供者交付的 SDK 包，分别见 [Python](../../hindsight-clients/python/README.md)、[TypeScript](../../hindsight-clients/typescript/README.md)。这些 SDK 不会安装服务端或自动建 Bank。
- **直接 REST / MCP**：连接与授权见[设计第 4 章](../../docs/contextdb-management/DESIGN.md#business)。MCP 地址由部署方明确提供，不从 REST 地址猜测；使用业务 Bearer Key 及相应 bank_id。

首次验证按“写入一条可识别的事实 → 确认写入处理完成 → Recall 查询该事实”的顺序。Python SDK 的同步 Retain 示例默认等待写入处理；使用 `retain_async=True` 或 REST `async:true` 时，保存返回的 operation_id，使用同一业务 Key 调用 `GET /v1/default/banks/{bank_id}/operations/{operation_id}`，确认响应 `status` 为 `completed` 后再查询。为等待设置上限；任务失败或等待超时先诊断，不当作已完成，也不无限等待。开发者可参考[现有异步系统用例](tests/system/test_100_contextdb_service.py)，业务用户无需阅读测试代码。

观察与知识页可能稍后生成，初始知识树为空合法；Reflect 和知识页属于后续使用内容。启用本插件不等于客户端自动执行“先查知识，再召回记忆”，这取决于 Agent 集成策略。

<a id="admin-quickstart"></a>

## 管理员操作：从登录到交付业务 Key

1. 从运营方取得管理 UI 地址和 UI 密码并登录。业务成员没有个人 UI 登录账号。
2. 在工作空间管理页创建空间，填写名称和可选描述，等待成功并确认可用；选择器中也有创建入口。
3. 在“用户管理”创建用户，展开目标用户创建 Key，选择空间范围及只读/读写权限。
4. 在创建结果中保存一次性明文，向应用交付业务 Key、bank_id 和对外端点。以后列表只能看到脱敏值。
5. 使用业务身份按[业务接入](#business-quickstart)验证授权；不要用 Admin Key 代替业务验证。

![管理员工作空间目录：创建后核对名称、描述及可用状态](../../docs/contextdb-management/screenshots/bank-rest-description.png)

图为已有验收示例，空间名称是测试数据；右上角是目录创建入口。它展示创建后的结果，创建表单及用户/Key 操作规则见[设计第 3 章](../../docs/contextdb-management/DESIGN.md#ui)。删除及写入结果未知时的处理见下方 Bank REST 参考，不要自动重放。

<a id="development"></a>

## 设计与开发

- [唯一完整设计](../../docs/contextdb-management/DESIGN.md#overview)：架构、对象关系、权限、生命周期及当前限制；[文档索引](docs/README.md)按任务导航。
- 实现位于 [hindsight_ext_contextdb](hindsight_ext_contextdb/)，四个扩展槽及 ASGI 保护层见设计中的扩展说明。
- [管理 OpenAPI](schemas/contextdb-control-plane.openapi.yaml)和[DDL](hindsight_ext_contextdb/schema.sql)提供机器契约；设计、示例不另行定义接口。
- [测试入口](#测试入口)按 Python、系统、UI 环境执行；[检视记录](../../docs/contextdb-management/CODE-REVIEW.md)与[验收记录](../../docs/contextdb-management/VALIDATION.md)保留各自版本和未验边界。

只安装 Python 模块不等于启用插件。API 必须由 `hindsight_ext_contextdb.asgi:create_app` 启动，配套扩展、离线初始化和匹配 UI；[插件配置与容器加载说明](docs/deployment.md#plugin-configuration)列出四个扩展变量，以及 render、挂载和启动脚本的具体作用。直接运行配置了本扩展的原生 API 命令会拒绝启动。原生应用仍负责内置 Worker 和关闭流程。

以下为接口、维护及测试参考；首次使用请先选择上方任务入口。

## MCP 工具白名单（Issue #47）

管理员设置的 Bank `mcp_enabled_tools` 同时约束 Admin、read 和 read_write Key 的工具发现和直接调用，并与服务端全局白名单、原有操作权限取交集。`null`／未设置继承服务端默认，`[]` 禁止全部工具；白名单不能赋予只读 Key 写权限。业务 Key 的 REST 配置响应仍保持原有空字段投影。

单 Bank 端点按目标空间判断；root 端点发现允许工具的并集，调用时重新按实际目标校验。root `list_banks` 只返回可见且启用该工具的 Bank，`total` 和分页在过滤后计算；单 Bank 端点不提供该工具。工具策略每次从已认证 schema 严格读取，查询失败、缺少 Bank 或策略畸形时拒绝，不将错误解释为未设置白名单。

这条窄适配复用插件 Repository 读取原生 `banks.config`，不通过会隐藏业务字段或吞掉查询故障的公开配置解析路径；只有 typed 工具策略进入 MCP 校验，不向客户返回原始配置。原生代码、表结构、SDK 和 REST 业务权限没有修改。

## Bank REST 管理工作空间（Issue #53）

启用 ContextDB 插件后，空间创建、属性更新和删除统一使用原生 Bank 路径，由插件协调管理元数据与独立 schema。未启用插件时保持社区原生行为；只安装Python包不等于启用插件。完整字段、状态与兼容边界见[设计第8章](../../docs/contextdb-management/DESIGN.md#bank-api-reuse-design)。

- 创建：Admin 调用 `PUT /v1/default/banks/{bank_id}`。UI使用 `If-None-Match: *` 严格创建，任意状态已登记的同名目标返回412；不带条件时，active目标按原生属性更新。成功返回200原生profile。
- 描述：新建时可选 `description`，最多512字符、默认空，保存为管理展示文字，独立于影响模型的mission。active目标的无条件PUT/PATCH显式传description返回400；不传保留原值；有效严格创建遇已登记目标仍412。UI两个创建入口均保留描述输入。
- 更新：Admin `PATCH` 仅更新active对象；不存在返回404，不隐式建空间。沿用原生字段，不新增工作空间编辑协议。
- 删除：先GET管理详情，保存确认时的身份ETag；停止新业务并等待已有请求/后台工作结束后，Admin通过Bank DELETE携原 `If-Match` 删除。缺失条件428、格式错误400、对象或版本不匹配412；成功200原生删除结果。
- 只读管理目录、详情、usage继续使用 `/ext/contextdb/v1/workspaces...`。旧workspace POST/DELETE已移除（API405、旧UI写代理404），不再支持旧写调用方。
- 插件启用时，MCP的 `create_bank`、`update_bank`、`delete_bank` 隐藏且拒绝，包括Admin；内容工具保持既有权限。原生模式不受此策略影响。

以下 Admin REST 示例中，`API_URL` 是运营方提供的 API 地址，`ADMIN_KEY` 是受控运维保存的 Admin Key，不能使用 UI 密码或业务 Key；`WORKSPACE_ETAG` 来自管理员核对过的详情响应。首次交付优先使用上方 UI 流程。不要把真实凭据写入脚本或版本库：

```sh
# 严格创建；响应头X-ContextDB-Workspace-ETag属于本次实际创建的对象。
curl -fsS -D - -X PUT "$API_URL/v1/default/banks/example" \
  -H "Authorization: Bearer $ADMIN_KEY" -H 'Content-Type: application/json' \
  -H 'If-None-Match: *' \
  --data '{"name":"Example","description":"示例工作空间"}'

# 管理详情含description/state/UUID/etag。不要假设Bank profile等于管理详情。
curl -fsS -D - "$API_URL/ext/contextdb/v1/workspaces/example" \
  -H "Authorization: Bearer $ADMIN_KEY"

# 先按前述条件停止业务；WORKSPACE_ETAG为人工确认时保存的完整ETag。
curl -fsS -X DELETE "$API_URL/v1/default/banks/example" \
  -H "Authorization: Bearer $ADMIN_KEY" -H "If-Match: $WORKSPACE_ETAG"
```

Python/TypeScript高层SDK的Admin创建、更新、列表沿用原生调用；高层删除不提供逐请求条件时不能直接使用，应采用支持请求级头的底层SDK或REST。不要改共享SDK的全局headers来临时设置删除条件，也不要自动取得最新条件后重放旧删除。

UI创建先发严格PUT，再GET详情核对本次响应头与UUID/版本/描述；同名新对象或GET失败均显示结果未知，不自动重放。接口503、超时或断连也不能证明写入回滚。

本次不改元数据结构，不需数据迁移或重发UI密码/API Key。升级与回退均应使用匹配的API/UI版本；旧UI调用退役路径会失败。创建/删除中断后的核查及人工清理见[设计8.13节](../../docs/contextdb-management/DESIGN.md#bank-rest-interrupted-cleanup)，不可用改状态代替备份或数据恢复。

## PG 部署辅助脚本

SQL 保留为可执行文件，README 说明用途；当前操作步骤见[同版本部署指南](docs/deployment.md#pg-preparation)。资料仓提供历史背景，不替代本 checkout 的部署依据。

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
npm test --workspace=contextbase-control-plane -- ../hindsight-extensions/contextdb-service/tests/ui
npm run lint --workspace=contextbase-control-plane
```

`tests/python/support`保存合成身份、管理ASGI装配、生命周期double和PG资源owner；`tests/system/support`保存独立部署/客户端/UI进程owner。conftest仅提供pytest fixture包装，故障清理直接测试普通owner。原生词条、原生API和普通系统故事保留宿主位置；原生system conftest与插件系统配置只共用 `hindsight_system_tests.pytest_plugin` 中的模型替身、规则重置及未匹配/格式错误校验；原生服务器、客户端与Bank fixture保留原conftest，不复制测试框架。

生产UI故事需要同源码构建的standalone与ContextDB manifest。正式构建使用 `python -m hindsight_ext_contextdb build-ui --source-root <checkout>`；从system环境调用CLI时显式设置 `PYTHONPATH=<checkout>/hindsight-extensions/contextdb-service`。已有 `CONTEXTDB_UI_SERVER`/`CONTEXTDB_TEST_NODE_BIN`可选择隔离产物和Node。产物和源码一致性只在UI fixture启动前校验一次。普通本地无产物时仍可跳过；独立CI job直接运行112故事，再执行 `python scripts/check_production_ui.py <junit-report.xml>`，要求两个Worker参数项完整通过且零跳过；路径按当前工作目录调整。无需额外开关。

CP的TypeScript配置、ESLint根目录调用、Prettier、knip和CI触发范围均包含插件UI测试；不维护第二个Node项目、Vitest配置或依赖锁。`tests/contracts`的跨语言合同检查需要Node，单独在有Node的CI步骤运行，不属于默认插件Python收集。


### ContextDB Service Extension CI

[工作流](../../.github/workflows/contextdb-ci.yml)在指向main的PR及main push命中相关路径时自动执行，也支持手动运行。按Python、UI、集成三组运行本插件的测试；不修改或接管原有 `test.yml`、`browser-brand-audit.yml` 的检查。

触发范围包括插件目录、共享API/UI、Python与TypeScript SDK、系统fixture、构建脚本/品牌输入、依赖锁/格式配置及本工作流。共享依赖改动触发的仍是插件自身回归。仅改普通文档、其他集成或其他工作流不触发；插件README属于插件目录，仍触发。具体路径以YAML中PR/push两份相同清单为准；手动运行不受路径限制。

路径过滤未触发时，GitHub不会创建这些Job。如果把它们配置为所有PR必需检查，需要结合路径适用范围设置分支规则，避免无关PR等待未创建的检查；本工作流不修改仓库合入规则。


| 步骤 | 范围 |
| --- | --- |
| Python | `tests/python/` 全量，以及插件Ruff、格式和ty检查 |
| UI | 仅 `tests/ui/`，使用宿主Vitest；插件组件和测试的ESLint、格式检查 |
| 生产构建 | 同源码构建UI并生成匹配manifest，供插件系统验收使用 |
| 合同与系统 | `tests/contracts/` 与 `tests/system/` 全量，包含两种Worker及两条生产UI故事 |
| 浏览器 | `tests/browser/key-copy.cjs`，真实Chrome验证API Key复制、焦点/选区及实际粘贴；作为插件套件内的步骤，不单列clipboard Job |

Python与集成组使用Linux Runner；UI组在macOS与Windows分别执行完整插件UI测试，并在同一个Job内执行真实剪贴板步骤。没有独立clipboard Job，两个平台的复制验证均保留。复制组件的Vitest用例与真实浏览器脚本是不同层次的检查，均执行。插件 `.gitattributes` 仅将 `tests/ui/**` 固定为LF，避免Windows检出换行转换导致Prettier误报；不修改全仓库Git配置或放宽格式检查。

复用原pytest、Vitest、SDK、模型替身、临时PG及 `verify_integration.py`。UI测试在SDK构建之前运行；系统故事显式使用模型替身并等待后台完成。JUnit必须非空且无失败、错误或跳过；生产UI另由 `check_production_ui.py` 核对两种Worker完整执行。

本地预检须使用任务自己的临时副本，避免安装依赖或生产构建影响运行中的服务。准备Python `.python-version`、Node 24、uv 0.11.2与Chrome，在该副本根目录执行：

```bash
export CONTEXTDB_CI_ISOLATED=1
for suite in python ui build system browser; do
  bash hindsight-extensions/contextdb-service/scripts/run-ci.sh "$suite" /tmp/contextdb-extension-results
done
```

未提交修改须按允许文件带入临时副本，不要复制部署秘密或其他任务改动。入口清理继承的服务参数、禁用dotenv；独立PG和随机端口由fixture管理并清理。`TZ=UTC`只固定测试环境。完整日志及JUnit由Actions保存；本地结果不能代替远程工作流结果。

独立的 `contextdb-key-copy.yml` 由本插件套件替代，原脚本与场景保留。其他工作流不变：品牌审计继续按其原有路径条件自动触发，原生CI继续执行自己的测试；已有接线造成的重叠不在本次重构。工作流文件不修改仓库Actions允许列表、Secrets或分支保护。


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
