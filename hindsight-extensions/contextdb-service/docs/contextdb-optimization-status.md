# ContextDB 优化清单、实施状态与待讨论项

当前交付分支：`contextdb/first-release`，上游基线 `a77c1f341`；已将开发期多次提交与本轮简化整理为一个完整功能提交。管理 API v1、首发元数据1。WS-02/03/05 已联合落地，下面记录实现及快照对应的验证证据；保留历史分析和阿里 UI 实测，不将历史通过计数替代最终复跑。夜间00a921b52快照的镜像及两模式容器功能已通过，本机Colima ARM须OPENSSL_armcap=0兼容覆盖；首发基线1需重新构建镜像，不能引用旧镜像作为当前代码或目标ECS默认启动证据。目标RDS中文全文仍有插件/适配/恢复依赖。

[当前设计](contextdb-release-design.md) · [部署与升级](contextdb-optimized-guide.md) · [curl验收](contextdb-optimized-curl-guide.md) · [OpenAPI](contextdb-control-plane.openapi.yaml) · [管控集成](contextdb-service-integration-guide.md) · [Agent合同](contextdb-deployment-contract.md) · [运维](contextdb-operations-runbook.md)

<a id="workspace-pending"></a>

## 0. 本轮三个优化点：已联合实现

2026-10-18补充：按照首个正式版本的决定，管理结构统一以1为基线，撤销开发期1/2/3/4的产品升级链。代码、DDL、运行校验及当前部署文档同步调整；下方历史验收保留原快照，重定基线后的测试单独记录。

三项已在同一实现中完成：可读标识、统一寻址和安全删除重建一起验证。原先“不采用”可读标识的记录已纠正；没有通过仅修改 banks 表或 UI 标签来冒充完整映射调整。新建对象采用下表规则，开发期试验库不纳入已发布升级链；旧结构拒绝自动接管。

首发基线1与统一连接复验：扩展425项通过、1项可选跳过；原生SDK/真实API的工作空间、授权、REST/MCP、Recall/Retain/Reflect及同名重建故事在两种Worker模式下共12项通过。初始化、管理员离线轮换和运行统一使用HINDSIGHT_API_DATABASE_URL，删除独立bootstrap地址及跨连接比对；遗留地址不会覆盖统一地址，也不能在缺失统一地址时回退。新增覆盖新库版本1、重复初始化身份/权限不变、旧试验布局/版本拒绝且不改号、管理员导入失败时DDL事务回滚。扩展ruff/ty及仓库lint通过。该次未重新构建UI/容器，夜间镜像及完整原生回归仍属于先前快照；发布需同源重建。证据位于本机 artifacts/contextdb-metadata-v1-20261018。

### 0.1 WS-02：可读 Bank ID 与 schema 名称

| 对象 | 新建空间示例 | 用途 |
| --- | --- | --- |
| 工作空间名称 | jiamu | 展示和选择空间 |
| bank_id | jiamu | 对外可读标识，直接用于原生 Hindsight 业务接口 |
| schema_name | ctxdb_ws_jiamu | 对应空间的实际业务 schema，由服务端受控生成 |
| workspace_id | 内部 UUID A | 不可复用的对象身份，用于授权关联、管理操作、准入和执行归属 |

- 新建空间不再强制 bank_id=workspace_id；不将原生 Bank ID 限制为32位十六进制。
- 同一实例内，未彻底删除的空间不能重复占用名称、bank_id 或 schema。完成删除后允许同名创建，新对象使用新的内部 UUID。
- 首版名称经 NFKC/trim/小写规范化后等于 bank_id，限制 `^[a-z][a-z0-9_]{0,53}$`，例如 MySQL→mysql。schema 前缀9字符加标识最多54字符，符合 PG63字节标识上限。首版不支持中文展示名、连字符及改名；避免改动原生未加引号的 schema SQL，也不引入易冲突的名称编码。
- 复用原生 Hindsight 的字符串 Bank ID 能力，优先修改扩展层的映射与校验，不修改记忆算法。

### 0.2 WS-05：管理与业务接口统一寻址

