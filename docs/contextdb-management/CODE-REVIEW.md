# ContextDB 团队分支集成代码检视

## 1. 检视结论与证据入口

本文件是实现者按项目 `.claude/skills/code-review/SKILL.md` 完成的自检及专家阅读指南，不代表独立专家已批准。最终测试状态见 [VALIDATION.md](VALIDATION.md)；评审必须同时查看设计约束与验证范围，不能仅依据冲突已消除或本地提交存在批准合入。

本次集成范围为工作空间、用户、API Key扩展，以及直接需要的UI、部署、测试和CI适配；不包含无关运行时重构、现有部署/数据库操作或远端发布。开发步骤不再单独维护为PLAN文档。

固定团队基线：`57bbfd2d39685091ce65a4742e43c6efbcb4c78e`。初始功能来源：`ddf5c360001f1db46f925b1822803ac9bff1119e`；本轮最新来源：`a05b80885883b36f879abdb2ce8a9c8f63b0922c`，增量适配经amend纳入本次单一功能提交。当前集成差异用以下命令审阅（命令在本分支执行）：

```sh
git log --oneline 57bbfd2d39685091ce65a4742e43c6efbcb4c78e..HEAD
git status --short
git diff --stat 57bbfd2d39685091ce65a4742e43c6efbcb4c78e
git ls-files --others --exclude-standard
git diff 57bbfd2d39685091ce65a4742e43c6efbcb4c78e -- hindsight-api-slim/hindsight_api
```

本次以amend提交后的完整差异为检视对象；如检视者另有工作树改动，新文件仍应按status/ls-files读取。最后一条预期没有输出：本次管理能力不修改原生 Python 运行代码；团队既有改动保留。专家不应以官方 v1.0.0 为差异基线而将团队已有改造归入本特性。

## 2. 必须先读的设计

统一以 [DESIGN.md](DESIGN.md) 为完整设计依据：第1章对象/架构，第2章部署/密码/配置，第3～4章用户操作与业务权限，第5.1节认证及SEC-01、第5.2节生命周期、第5.3节PG、第5.4节API，第6章边界/Q&A。本文件仅记录代码走读和检视发现；所有读者审阅同一份设计，不另设角色版本。

## 3. 逐层阅读顺序

| 顺序 | 文件/目录 | 重点 |
| --- | --- | --- |
| 1 | `hindsight-extensions/contextdb-service/hindsight_ext_contextdb/models.py`、`schema.sql` | 六张元数据表、对象身份、版本、Key授权输入与显式权限 |
| 2 | 同目录 `security.py`、`repository.py`、`authorization.py` | 全Key的HMAC、PG角色、用户启停、selected/all、空间UUID绑定、请求内复用边界 |
| 3 | `asgi.py`、`transport.py`、`tenant.py`、`validator.py`、`mcp.py` | 正确启动入口、REST/MCP当前消息身份、schema路由、Worker任务边界、诊断脱敏 |
| 4 | `http.py`、`lifecycle.py`、`migrations.py`、`bootstrap.py` | 管理API、短事务、同步创建删除、离线初始化、唯一管理员保护 |
| 5 | `hindsight-control-plane/src/proxy.ts`、`src/lib/contextdb.ts`、`src/app/api/contextdb/[...path]/route.ts` | 团队会话叠加Admin检查、同源/Host、固定上游、白名单、ETag、无自动重放 |
| 6 | `src/app/api/auth/login/route.ts`、`src/instrumentation.ts` | 先校验密码和Admin身份再签发会话、启动时配置及后台身份验证 |
| 7 | `src/lib/contextdb-api.ts`、`src/lib/contextdb-mode.tsx`、`src/components/contextdb/` | 产品身份请求头、一次性Key展示、分页/搜索、结果未知提示、统一创建对话框 |
| 8 | 布局、登录页、Bank选择器/详情/配置/总览及 `src/i18n/*` | 团队品牌/主题/语言回退保留、禁用原生生命周期入口、管理导航 |
| 9 | 扩展 `deployment.py`、`launch.py`、`ui_probe.py`、`deployment/` | 秘密隔离、别名优先级、会话存储权限与持久化、Host安全探测 |
| 10 | 扩展测试、插件`tests/system/test_100_*`～`test_118_*`、UI测试与CI | 核对下列风险有实际行为覆盖，确认生产UI故事不会在CI静默跳过 |

