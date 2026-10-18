# 2026-10-17 服务化夜间任务验收

2026-10-18补充：本报告下方记录夜间验收时的代码快照，之后用户确定首个正式版本的管理元数据从1开始。当前代码/设计已重定为首发结构1，开发期旧结构不自动升级；初始化、管理员离线轮换与运行统一使用HINDSIGHT_API_DATABASE_URL。本次调整的回归结果另见优化状态文档。夜间原有测试计数及镜像指纹不改写为重定基线后的证据。

本轮基于 `1e188ac306b85f6f58699592aae80bd0880c8864`，工作分支 `contextdb/service-night-20261017-225618`。代码和文档留在独立 worktree，未提交、未推送；原始设计及优化清单已归档，用户编辑的 drawio 文件未改动。

## 已完成的改动

- 新空间统一 `name=bank_id=jiamu`、schema=`ctxdb_ws_jiamu`；内部 UUID 负责授权、异步执行及对象代次。输入规范化为小写，限 `[a-z][a-z0-9_]{0,53}`，不新增改名接口。
- 管理 GET/DELETE、授权选择、原生 REST/SDK/MCP 和 UI 使用同一个可读标识。DELETE 必须携带含 UUID/版本的 ETag；selected 授权可指定预期 UUID，UI 始终发送，防止旧选择授权给同名新对象。
- 正常删除物理清理 schema、空间和关联授权；彻底排空旧请求、任务及迁移执行者后允许同名重建。旧的 selected 授权、旧删除重试及旧 Worker 不继承新空间身份；all Key 按既定语义可以访问未来新空间。
- 原生取消只修改任务状态，新增可选 Tenant Worker 执行上下文，覆盖真实执行直到最终状态写入。其他 Tenant 默认空实现。未知失败保留删除屏障，不能用 TTL 强制视为安全。
- 同名重建首次访问/UUID变化时，在扩展层失效当前进程的原生 profile/config 缓存；同代继续命中原生缓存，不新增PG表或核心缓存实现。真实 Worker 提示词验证不携带旧 mission；独立复核见 `review-cache-independent.md`。
- 元数据升级到4，旧库保留原 Bank ID/schema/数据；不自动重命名。升级前旧版排空原生 pending/processing，再停止所有写入者、备份和离线迁移；不允许运行时无身份启动迁移。
- 新增类型化部署意图、配置渲染/校验/状态命令、PG准备脚本、同源容器和 Compose。复用已有节点 Agent 监管前台进程，不新增实例管理 HTTP 守护进程。

## 文档入口

| 读者/用途 | 文档 |
| --- | --- |
| 管控、节点开发和集成人员 | [部署集成指南](docs/contextdb-service-integration-guide.md) |
| 节点 Agent 自动化 | [配置合同](docs/contextdb-deployment-contract.md)、[意图模板](deployment/intent.example.json) |
| 架构及详细实现 | [完整设计](docs/contextdb-release-design.md)、[优化状态](docs/contextdb-optimization-status.md) |
| 管理与业务 API 验证 | [14接口 curl 手册](docs/contextdb-optimized-curl-guide.md)、[OpenAPI](docs/contextdb-control-plane.openapi.yaml) |
| 值班、排障、备份和升级 | [运维手册](docs/contextdb-operations-runbook.md) |
| 拓扑、MaaS、全文方案与许可 | [补充调研与实测](docs/contextdb-service-research-validation.md) |

## 验证结果

| 范围 | 结果与证据 |
| --- | --- |
| ContextDB 扩展单元/真实隔离PG | 438通过、1跳过；`extension-acceptance.xml` |
| 原生 Hindsight 系统故事 | 337通过、1跳过；`native-system-final.xml` |
| 原生 Worker/执行保护/墙钟超时 | 167通过；`native-worker-final.xml` |
| 其他原生配置/检索等针对性单测 | 274通过；`native-unit.xml` |
| UI组件及代理单测 | 405通过；`ui-integrated.log`，独立UI专家另行复验 |
| ContextDB系统全量 | 最终65通过、无跳过；`system-acceptance.xml`，包含两种Worker模式、生产UI、取消后的实际执行者及同名重建缓存。此前2个旧Trace非空断言与首版关闭合同不符，修正断言后全量重跑通过；中间失败日志仍保留 |
| 最终生产UI到真实API | 两种Worker模式2通过；`ui-final-system.xml`。同版构建与源码指纹一致 |
| 文档中的管理命令 | 14管理操作按文档顺序在独立真实服务执行通过，连同PG只读核对；`curl-guide-probe-final.log` |
| MaaS完整链路 | merged/split均通过异步Retain、中英Recall和Reflect；非超级用户服务角色；重复init保留秘密；split Worker独立停止及稳定ID重启排空通过；`live-maas-service-final.json` |
| 全文及逻辑恢复 | PG18.4、PGroonga4.1.0；12条材料/7查询的SQL对照，pg_dump/restore后数据与结果一致；`fulltext-sql-probe.json` |
| 部署CA/秘密/状态 | 合同单测及真实HTTPS私有CA回归通过；未配置CA失败，配置后Python探针及身份校验成功；不关闭TLS |
| UI只读缓存与依赖适用性 | 最终镜像负对照：远程图片请求400、受控目标命中0；当前无remotePatterns，不满足已审视SSRF条件。UI增加64MiB缓存tmpfs后UID10001可写且mkdir异常消失；`review-ui-cache-tmpfs.md`、`review-runtime-dependencies.md` |
| 静态检查 | 仓库lint、扩展ruff/ty、OpenAPI生成/合同、Markdown代码块静态检查通过 |
| 容器及同预算对照 | 同源镜像构建成功；两模式功能及3轮对照通过，split Worker停止/重启恢复通过，无OOM；`container-topology-pilot-result.json`。本机须OPENSSL_armcap=0兼容覆盖，原样ARM启动未通过，见下文边界 |