- 管理 GET/DELETE `/workspaces/{bank_id}` 与原生 REST/MCP 使用相同可读 bank_id；工作空间列表、详情、Key 授权、UI 和 OpenAPI 已一起更新。用户和 Key 本身的资源地址仍按各自稳定 ID，不混用空间名称。
- 元数据目录同时返回 bank_id、内部 workspace_id 及绑定该对象的 etag。原生 Bank 行和单/多空间 MCP 使用可读 bank_id，已拆开原先 bank_id=workspace_id 的假设。
- selected 输入按 bank_id 选择空间，服务端在管理事务锁内解析 active 空间并保存内部 workspace_id。UI 始终附加所见 workspace_id 期望值，创建 Key 和增补授权都检查同名替换，冲突409；API 省略期望值则明确表示授权当前同名对象。
- 内部 UUID 继续用于关联和身份校验；客户端可以从查询结果或服务端条件凭据中获得必要身份，不要求把全部业务地址继续写成 UUID。
- Tenant、Validator、Worker、生命周期和原生目录映射已按外部 Bank ID/内部 UUID 分开；原生记忆算法保持复用。

### 0.3 WS-03：彻底删除后允许同名重建，隔离旧授权与旧请求

允许删除旧 jiamu 后再创建新 jiamu，不采用“名称永久占用”。

| 项目 | 旧空间 | 同名新空间 |
| --- | --- | --- |
| 名称 / 可读 bank_id | jiamu | jiamu |
| 内部 workspace_id | UUID A | UUID B，与 A 不同 |
| schema | ctxdb_ws_jiamu | 旧 schema 彻底删除后重新创建 |

**名称释放条件：** 先关闭新请求准入，确认在途请求、原生任务及旧初始化/删除执行者已经结束，完成业务数据、文件、schema 和关联授权清理，管理操作成功后才允许同名创建。删除中、删除失败或结果未知时不释放名称，不先标 deleted 后异步继续清理可复用 schema。

**旧授权：** 指定空间的 Key 授权绑定 UUID A；删除时移除这些关联并增加受影响 Key 的版本。新 UUID B 不继承旧授权，须明确重新授权；空 selected 仍表示没有权限。“全部工作空间”Key 按原定义可访问未来新建空间，因此可访问 B。

**旧删除请求与重试：** 删除必须绑定当时查询到的原对象身份，不能仅凭 /workspaces/jiamu 作用于任何当前同名对象。当前以带双引号的 `etag="<workspace_id>:<version>"` 及 DELETE If-Match 实现；缺少条件428、格式错误400、旧身份/版本412。只使用可能在不同对象上重复的 version 数字不够。幂等重试优先定位旧操作及 UUID A，返回旧结果或明确拒绝，不能解析为 B 后再次执行。操作记录超过保留窗口时，也不能把陈旧删除请求当作新删除执行。

旧请求保护重点是空间生命周期操作和重试；原生业务请求仍按当前 Key 授权检查。不能承诺“全部空间 Key 携带同一个可读地址，任何陈旧业务请求都会自动识别并拒绝”。

完成后删除业务 schema 和空间记录，不为禁止复用而永久保留名称占用表。操作结果在约定窗口内保留，审计独立保留；继续复用现有生命周期、准入和管理操作机制。

### 0.4 联合验证与边界