目录均相对仓库根；以上同目录简称均指 `hindsight_ext_contextdb/`。

## 4. 11个冲突的解决决策

| 冲突路径（UI路径省略前缀 `hindsight-control-plane/src/`） | 决策 |
| --- | --- |
| `app/[locale]/banks/[bankId]/page.tsx` | 保留团队翻译状态；ContextDB模式隐藏原生克隆入口 |
| `app/[locale]/layout.tsx` | 团队ProductRuntime/metadata/dataset叠加ContextDBModeProvider；本地系统字体 |
| `app/[locale]/login/page.tsx` | 团队登录布局/productFetch叠加独立UI密码说明 |
| `app/api/auth/login/route.ts` | 保留配置、Host/Origin和磁盘会话；验证当前Admin身份后签发 |
| `app/globals.css` | 保留团队主题色与语义token；使用本地字体变量 |
| `components/bank-selector.tsx` | 保留团队资源导航与productFetch，合入用户入口和统一空间创建对话框 |
| `i18n/request.ts` | 合成团队语言回退、品牌替换与管理词条 |
| `instrumentation.ts` | 团队产品配置校验加ContextDB后台身份启动检查 |
| `lib/i18n/api-errors.ts` | 团队locale解析与回退保留，合入管理模式兼容 |
| `middleware.ts`（修改/删除） | 删除旧文件，将所需策略接入团队 `proxy.ts` |
| `hindsight-system-tests/hindsight_system_tests/server.py` | 保留团队外部专用PG覆盖和环境隔离，合入扩展入口/解释器注入与失败清理 |

自动合并的 `banks-overview.tsx`、`bank-config-view.tsx`、Vitest、CI和OpenAPI仍单独审阅；自动合并不等于行为兼容。

## 5. 检视发现与闭环