上述测试有交叉覆盖，不将各行简单相加。系统测试使用真实进程与发布SDK，模型行为多数由本地确定性服务提供；真实MaaS调用另列；该链路运行早于最后的缓存隔离修复，缓存修复由真实PG、原生Worker和本地模型服务的全量回归覆盖，未重复消耗MaaS配额。仅本机Python3.11/PG18.4及列明环境验证，不冒充全部Python/PG版本矩阵。

## 专家评审

Hindsight、Web、UI、PG专家已分别ACCEPT批准的首版范围；资料复核也已ACCEPT。保留每位评审的文件快照、独立测试和历史问题，报告位于本轮artifacts的 `review-hindsight.md`、`review-web.md`、`review-ui.md`、`review-pg.md`、`review-docs.md`。原取消任务跨代晚写P0已通过真实WorkerPoller、native.cancel_operation和PG删除/重建的独立复现验证关闭。

容器负对照进一步发现Next在拒绝图片请求前初始化缓存，原只读根FS产生mkdir异常；已在Compose只给UI增加64MiB可丢弃tmpfs，保持根FS/秘密只读，使用默认UID10001独立复验通过。负载对照早于该挂载补充；缓存修复以单独真实容器回归验收，未重复运行API负载。

容器构建暴露的Python解释器选择问题已修：build-ui明确使用 `/app/.venv/bin/python`。依赖下载使用 BuildKit 缓存，npm 安装关闭 audit/fund 联网；依赖漏洞扫描仍是单独的发行门禁，本轮未声称通过安全审计。本地依赖下载使用测试专用代理及HTTPS源；保留TLS/GPG验证，与正式Dockerfile差异单独记录，不能将测试环境代理地址作为客户配置默认值。固定Next.js包采用测试专用Range下载并按锁文件SHA512校验后加入内容缓存，未替换依赖。

镜像ID为 `sha256:d2fbdb1396d1c53e4b6377d8a477b6781d88151cb1650cc2c91680b9a8e4d8bb`；应用源码指纹 `868c921d80594a7555b01f4302e356e360aa5ad25f5232fff9918d6d1fece585` 与当前源码及UI产物一致。性能数值和条件见[补充调研第6节](docs/contextdb-service-research-validation.md#6-容器功能与同预算小样本对照)。

## 上线前仍需确认的边界

1. 独享服务推荐同ECS分容器，合并模式保留给小规格。按实际规格压测容量；源码MaaS小样本和确定性容器对照不能证明生产SLA。
2. 本机中英文使用PGroonga；云RDS的固定中英文方案仍取决于实际插件能力和许可/恢复验收。Groonga为LGPL-2.1-or-later，不是另一个必须CREATE EXTENSION的PG插件；native+zhparser仍有mental_models适配工作，不能只设置一个变量宣称已支持。
3. 首版关闭原生持久LLM Trace、原生业务Audit、Webhook，防止未受保护的独立后台写入跨代落入新schema；相应配置或遗留启用行拒绝启动/迁移。ContextDB管理审计、JSON日志、指标、按需OTEL继续可用。此取舍应在产品验收时明确。
4. 未知旧执行者保守阻止删除，需要运维证明退出后定向恢复；不提供一键清空准入表。PG超级用户、数据库/主机所有者可破坏服务，普通SQL账号隔离不能变成防root承诺。
5. 当前Colima ARM原样镜像在cryptography/OpenSSL导入时SIGILL；仅测试覆盖OPENSSL_armcap=0后容器链路通过。正式镜像未默认加入覆盖，目标ECS架构/原样启动仍须验证。依赖漏洞扫描也不能以功能通过代替，初始npm全工作区审计69项（含1 critical）未完成全量归因；一次有界UI运行期复核未发现已证明的P0/P1，但不能当作全依赖/最终镜像扫描通过。Next16.3.7版本命中[已审视SSRF公告](https://github.com/advisories/GHSA-cjq9-62q9-8jv4)，当前无remotePatterns，必要条件不成立，真实镜像负对照未外联。
6. 本轮未验收目标RDS主备/PITR、生产并发、外部TLS入口和云上HA；未创建付费云资源。

测试数据与服务仅属于本轮。临时PG数据目录在停止后清理，保留日志/XML；原生单测曾启动默认PG0夹具5556，已停止，未删除其目录。原有PG5432保持运行，未修改其全局配置或重启。