1. 新建 jiamu 后，原生 Bank 为 jiamu、schema 为 ctxdb_ws_jiamu；管理、授权、REST/SDK、单空间和多空间 MCP 寻址一致。
2. 同名并发创建被唯一约束拒绝；删除中、失败、结果未知及旧执行者未结束时不能重建。
3. 删除完成后可同名重建；内部 UUID 改变，旧 schema 和数据已清除，不承接旧数据。
4. 旧 selected 授权不能访问新对象，旧编辑返回并发冲突；all Key 保持未来空间权限。
5. 旧删除请求、响应丢失重试、幂等结果过期等场景均不能误删同名新对象。
6. 使用独立临时 PG 和新建任务库验证，不改用户旧库。首发从版本1的新库初始化；开发期旧结构拒绝自动改号，已有数据保持原样。以后正式发布再增加从1开始的有序迁移。
7. 生命周期迁移和整个 WorkerPoller 执行（含最终状态/重试 SQL）都有持久准入。取消任务行不能证明旧执行者结束；held-writer 测试验证其仍会阻止 DROP/同名重建。旧任务缺失/不匹配空间代次时，在进入执行前拒绝，不能向新 schema 写失败状态。
8. 运行配置固定 RUN_MIGRATIONS_ON_STARTUP=false；新空间显式受保护迁移，旧 schema 升级停全部写入者后按实际 schema 离线执行。首版不支持原生 Webhook 配置/投递，部署显式拒绝；不把无代次任务留成未知兼容能力。
9. 原生 fire-and-forget LLMTrace/Audit INSERT 没有完整执行期限保护，首版强制 LLM_TRACE_ENABLED=false、AUDIT_LOG_ENABLED=false。trace 缺省 true 也拒绝；内外部配置入口不允许 audit_log_enabled，既有 Bank 配置或默认模板开启时启动/迁移拒绝。管理审计 ctxdb_meta.audit_events 保留，JSON日志/metrics/OTEL可用；UI原生正文/审计页不产生新记录。

### 0.5 夜间任务的补充调研与交付项（2026-10-17）

代码、脚本和文档已实现，测试及四类专家检视已开展；通过证据和仍待环境验收的事项分列。拓扑性能与中文全文选型须依据实际目标环境，不以“默认简单”或仓库星数替代验证。