| 编号 | 级别 | 具体问题 | 处理与覆盖 |
| --- | --- | --- | --- |
| C01 | Must fix | 新增contextdb.ts导入团队已删除的ACCESS_KEY_COOKIE，Git不会报冲突 | 使用sessionCookieName；覆盖撤销后重放会话、配置别名、origin绑定 |
| C02 | Must fix | 旧middleware与团队proxy不能并存；直接选一边会丢安全或管理策略 | 删除旧入口，在proxy合成；覆盖本地化登录、私有页、静态资源、带扩展名API ID和生命周期限制 |
| C03 | Must fix | 旧部署模板缺PUBLIC_ORIGIN/SESSION_DIR且只读容器无会话写目录 | 新意图字段、0700目录和独立rw挂载；覆盖渲染、错误地址、路径权限与符号链接拒绝 |
| C04 | Must fix | 新管理代码只读HINDSIGHT前缀，团队前缀优先级会不一致 | 统一controlPlaneEnv；启动器保留团队配置和产品名，私有文件覆盖两套秘密；冲突变量行为测试 |
| C05 | Must fix | 管理fetch未带团队标签页产品身份，旧标签页保护不完整 | 使用productFetch；jsdom验证X-Product-Name及浏览器无Admin Authorization |
| C06 | Must fix | 本地健康探测Host与公网origin不同，会返回421 | 专用异步探测连接本地并发送规范化Host（大小写/默认端口/IDNA/IPv6）；shell显式传递origin/port（仅source不会export）；覆盖200/302/421/503、非法origin及实际Compose健康命令 |
| C07 | Must fix | CI未构建生产UI，端到端UI测试可能跳过 | 上一轮system job构建并用require标志；本轮改为独立test-contextdb-system-ui正式构建+双Worker JUnit完整性门禁，普通system不重复构建 |
| C08 | Important | 原生/新增故障用例断言内部异常原文，与团队脱敏契约冲突 | 保留运行代码，适配Worker重试/最终错误和MCP故障用例，状态/重试/无数据丢失等断言仍保留；视觉能力错误继续使用安全提示 |
| C09 | Important | 代理测试只设置HTTP_PROXY时，被宿主http_proxy遮蔽 | 测试显式清理小写变量，保留真实TCP代理断言 |
| C10 | Important | 原管理UI测试依赖旧布局导航mock和原生Bank术语 | 适配团队Link/usePathname和现有词条，不恢复旧团队已移除的外部模板链接 |
| C11 | Important | 迁移测试复用固定PG实例/端口，可能连接旧实例并因凭据冲突失败 | 新建module级私有PG工厂，唯一名称/端口/临时目录、明确停止；10个迁移/向量测试模块23项通过 |
| C12 | Important | 未分类的真实LLM及Docker/S3测试混入非外部依赖路径 | 补hs_llm_core/integration标记，保留对应测试；不使用xfail或静默断言替换真实能力 |
| C13 | Important | 原生测试尚未跟随团队品牌名、metrics和配置前缀变化；Copilot构造依赖宿主登录状态 | 测试契约适配；mock只覆盖认证元数据准备，仍验证真实provider工厂携带timeout；不改变任何原生运行文件 |
| C14 | Important | 共享PG的不同xdist Worker执行并发索引DDL，干扰索引修复断言 | 验收模式为每个Worker分配私有PG；默认开发/CI连接方式不变，不增加重试或跳过 |
| C15 | Important | 方言单例保存异步索引锁，前一用例竞争后的锁绑定已关闭的事件循环 | 测试夹具逐用例清理方言单例，同一用例的backend/store仍共享实例；直接双循环诊断可复现；未改运行代码，未声称解决生产跨循环使用 |
| C16 | Deferred baseline issue | 团队基线的概览页引用不存在的what-contextbase-does.json，文档生成钩子失败 | 已由 [Issue #14](https://github.com/RSIXDB/hindsight/issues/14) 独立跟踪；按用户范围要求移除相关修复，109个文档/生成文件均恢复团队基线；不属于管理功能依赖，不宣称该检查通过 |

原生测试适配全部位于 `hindsight-api-slim/tests/`，与移植业务代码分开阅读。修改范围包括公开品牌/错误契约和测试夹具/分类，不修改记忆算法、任务状态机或数据库迁移实现。

C08中原生两个Worker测试的失败断言在修改前已单独复现，且其运行文件与团队基线一致。调整的是安全输出契约的测试期望，未通过重新暴露内部错误换取测试通过。

## 6. 自检清单与剩余专家判断

- 分支直接从固定团队main创建；只有本特性和必要兼容/测试/文档变更。
- 不新增原生内核钩子、advisory lock、BaseHTTPMiddleware或管理调度循环。
- 管理路由解析输入后调用Repository/生命周期层；SQL仍集中在扩展持久层，动态标识经过校验。
- selected权限按UUID绑定，列表/搜索分页，Key完整值不进入普通列表、错误和浏览器持久存储。
- 授权复用仅限同请求/目标/凭据；新请求及新MCP消息重新认证。
- 管理删除有身份绑定ETag，超时结果未知不自动重放；不宣称并发删除安全。
- 保留团队产品配置v2、品牌模板/生成文件、会话撤销及UI配置优先级。
- lint、类型、构建、契约及功能测试证据集中记录；完整文档生成钩子保留Issue #14所述基线失败，不混入通过项；日志、.venv、node_modules和构建产物不提交。

专家仍需确认删除停止访问的产品约束、目标RDS权限和镜像交付要求。真实LLM评测、目标ECS/RDS、镜像漏洞扫描与生产压测不由本地stub回归替代；详见验证记录。原生敏感日志Issue #3按已有范围约定独立跟踪。


## 7. 关键代码调用链与逐步核对

以下路径省略扩展前缀 `hindsight-extensions/contextdb-service/hindsight_ext_contextdb/`；symbol便于重新定位，避免仅依赖易变行号。不是要求审阅者仅看这几个函数，还应追查上下游和错误分支。

### 7.1 管理HTTP认证到元数据提交

`http.ContextDBHttpExtension.get_router` 建立ManagementRoute，包装器先调用 `Repository.authenticate_admin`，再由FastAPI验证body；即使业务Key提交坏body也应先拒绝身份。`security.bearer_credential` 拒绝重复Authorization。`Repository.authenticate` 用完整Key的HMAC验证PG用户角色和状态；前缀/all不授予admin。

13项路由调用Repository或Lifecycle。检查所有变更事务是否先 `_instance_lock`、是否记录真实管理员公开key_id、审计是否与成功变更同事务；失败不得产生成功记录。输入错误只输出白名单字段位置，不回显Pydantic input、未知字段名或SQL诊断。

### 7.2 REST内容访问

`asgi.create_app` → `WorkspaceAuthorizationMiddleware.__call__` → `Repository.authenticate(key,bank)` → `authenticated_request`/`bank_target` → 原生Tenant认证 → `ContextDBTenantExtension.authenticate` → 原生引擎Validator钩子 → `ContextDBOperationValidator._authorize`。

检查目录、文件下载、内容清空等特殊路径；Bank/schema匹配必须在引擎执行入口仍成立。transport对非Bank路由放行，不能因此声称全API统一私有；SEC-01和version/OpenAPI必须单独评估。

### 7.3 MCP发现与执行

`mcp.ContextDBMCPExtension` 中间件读取当前HTTP消息Bearer，设置实际工具Bank；Tenant/Validator筛选当前工具集合及授权实际目标。`filter_mcp_tools` 在原生外层恢复ContextVar之后仍从当前HTTP request取凭据/目标。检查新session与旧session、工具发现并集和实际执行、path Bank与参数Bank不同的冲突行为。

静态工具隐藏只是减少误调用，不能覆盖执行授权。优先打开system test_104/105/111，核对先writer后reader、跨空间和吊销后重放session的断言。

### 7.4 受信管理调用与Worker

`authorization.workspace_management` 在已认证管理路由和状态过渡后构造原生internal RequestContext，绑定workspace_id/bank/schema/action和当前asyncio task。`management_call` 要求同一context对象与owner task；退出后active=false。检查客户headers、普通Worker、继承ContextVar的子任务不能取得生命周期权限。

Worker发现走 `list_tenants` / `worker_workspaces`，普通后台任务仍校验注册空间与schema；不因原客户Key吊销而丢弃已接受处理。不得将此解释为删除期间执行安全保证。创建/删除中的任务发现及周期任务入队限制以validator实际分支为准。

### 7.5 创建与删除

`Lifecycle.create` → Repository预留creating → 原生migration/update_bank/profile确认 → finish_workspace_creation。

`Lifecycle.delete` → Repository检查原ETag并记deleting → schema检查/原生delete_bank → finish_workspace_deletion → `_destroy_workspace`。

逐个await检查元数据连接是否已经归还；最终事务需再次验证状态/版本/归属/外部依赖。取消不被Exception捕获为普通失败，因此会保留未知状态；没有shield或自动后台恢复。对比test_lifecycle_metadata中短事务、取消、最终回滚、外部依赖测试，检查原生清理的事务外副作用不能被PG回滚测试覆盖。

### 7.6 UI与部署

`proxy.ts`保留团队Host/Origin/产品身份/会话流程，ContextDB配置有效后叠加后台身份与原生生命周期限制。`login/route.ts`先密码与后台身份，再签发团队磁盘会话。`requireContextDBAdmin`路由自身复验会话/写Origin；管理转发实际由API校验Admin，因此不另缓存后台身份。

管理代理只接受users/workspaces固定路径，转发q/limit/offset和If-Match；body限制为JSON对象、业务字段由Python模型校验，响应递归防御过滤秘密字段。`contextdb-api.ts`用productFetch，组件保留旧ETag/预期空间ID、一次性secret和结果未知状态。

`deployment.load_config/render` → `bootstrap.prepare_deployment/load_deployment_secrets` → `launch` → `ui_probe`。检查密码两套前缀覆盖、PG/模型秘密不传UI、UI凭据不传API/Worker；会话rw挂载和秘密ro目录分离；健康探测发送规范化公网Host但不携带秘密。

## 8. 契约、代码和测试追踪矩阵

扩展测试简称E，目录为 `hindsight-extensions/contextdb-service/tests/python/`；系统简称S，目录为同插件`tests/system/`；UI测试简称U，目录为同插件`tests/ui/`。运行实现的UI路径仍相对hindsight-control-plane/src。文件名/symbol可用rg定位。所有RUN结果在VALIDATION，不由本矩阵重复宣称。

| 契约ID / 设计 | 实现symbol / 路径 | 具体证据 / 仍需核对 |
| --- | --- | --- |
| T01 全Key统一认证，role来自PG（D3/D5.1） | security.key_digest、Repository.authenticate/authenticate_admin | E test_repository::test_member_cannot_manage_keys_or_directory；test_security；S test_111全空间业务Key仍不能管理 |
| T02 selected/all和read矩阵（D3.3～3.4） | models.ApiKeyCreate/ApiKeyPatch；Repository._replace_authorization/_selected_principal；validator | E test_extensions::test_read_key_covers_knowledge_memory_and_reflect；test_http::test_key_name_edit_preserves_mixed_authorization_and_secret；S test_113 |
| T03 每消息MCP身份（D1.3/D4.1） | tenant._current_mcp_credential；mcp；validator.filter_mcp_tools | E test_extensions::test_mcp_uses_current_http_key_instead_of_initialize_identity；S test_104/105及test_111吊销后旧session |
| T04 Worker隔离及internal边界（D1.3/D4.1） | Tenant.list_tenants；validator._authorize；authorization.management_call | E test_extensions::test_internal_worker_is_scoped_but_cannot_create_delete_bank；S test_100双空间Worker隔离 |
| T05 名称规范化/拒接孤立schema（D1.2/D5.2.3） | models.workspace_name；Repository.create_workspace | E test_readable_workspaces::test_readable_bank_and_schema_are_canonical_and_bounded、test_unregistered_schema_is_never_adopted |
| T06 同名重建/旧ETag/旧picker（D3.3/D4.3/D5.2） | http._workspace_condition；Repository.delete_workspace/_replace_authorization/_destroy_workspace | E test_readable_workspaces::test_same_name_successor_does_not_inherit_selected_grants_or_stale_deletes、test_grant_expectation_rejects_same_name_successor_for_new_and_existing_key；S test_115 |
| T07 同步201/204及无自动重放（D5.2/D6） | Lifecycle；UI contextdb-api和组件 | E test_http::test_creation_response_waits_for_native_migration_without_polling；S test_103::test_lost_management_response_is_resolved_by_query_without_replaying_write；U contextdb-workspaces.test.ts |
| T08 短事务/取消/最终回滚（D5.2.5/D5.3.7） | Lifecycle；Repository.finish_workspace_* | E test_lifecycle_metadata::test_native_awaits_do_not_hold_shared_pool_connection、test_cancellation_preserves_unknown_state_without_recovery_or_shield、test_final_cleanup_rolls_back_authorizations_and_key_versions |
| T09 schema所有者/依赖（D5.3.7） | Repository.verify_workspace_schema/_has_external_schema_dependencies | E test_lifecycle_metadata::test_external_dependencies_are_never_dropped；test_customer_pg_boundary是PG客户角色边界，不能冒充全部DDL依赖覆盖 |
| T10 管理错误/秘密/一次性展示（D3.2/D5.4） | http.ManagementRoute；UI管理代理；components/contextdb/user-keys-panel | E test_http::test_auth_precedes_body_validation_and_errors_hide_credentials；test_credential_repr；U contextdb-users-view.test.tsx、contextdb-boundaries.test.ts；S test_112/114 |
| T11 请求内复用、下一次重查（D1.3/D5.1） | authorization.authenticated_request/authenticated_principal | E test_query_efficiency::test_request_reuses_target_auth_but_next_request_rechecks_revocation；S test_111 |
| T12 1000授权与数据库约束（D5.3.6） | schema.sql延迟触发器；Repository._replace_authorization | E test_query_efficiency::test_thousand_grants_use_bounded_sql_and_still_reject_overflow；SQL计数不是生产性能基准 |
| T13 团队会话/Origin/产品身份（D3.2.1） | UI proxy.ts、auth/session.ts、contextdb.ts、productFetch | U contextdb.test.ts、contextdb-boundaries.test.ts、contextdb-native-entrypoints.test.tsx；S test_112退出后Cookie重放 |
| T14 配置别名/秘密隔离/会话挂载（D2.4.2） | deployment.py、bootstrap.py、launch.py | E test_deployment_contract、test_bootstrap_deployment、test_release_hardening；U contextdb配置测试 |
| T15 Host探测与Compose实际shell（D2.4.4） | ui_probe.py、deployment/compose.yaml | E test_ui_probe.py：规范化地址矩阵、302/421/503拒绝、实际shell命令 |
| T16 默认原生兼容/生产UI构建（D2/D3.2.1） | 未启用插件的原生路径、artifacts.py、CI | S test_107原生默认兼容；test_102构建指纹；test_112生产UI；缺UI/缺用例/跳过由独立双Worker JUnit门禁拒绝 |
| T17 原生配置响应字段过滤一致性（D5.1.1） | Tenant.get_allowed_config_fields vs原生_get_bank_config_authenticated | 已在自研transport内修复；插件16项投影/传输回归及test_114双WorkerSDK故事，见第12章与VALIDATION第10章 |

D表示DESIGN章节。矩阵证明“去哪检查”，不证明每个交错、字段或攻击面已穷尽。

## 9. 当前发现状态与独立检视缺口

C01～C15是移植过程中发现且已按所列测试修正的实现者记录；C16是明确分离的基线问题。SEC-01此前为配置响应过滤不一致；当前在插件transport内补齐投影，最新验证见第12章和VALIDATION第10章。

尚无本分支独立专家/committer审查批准；现有本机测试不是独立安全审查。删除支持前提、公开功能位策略、SEC-01处置、Issue #14门禁及目标环境验收需在统一设计对应问题及本文件记录具体决定。报告应把未运行、已接受范围、开放缺陷分别说明，不使用无具体指向的“with risks”。


## 10. a05b808增量适配记录（SEC-01修复前历史）

来源为ddf5c360→a05b808的113文件差异，不以整个来源目录覆盖团队代码。四处冲突为package.json、bank-selector.tsx、tsconfig.json和迁移后的test_112；其余自动合并仍逐层核对。这些变化与初始管理功能通过amend整理为一个提交；本节保留增量适配的具体依据。

| 项目 | 来源变化及集成决定 | 核验入口 |
| --- | --- | --- |
| UI组件/状态 | 合入components/contextdb目录和成员/Key/picker/只读核对分工；bank-selector保留productFetch及团队导航 | UI全量、Key状态/响应、生命周期入口回归 |
| TypeScript配置 | 保留团队standalone排除及标准.next路径，只增加插件UI测试；不带入来源累计的临时.next-端口条目 | tsc、正式Next构建 |
| 服务端凭据 | 合入server-only；保留controlPlaneEnv、动态会话Cookie、PUBLIC_ORIGIN和后台Admin复验 | 团队认证、别名、撤销及productFetch测试 |
| 共享检查/授权 | database_checks、固定grant SQL、permission_scopes/discovery_scopes与来源一致；schema/OpenAPI未变 | 插件Python、MCP发现查询计数、跨语言Key合同 |
| 生产UI owner | 使用来源的新普通owner；补回团队local/public-origin/session-dir和退出后旧Cookie拒绝断言 | 插件system test_112，两种Worker |
| 迁移/独立Worker | 保留三套API前缀清理，使用现有主库和task-owned PG；不操作部署库 | 原生/插件系统故事，临时资源故障清理 |
| 迁移收集遗漏 | 源增量不包含旧集成独有test_ui_probe；手动迁入python并修正路径，productFetch用例迁入ui | 21项健康探测和产品身份用例继续通过 |
| CI | 接入来源独立生产UI job、跨语言合同、双Worker JUnit检查及汇总；移除旧普通system中的重复UI构建/无效require变量 | test_production_ui_gate、CI YAML走读；远端CI未执行 |
| 隔离验收入口 | verify_integration增加contextdb-system/contracts，原system仅原生，extension显式tests/python | 当前回归命令与结果见VALIDATION |

T18：新响应边界及Key投影 → contextdb-api.ts → tests/ui/contextdb-responses、contextdb-key-types、tests/contracts/test_ui_key_contract。

T19：MCP目录无逐空间查询 → authorization.discovery_scopes、validator.filter_mcp_tools → tests/python/test_mcp_discovery（1/10/1000空间、空目录、当前消息和执行权限）。

T20：UI状态归属/secret迟到清理 → components/contextdb/user-keys-panel、key-editor-dialog → tests/ui/contextdb-key-state和contextdb-users-view；实际进程见system/test_112。

T21：生产UI门禁拒绝skip/缺失 → scripts/check_production_ui.py → tests/python/test_production_ui_gate；CI接线见独立job。

本轮原生Python运行目录相对团队base仍零差异，团队既有错误脱敏/品牌测试适配保留。SEC-01的config/overrides字段过滤不一致未在最新来源中解决，继续OPEN；不混入Issue #14修复。本轮回归已完成，最终结果见VALIDATION第8章；不复用来源的334/486/61作为当前团队计数。


本轮原生dotenv适配：来源把托管禁用dotenv用例移到插件，增量应用后原生entrypoint测试失去旧集成对PYTHON_DOTENV_DISABLED的显式清理。在本轮受控验收环境中复现失败；只在该测试恢复enabled-path环境并保留所有优先级断言，不更改运行策略、不新增skip/xfail。定向5通过/1既有条件跳过；完整重跑结果见VALIDATION。

MCP原生路由测试隔离：API完整首轮出现test_mcp_bank_named_sse_routes_to_single_bank teardown错误；日志显示默认poller领取前面测试故意留下的8个pending任务，随后与memory fixture关闭竞争。本轮仅对该MCP路由测试模块关闭无关poller，其memory仍用同步task backend；不修改Worker运行代码，不改变专门Worker测试及61项真实系统故事。加入两套配置前缀的局部monkeypatch，路由/瞬时提取失败/dotenv定向19通过、1既有条件跳过；最后全量回归另记。


本轮最终自检：原生API10857通过、186条件跳过、5既有预期失败，0失败/错误；插件Python359、UI593、跨语言合同1、ContextDB系统61全部通过；原生系统354通过、2既有条件跳过、11子测试通过。构建、指纹、类型检查、最终lint和静态差异检查通过。证据、首轮失败及两项测试隔离适配均在VALIDATION第8章，不以首轮失败或来源结果替代本轮结果。未发现新增的适配阻断项；SEC-01继续OPEN，Issue #14的文档生成门禁仍为已知基线失败，远端CI及独立批准尚未执行。本段记录提交整理前的验收快照；最终发布检查见VALIDATION第9章，未进行部署。


## 11. amend提交与PR检视前复核（首次PR时点）

按用户要求，将a05b808适配、完整设计恢复、检视记录及验证证据一起amend到本特性提交，保持团队main上只有一个功能提交。原先0e283e923为本轮验收前的历史快照；amend后的当前提交以git rev-parse HEAD及PR显示为准，正文不硬编码自身提交哈希。

本轮只更新文档中的状态和问题表述，没有新增运行行为。完整DESIGN保留总体方案、部署、凭据、UI、REST/MCP、生命周期、PG、13项API与Q&A；CODE-REVIEW保留代码调用链、冲突决策、发现闭环和T01～T21追踪。所有读者使用同一套完整正文，PLAN.md删除；没有恢复角色任务文档。资料仓原始设计/检视正文存在其他未提交修改，本轮不覆盖它们；本次PR内的设计作为团队分支同版阅读副本，并记录固定来源。

Findings：Critical无新增；Important为OPEN SEC-01（字段过滤不一致及配置可见性需求待确认），以及已由Issue #14跟踪的文档生成基线失败；不把它们标成已解决。Minor无新增需阻止本次送审项。SEC-01的场景、现象、按当前实现规则的预期和当前行为见DESIGN第5.1.1节；它不能直接证明任意秘密泄漏，也不能将当前实现规则当成已经确认的产品需求。

Verification：VALIDATION第8章列出实际本机测试及跳过；第9章记录提交前复核和已知钩子例外。当前原生运行目录仍与团队基线一致；无新增provider/SDK/原生配置标志或原生迁移，因此不生成无关客户端/原生OpenAPI，不重新引入Issue #14的文档修复。

Recommendation：送PR检视；不代替专家批准或宣告可直接发布。Open questions：普通业务Key应看到哪些空间配置；SEC-01处置及端到端补证；Issue #14门禁的合入安排；目标环境验收。创建PR是提交检视请求，不是关闭这些问题或自动合入。


## 12. SEC-01插件内修复的最终复核

先在原仓实现插件投影并通过350项Python及63项完整ContextDB系统测试，再同步到团队目录。此前尝试的原生MemoryEngine过滤和4项新增原生用例已全部撤回；不能把该尝试的96项结果当成本轮插件验证。原生运行目录继续相对各自基线零差异，不增加原生方法替换或monkey patch。

实现为transport._bank_config_json及WorkspaceAuthorizationMiddleware._project_json_response。前者按宿主公开BankConfigResponse模型校验，并以已经过滤的config键筛选overrides；后者复用现有任务诊断缓冲机制，只拦截选定配置成功JSON响应。没有新增权限查询/钩子调用、没有存储写回，也不在中间件中重建原生GET/PATCH/DELETE业务逻辑。配置错误状态原样返回，非法成功响应安全503；分块/编码/长度和无关路径均有测试。

E test_transport新增16项矩阵和HTTP边界回归，旧任务诊断测试一并验证。S test_114新增故事、两种Worker，发布SDK读取仍成功，当前member两部分为空，Admin读写/重置不丢存储，跨空间拒绝，MCP get_bank保留。原生默认兼容和双Worker生产UI属于完整系统验收，不因插件修复跳过。实际结果见VALIDATION第10章，不将针对性和完整轮重复相加。

Findings：Critical无新增，Important无新增插件修复阻断；Issue #14独立作为团队基线文档生成问题，非本特性缺陷。SEC-01字段投影在当前实现关闭，公开version/schema策略仍按原设计边界处理。Verification：原仓和集成的插件实现/测试一致、原生运行差异为空、lint及实际JUnit核对；最终计数见VALIDATION。Recommendation：按明确插件边界送审，不代替独立专家批准或生产验收。