| 项目 | 需完成的工作 | 当前证据与入口 |
| --- | --- | --- |
| DEP-09 API/Worker 部署 | 已提供明确 merged/split 意图及监管命令；两种模式复用原生 Worker 和同一执行准入；同容器双进程不作为默认样例 | [设计2.5](contextdb-release-design.md#api-worker-deployment)；功能回归与性能/容器最终验收分别记录，不能据单元测试确定云上规格 |
| SEARCH-01 中英文全文选型 | 已比较 native、PGroonga、pg_search 及中文适配候选；目标 RDS 可安装性、许可证、备份/恢复是发布前置条件 | [设计2.6](contextdb-release-design.md#fulltext-selection)；Groonga 为 LGPL，PGroonga 本身为 PostgreSQL License。中文 RDS 路线仍有依赖，尚未宣称生产通过 |
| DEP-10 服务化交接 | 已交付人工指南、类型化 JSON/私有文件合同、validate/render/status、同版镜像/Compose样例；状态核对健康正文和管理员实例身份，组件只挂载自己的秘密 | [人工指南](contextdb-service-integration-guide.md)、[Agent合同](contextdb-deployment-contract.md)；Web源码复审 ACCEPT，同源镜像与两模式功能通过；本机CPU覆盖、真实ECS默认启动及发行依赖扫描边界见验收报告 |
| OPS-01 运维与诊断 | 已交付日志/任务/PG/模型分层诊断、私有CA、PGSERVICEFILE/PGPASSFILE、备份恢复与学习入口；未知执行者须先隔离再恢复 | [运维手册](contextdb-operations-runbook.md)；流程可执行，云上HA/PITR/灾备演练仍需目标环境验收 |

<a id="document-consistency"></a>

### 0.6 文档与代码统一核对（2026-10-18）

**原因：方案发生调整后，部分旧描述被保留在当前文档，历史入口也未统一标识。此前只清理调用代码，没有完整核对部署、设计和资料仓入口。** 以下按当前代码修正，不把历史功能继续算作本期支持能力。

| 问题 | 处理及当前结论 |
| --- | --- |
| 旧管理员摘要环境变量、独立管控认证说明 | 已移除运行代码、测试夹具和当前配置说明；管理员/业务Key统一PG HMAC认证，没有SHA回退或CK入口 |
| 独立bootstrap数据库地址及继承清理分支 | 初始化、轮换、运行只用HINDSIGHT_API_DATABASE_URL；旧变量不再是部署输入；删除启动器中无消费方的旧变量处理 |
| 开发期1/2/3/4升级链及“保留旧UUID库升级”承诺 | 首发结构为1；不接管试验库。当前清单、设计和管控联调入口撤回旧升级承诺 |
| 仅被测试使用的业务Key专用解析函数 | 已删除；管理员和业务Key共用credential_key_id解析及Repository.authenticate认证 |
| sha256被解释为“旧版离线导入校验” | 更正为可选凭据文件一致性校验；不参与运行认证，不是环境变量。HMAC中的SHA256算法继续使用 |
| PGroonga被写成全局默认、监控插件被写成必装 | 安装页改为基础三插件＋按语言选全文后端；pg_stat_statements可选；云RDS中文路线须确认平台能力 |
| schema_name类型与DDL不符；API“只加载pepper”表述不完整 | schema_name实际为text，CHECK与bank_id长度共同限长；API/Worker还加载PG、模型及扩展配置，不加载UI秘密 |
| 管控联调入口仍使用元数据3、UUID删除及bank_id=workspace_id | 已同步为首发1、管理/业务统一可读bank_id、内部UUID关联和DELETE身份ETag |
| 旧设计、旧验证、版本对比页可被误认为当前指南 | 首屏增加历史标记及当前入口；保留原文供对照，不按旧命令部署当前代码 |
| 离线原生升级示例依赖前面终端的临时环境 | 示例先显式加载本实例api.env，关闭.env自动发现；仅适用于未来明确支持的正式版本升级，不接管试验库 |

**本期仍有用途的机制：** pepper用于独立保存HMAC秘密；内部workspace_id区分同名重建对象；元数据版本/format_id用于识别受支持结构；管理操作、在途准入、审计分别负责执行恢复、删除屏障、操作追溯。内部audit_events.control_key_id只是管理员Key标识列名，不表示还存在一套管控Key认证。本轮不改这些持久语义或表结构。

核对范围：当前11份入口/设计/配置/部署/API/运维文档、14个管理方法、部署模型和渲染器、认证/初始化/轮换代码、DDL，以及资料仓对应入口。59个文档环境变量名称逐项对照；唯一不存在的名称是文档明确提示“不要使用”的通用Embedding维度变量。历史文档中的旧变量和接口只作为快照保留。容器、目标RDS和云上HA不由本次静态核对证明。

本轮验证：扩展425项通过、1项可选跳过；Ruff、ty、仓库lint、OpenAPI --check及88段文档代码块检查通过；当前文档相对文件链接均存在。未重新部署、重建容器或重复执行历史全量原生/云上验收。证据保存在本机 artifacts/contextdb-document-consistency-20261018。

## 1. 历史实施结果与待优化状态

| 编号 | 当前决定与实现 | 验证入口 |
| --- | --- | --- |
| UM-01～08 | 保留已实现的实例级“用户管理”、成员展开/更多菜单、默认读写、逐空间授权、脱敏和一次性明文、吊销隐藏、成员停用/删除与审计 | UI组件、HTTP、真实UI→API、REST/MCP |
| UM-09 | 现有名称搜索足够，不加复杂过滤；使用统一消息、请求取消/归属校验；普通成员无角色选择或个人UI登录 | users-view、UI代理与端到端 |
| UM-10 | NFKC/trim/casefold 名称唯一，active/disabled一起占名；PG唯一索引兜底，并发409；保留管理员名；软删除后新身份，不继承旧Key | release_hardening、bootstrap_deployment、115故事 |
| AUTH-01 | 管理员与业务Key统一PG HMAC认证；角色来自PG；离线导入唯一受保护管理员；不保留运行时SHA回退 | security/repository/bootstrap/tenant、HTTP、系统测试 |
| DEP-01 | 同版源码交付、实际模块路径及扩展接口预检、受支持构建；部署方记录提交/补丁或镜像摘要 | preflight、Node构建、service.sh测试 |
| DEP-02 | 外部PG无强制pg0；embedded-db可选依赖，发行包pg0-embedded | pyproject、部署文档/预检 |
| DEP-03 | HINDSIGHT_API_ENV_FILE显式文件或空值；托管启动关闭cwd/父目录自动发现，PG连接复用 | 原生dotenv的8项测试、启动脚本 |
| DEP-04/07 | 正式.mjs配置、支持Node22.12+/24、平台optional依赖、系统字体 | Node22和24生产构建 |
| DEP-05 | API readiness前不启动UI；启动有界退避，仅暂时故障重试，凭据错误立即拒绝；请求仍实时鉴权 | UI启动回归、实际生产UI→API |
| DEP-06 | 首次秘密原子落盘、0600/0700、重复保留；已初始化缺文件拒绝补生；离线显式管理员轮换 | bootstrap_deployment与脚本重复init |
| DEP-08 | Python/Node/npm/esbuild/PG扩展/UTF8/全文语言预检；中文不能以native英文验收代替 | preflight测试、分层部署说明 |
| API-01～07 | 保留既有敏感载荷门禁、单一authorization、字段/错误/列表合同、并发If-Match、显式恢复及安全代理 | HTTP/OpenAPI、所有ContextDB系统故事 |
| API-08 | 管理代理不再与middleware重复查身份；使用时间最多60秒更新一次；统计只在未带ETag列表，可编辑快照排除统计 | UI请求计数、使用时间/吊销测试、OpenAPI |
| API-09 | /admin/session改/admin/identity，所有UI及测试调用同步，不新增登录或Key接口 | 路由/代理/仪表启动测试 |
| WS-01 | 正常行移除“查询进度”；处理中单目录GET自动刷新1～5秒，最多2分钟；失败可查、未知结果显式恢复 | workspaces-view、recovery测试 |
| WS-02 | **已实现**：新空间规范化可读 bank_id、ctxdb_ws_<bank_id>，内部 UUID 保留作稳定身份；首版小写ASCII字母/数字/下划线，最多54字符 | 第0.1节、readable_workspaces PG回归、ContextDB系统及UI回归 |
| WS-03 | **已实现**：物理清理、有界历史、代次ETag、旧授权清理、未知迁移及完整Worker执行准入；同名重建前完整排空 | readable_workspaces、worker_execution_admission；原生Worker167项及原生/扩展系统回归，见第4节快照范围 |
| WS-04 | **已由 WS-05 统一**：GET/DELETE 都按可读 bank_id；不增加名称/UUID双重解析，也不自动接管开发期 UUID 库 | HTTP/OpenAPI、真实SDK/MCP；开发期结构拒绝覆盖回归 |
| WS-05 | **已实现**：管理/REST/MCP统一 bank_id，selected按 bank_id 输入并可附UUID期望，PG关联仍为不可复用UUID；UI选择与导航同步 | 第0.2节、授权代次冲突回归、UI405项、ContextDB系统当前63个唯一场景，失败旧预期及复验见第4节 |
| DB-01～04 | 保留单行部署、去冗余字段、关联授权、varchar输入约束/COMMENT和必要索引；新增用户规范化唯一与管理员约束 | schema、迁移、目录/注释/并发测试 |
| DB-05 | 采用last_used_at有界更新；不缓存认证、不改持久准入、不去全局管理事务锁 | 使用时间/即时吊销/并发屏障回归 |
| DB-06 | 管理任务、准入、审计分工不合表；完成空间行清理及有界操作历史回收，未知执行者不按TTL清除 | 终态保留、准入/故障/租约/排空故事 |
| OBS-01 | 首版明确关闭原生后台LLM trace/audit，禁止Bank/模板重新开启，拒绝缺省trace=true；保留管理审计和运行可观测性 | 新跨代晚写风险收尾修复；最终复跑覆盖配置/启动/迁移拒绝，不能引用旧快照计数冒充已验证 |

## 2. 已有机制与本轮调整的衔接

- 已实现第0节方案：可读 bank_id 对外寻址，内部 UUID 稳定关联；名称在彻底删除后可复用。开发期 UUID Bank/schema 留在原试验库，不自动导入首发库。
- 正常删除空间后不保留空表或空间墓碑；仍保留操作结果和审计，生命周期不同。开发期旧结构不自动导入首发实例。
- 删除选中空间会删除对应Key关联并递增版本。内部空selected表示无权限，公开创建/替换仍要求1～1000个有效空间；不会变成all或继承同名新空间。
- 管理员同样入users/api_keys，但普通成员列表和CRUD隐藏/保护它。普通UI创建用户无角色选项；all范围不会提权。
- pepper继续保留并独立备份。管理员与业务 Key 统一使用PG中的HMAC-SHA256摘要认证；部署无需额外的管理员摘要环境变量。
- 历史默认168小时，可配置24～8760。浏览器未知意图24小时后不重放；服务端不承诺过期请求“从未执行”。未完成/未知/有残留空间的失败操作不清理。
- 只在API就绪后启动UI；启动暂时故障重试与每次请求的权限复核是两件事，不以授权缓存换启动速度。

## 3. 评估后不增加的机制

以下原本是“先测量再决定”的候选，不是漏实现的既定功能：

| 候选 | 本次决定 |
| --- | --- |
| 名称搜索GIN、全量Key历史索引、更多任务领取索引 | 现有小目录无证据证明瓶颈；保留必要B-tree/唯一/部分索引，不预建近似索引 |
| 全局管理锁替换 | 当前是低频管理写；保持已验证并发语义，不引入更复杂锁序 |
| Bank列表/MCP批量读取及新分页/过滤协议 | 原生逐空间读取保留；没有代表性规模数据，不声称吞吐收益，也不新增接口平台 |
| 取消pepper、SHA-only或多管理员/在线恢复 | 本次统一PG HMAC，保留运维秘密边界；仅显式离线管理员轮换 |
| 通用同步/异步开关、额外Agent服务 | 空间生命周期仍异步；用户/Key同步；复用已有Agent监督器与原生Worker |
| 强行清除异常准入/未知执行者 | 不采纳；阻止破坏性清理是必要安全语义 |

## 4. 验证与交付边界

### 4.1 本轮已取得的证据

以下按测试快照分别记录，不把正在进行的最终复跑提前写成通过。最终交付清单应记录对应源码树/补丁和日志；新增修复后必须以最终复跑覆盖结果为准。

| 验证范围 | 已取得结果 | 解释 |
| --- | --- | --- |
| ContextDB 系统故事 | 最终65 passed、无跳过 | 独立服务进程、真实PG、原生SDK/REST/MCP、生产UI及两种Worker模式；含取消后执行者和同名缓存隔离 |
| UI→API 系统验证 | 2 passed | 实际UI服务端代理及工作空间/用户管理链路 |
| 原生 Worker | 167 passed | 原生领取/执行/重试/取消行为回归；新增执行屏障另有专项回归 |
| UI 单元回归 | 405 passed | 含可读标识、代次条件、选择器和原生入口调整 |
| ContextDB 扩展 | 最终438 passed、1 skipped | 含Webhook/trace/audit边界、真实HTTPS CA和部署合同；可选PG入口另有真实非超级用户服务链路验证 |
| 原生 Hindsight 系统故事 | 最终337 passed、1 skipped | 原生Worker钩子改动后的最终原生系统回归 |
| Web部署合同复核 | 24 passed、1可选测试跳过；私有CA真实HTTPS及UI Python探针通过 | 组件秘密挂载、身份状态、配置校验与密码持久化；不等同容器验收 |
| UI只读缓存 | UI独立64MiB tmpfs；UID10001写/删成功，图片远程URL仍400且未外联，cache异常消失 | 根FS和组件秘密仍只读；全发行安全扫描另验 |
| 容器构建及功能 | merged/split两模式通过，含页面/静态资源、组件只读秘密和Worker重启恢复 | 本机Colima须OPENSSL_armcap=0；3轮同预算结果不外推生产容量 |
| 专家检视 | Hindsight、PG、UI、Web及资料复核均ACCEPT批准的首版范围 | 每位评审的范围、已修复问题与环境限制分别保留；不以作者自测冒充独立复核 |

容器镜像及两模式功能已通过，但本机CPU兼容覆盖不能替代目标ECS原样启动验收；RDS中文全文路线有插件可用性/适配和恢复依赖。真实 MaaS 小样本探测不能证明通用准确率或生产容量。接口、UI、PG、模型连通、检索质量、容器和云上灾备分别验收。

### 4.2 原2026-10-16历史验收（保留）

下面仅为历史基线，不覆盖本轮第0节实现及收尾修复。后续代码已提交推送，2026-10-17曾部署验证，现已按用户要求停止并清理验证库。完整日志位于对应独立artifacts目录。原始dirty基线已保存，新增工作在独立worktree。四类专家复核均无剩余阻断；PG接受的边界是客户不得绕过服务进行并发DDL，以及旧deleted兼容清理三败后需所有者离线恢复。最终测试计数见[本次验收报告](../REVIEW-release-hardening-20261016.md)，过程中失败修复与最终结果分开记录。

历史本地模拟模型验证权限、路由、任务与资源生命周期；不据此宣称真实MaaS质量、中文全文检索效果、生产容量、HTTPS/突发限流、PGroonga故障恢复或云HA已通过。这些属于部署环境验收，不通过改应用代码伪装完成。

## 5. 阿里ContextDB实测证据（历史保留）

#### 环境和方法

- 日期：2026-10-16。
- 页面：阿里云 ContextDB，杭州区域，`research` 工作空间的 [用户管理页面](https://rdsnext.console.aliyun.com/cn-hangzhou/contextDbDetail/ws-8cc8o2zty2u47cz/userManagement)。该链接需要账号登录，仅用于定位本次观察环境。
- 使用用户已登录的 Chrome 实际操作页面；浏览器扩展连接超时后，改用桌面方式完成查看。
- 先查看已有成员的表单和确认弹窗，全部取消，没有修改已有成员或 Key。
- 后续创建专用临时成员 `ui-review-disposable-20261016`，角色为成员；初始 Key 名称为 `ui-revoke-test`。测试对象仅用于本次调研。
- 创建提交由用户在 Chrome 完成；吊销由助手在用户确认后完成。下一次连接时成员删除已完成，助手未再次点击删除，而是刷新及重新加载页面核验结果。
- 截图仅包含表单、脱敏凭据和列表结果，不保存完整 API Key。

#### 按钮与表单观察

| 操作 | 实际观察 | 验证程度 |
| --- | --- | --- |
| 新建成员 | 成员名称、管理员/成员；默认选成员 | 已打开表单并切换选项 |
| 同时生成初始 ApiKey | 默认选“是”，可填写初始 Key 名称；选“否”后隐藏名称框 | 已切换观察；临时成员按“是”创建 |
| 成员行展开箭头 | 在该成员行下展示 ApiKey 列表 | 已实际展开、收起 |
| 管理 ApiKey | 同样展开该成员的 Key 列表，不跳转独立页面 | 已实际操作 |
| Key 列表 | 名称、脱敏 Key、创建时间、最近使用时间、操作 | 已查看已有与测试 Key |
| 新建 ApiKey | 显示所属成员，只填写 Key 名称 | 已打开表单；没有通过该独立入口签发第二把 Key |
| 编辑 Key | 显示脱敏 Key、成员、状态；可修改名称，提示吊销需使用吊销按钮 | 已查看后取消，没有提交修改 |
| 角色设置 | 打开“编辑成员”，包含角色与状态；成员名称只读展示 | 已打开查看，没有提交变更或确认实际授权效果 |
| 角色说明 | 页面说明涉及工作空间成员、用户组及组管理员管理 | 已查看说明，不代表本次验证了这些权限 |
| 删除成员 | 确认框说明永久删除、其所有 Key 失效、不可恢复 | 已查看；后续核实临时成员删除结果 |
| 刷新 | 成员列表和展开的 Key 列表分别提供刷新按钮 | 已实际刷新 |
| 阿里云 UID 绑定 | 成员列表包含绑定信息；普通成员行的绑定按钮在本次页面中为禁用 | 仅观察，不纳入我们的首版设计 |

#### 测试时间线与结果

| 步骤 | 操作及结果 |
| --- | --- |
| A1 创建临时对象 | 用户提交新建成员。列表出现临时成员，角色为成员、状态可用，页面显示创建时间为 2026-10-16 10:26:20。 |
| A2 核对脱敏展示 | 展开临时成员，看到 `ui-revoke-test`，凭据显示为 `ctxdb-***b423a8`，最近使用时间为空。 |
| A3 实际吊销 | 打开吊销确认框；用户确认后，助手点击“确定”。Key 行从列表消失。 |
| A4 刷新 Key 列表 | 刷新后仍显示“没有数据”，没有留下“已吊销”的历史行。临时成员仍保留，状态可用。 |
| A5 成员删除确认 | 打开临时成员的删除确认框，提示永久删除及全部 Key 失效。 |
| A6 核实成员删除 | 用户确认后，助手重新连接时弹窗和临时成员已不存在。刷新成员列表并重新加载页面，临时成员仍不存在，原有三名成员保留；分页按钮均禁用。 |

**界面结论：** 吊销相当于从用户日常管理视图中删除一把凭据；删除成员则移除成员及其管理入口。界面不要求用户理解数据库中的吊销、软删除或审计状态。

#### 没有验证的事项

- 未使用测试 Key 发业务请求，未验证吊销前后 HTTP/MCP 鉴权结果。
- 成员删除前，其唯一测试 Key 已吊销，未验证“删除成员使未吊销 Key 失效”的链路。
- 创建由用户提交，助手没有直接观察创建成功时的完整 Key 弹窗；不能把“明文仅展示一次”写成本次 UI 已实测结论。
- 未测试实际角色变更、成员停用/恢复、管理员的权限边界、Owner 保护规则。
- 未查看阿里服务端数据库或实现，不能从 UI 行消失判断物理删除或历史保留方式。

#### 截图证据

截图保存在资料仓库中，避免依赖 `/tmp` 临时文件。它们包含登录后的成员元信息，分享范围应与该资料仓库一致；不是完整密钥备份。

| 证据 | 内容 |
| --- | --- |
| [E1 新建成员待提交](evidence/alibaba-user-management-2026-10-16/contextdb-ui-test-create-confirmation.jpg) | 临时成员名称、成员角色、初始 Key 名称 |
| [E2 吊销确认](evidence/alibaba-user-management-2026-10-16/contextdb-ui-test-revoke-confirmation.jpg) | 明确吊销对象及不可恢复提示 |
| [E3 吊销后列表](evidence/alibaba-user-management-2026-10-16/contextdb-ui-test-revoked-result.jpg) | 成员保留，Key 列表为空 |
| [E4 删除成员确认](evidence/alibaba-user-management-2026-10-16/contextdb-ui-test-delete-confirmation.jpg) | 成员名称及永久删除提示 |
| [E5 删除后列表](evidence/alibaba-user-management-2026-10-16/contextdb-ui-test-deleted-result.jpg) | 临时成员消失，原有成员保留 |

#### 官方资料补充

以下资料用于确认公开接口语义，与上述实际 UI 观察分开记录：

- [创建成员](https://help.aliyun.com/zh/rds/developer-reference/api-rdsai-2025-05-07-createcontextdatabasemember)：公开角色包含 owner/admin/member，支持可选签发初始 Key；文档说明明文仅在该次创建响应返回。
- [创建 API Key](https://help.aliyun.com/zh/rds/developer-reference/api-rdsai-2025-05-07-createcontextdatabaseapikey)：请求包含工作空间、成员和 Key 名称。
- [吊销 API Key](https://help.aliyun.com/zh/rds/developer-reference/api-rdsai-2025-05-07-revokecontextdatabaseapikey)：响应包含 `Status=revoked` 和 `RevokedAt`。这些字段不证明其底层采用哪种删除方式。
- [列出 API Key](https://help.aliyun.com/zh/rds/developer-reference/api-rdsai-2025-05-07-listcontextdatabaseapikeys)：列表不返回明文。吊销后从 UI 消失的结论来自 A3/A4，不单凭该接口示例推断。
- [权限管理](https://help.aliyun.com/zh/rds/apsaradb-rds-for-mysql/permission-management)：阿里还有工作空间角色、用户组和资源授权等机制。本轮不复刻这些能力。

本轮详细结果、过程中失败与复验、云上前提统一见[夜间验收报告](../REVIEW-service-night-20261017.md)。14管理操作curl已在独立真实源码服务按文档执行；最终MaaS merged/split服务链路及Worker停止/重启排空通过。ContextDB最终全量系统65项通过，无跳过；此前2个旧Trace非空断言已按首版关闭合同修正，全量复跑通过，保留中间失败日志。
