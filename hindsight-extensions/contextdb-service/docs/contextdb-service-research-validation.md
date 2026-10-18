# 服务化补充调研与验证记录

2026-10-17。本轮代码基于 `1e188ac306b85f6f58699592aae80bd0880c8864`，独立工作分支 `contextdb/service-night-20261017-225618`。本文区分实际验证、工程选择和云上前提，不能作为生产容量承诺。下列夜间模型/容器实测对应00a921b52快照；之后管理元数据重定首发1，未将这些旧结果改写为新基线的容器实测。

## 1. API 与 Worker 的选择

**独享服务推荐同 ECS 分容器部署 API、Worker、UI；保留合并模式用于小规格及本地验证。** 理由是可以独立限制后台资源、重启 Worker、观察积压；不是已经证明拆分吞吐更高。同 ECS 仍是同一节点故障域，PG 和 MaaS 配额也共享。

| 比较项 | API 内置 Worker | 独立 Worker 容器 |
| --- | --- | --- |
| 开通及资源成本 | 少一个进程及连接池 | 多一个进程及连接池，需单独预算 |
| 后台任务与请求 | 同进程；进程重启时一起中断 | 可以独立重启及限额；Recall/Reflect 仍在 API 运行 |
| 异步任务交接 | 内置 poller 领取 PG 队列 | 独立 poller 领取同一个 PG 队列，不经过 Agent 转发任务 |
| 工作空间创建/删除 | API 的扩展生命周期执行器 | 仍由 API 执行，不迁到记忆 Worker |
| 运维 | 单进程简单 | Worker 停止时 API 可继续处理查询，异步写入等待；必须监控队列 |
| 高可用 | 需管控和节点 Agent 另外实现 | 分离本身不提供节点高可用 |

两种模式均已通过真实 API/原生 Worker 的扩展系统故事，包括权限隔离、在途请求排空、取消后的真实执行者退出、删除及同名重建。生产 UI 到 API 的创建、授权、业务写入和清理也覆盖两种模式。官方机制见 [Services](https://hindsight.vectorize.io/developer/services)。

部署输入显式指定 `topology`，不使用隐藏默认值；详见[人用集成指南](contextdb-service-integration-guide.md)和[Agent 合同](contextdb-deployment-contract.md)。推荐不替代目标 ECS 规格的容量测试：必须固定总 CPU/内存、相同 PG、数据、模型及配额，测混合写入/查询 p50/p95、任务积压、连接数、CPU/内存和限流。源码进程烟测与远端模型调用耗时不能冒充这个对照实验。

## 2. MaaS 模型

首版固定 `deepseek-v4.1-flash + bge-m3 + bge-reranker-v2-m3`，客户不选择模型。分别复用原生 OpenAI LLM、OpenAI Embeddings、SiliconFlow Rerank 适配，无须新增 MaaS Provider。

| 本轮实际探测 | 结果 | 结论的边界 |
| --- | --- | --- |
| DeepSeek v4.1 Flash | 中英两例均 HTTP200，直接 JSON 结构两例通过；耗时中位数3.550秒 | 每模型仅两例，不代表准确率排名 |
| GLM 5.3 | 两例 HTTP200；一例带 Markdown 代码围栏，不符合本探测的直接 JSON 要求；中位数6.704秒 | 未完整评测 Hindsight 的容错解析，不能据此说 GLM 不可用 |
| bge-m3 原生适配 | 自动识别1024维；两条输入各1024维 | 不发送 `dimensions`，新库须按1024维初始化 |
| bge-reranker-v2-m3 原生适配 | 返回两个分数，相关文档排在前面 | 请求字段是 `query`，历史 `input` 示例实际返回400 |

上述延迟含当前网络和服务排队，不是模型本身的固定延迟。完整质量评测应覆盖事实抽取、合并、检索和 Reflect，并使用独立评判模型或人工标注；本轮没有完成这样的准确率基准。

实际源码部署使用专用非超级用户 PG 账号、PG18.4、PGroonga4.1.0，并执行重复离线初始化、原生异步 Retain、中英 Recall 和 Reflect。逐模式结果见本轮验收报告；不能用单独三个模型 HTTP200 代替服务链路通过。

## 3. 中英文全文路线

**英文可以直接使用 native；云上中英文方案尚有 RDS 插件前提，不能宣称已经定为 PGroonga。** 本机中英文功能验证继续使用已安装的 PGroonga，平台产品组合仍需确认。

| 路线 | 适配成本 | 服务化前提 |
| --- | --- | --- |
| native + english | 已支持，最低 | `vector/pg_trgm/btree_gin`，仅英文全文验收 |
| native + zhparser | 中等；普通记忆已有 language 入口，但 mental_models 仍有固定 english 的 DDL/查询 | RDS 确认可用；统一中文配置、索引重建和预检后才能交付 |
| PGroonga + Groonga | 已有 Hindsight 适配，应用修改少 | PG 侧支持插件及系统库；核查许可证、WAL、恢复和主备 |
| pg_textsearch + zhparser | 中等；当前 Hindsight 英文配置需参数化 | 目标 PG 同时提供两个插件；验证中文 text_config 与 BM25 |
| pg_search + 中文 tokenizer | 已有适配 | 确认实际发行物含 tokenizer，并解决 AGPL/商业授权和 RDS 支持 |

`vector` 是向量检索；`pg_trgm` 是相似度/模糊匹配；`btree_gin` 是标量类型 GIN 操作符类。它们不是三套中文分词方案。

PGroonga 使用 PostgreSQL License，Groonga 官方说明为 **LGPL-2.1-or-later**；不能写成“依赖 GPL 因此不能商用”。pg_search 社区源码为 AGPL-3.0，也不是无许可证义务的替代品。pg_textsearch、zhparser/SCWS 分别采用其宽松许可证。具体交付义务取决于锁定版本、修改和交付方式，详见[设计中的许可与候选方案](contextdb-release-design.md#fulltext-selection)及原始来源：[PGroonga](https://github.com/pgroonga/pgroonga/blob/main/COPYING)、[Groonga](https://groonga.org/docs/reference/api/index.html)、[pg_search](https://github.com/paradedb/paradedb/blob/main/LICENSE)、[pg_textsearch](https://github.com/timescale/pg_textsearch/blob/main/LICENSE)。

华为云[公开插件清单](https://support.huaweicloud.com/intl/zh-cn/usermanual-rds-pg/rds_09_0045.html)列有 zhparser，本轮未查到另外三个全文插件。须由 RDS 同事确认实际区域、PG版本和 `pg_available_extensions`；公开清单未列出不能替代最终平台结论。不能将插件装在 Hindsight ECS 上来解决外部 RDS 缺插件的问题。

### 本机 SQL 对照及恢复

在独立 PG18.4 数据库放入12条中英材料，执行7个关键词查询。native 使用 Hindsight 当前的 English AND 查询，PGroonga 使用其分词后 OR 候选，**语义不同，不据此给出优劣排名**：

- 三个中文查询，English native 未召回标注材料；PGroonga Top5 包含标注材料，部分查询也有额外候选。
- 两个英文、一个标识符、一个模型名称查询，两条路线均召回标注材料。
- `pg_dump` 后恢复到独立数据库，12条数据及7个查询结果与恢复前一致。

这证明当前环境的基础关键词能力与逻辑备份恢复，不证明大样本质量、索引膨胀、生产 p95、异常退出、PITR 或 RDS 主备切换。PGroonga 的流复制/WAL要求应按其[官方说明](https://pgroonga.github.io/reference/streaming-replication.html)另验。

## 4. 删除重建保护与首版限制

可读 `bank_id=jiamu`、schema=`ctxdb_ws_jiamu` 可以在彻底删除后复用，内部 UUID 永不沿用。业务 Key 的 selected 授权绑定 UUID，DELETE 的 ETag 包含 UUID及版本。旧的 selected 授权、旧删除重试和旧 Worker 不能获得新对象身份；all Key 仍按既定语义访问未来新空间。

原生取消接口只修改任务状态，不保证实际 LLM/批次已经退出。因此新增可选 Worker 执行上下文，扩展持久准入覆盖**实际执行直到最终状态写入**。未知失败保留屏障；不能用任务表的 cancelled 或固定 TTL 推断旧执行者已退出。其他 Tenant 扩展默认空实现，不改变原生执行语义。

原生启动迁移和独立后台正文写入没有上述身份保护，首版明确收敛：

| 功能 | 首版约束 |
| --- | --- |
| 启动自动迁移 | 固定 `RUN_MIGRATIONS_ON_STARTUP=false`；初始化及升级离线显式迁移目标schema |
| 原生 Webhook | 不支持；非空 `WEBHOOK_URL` 拒绝启动；旧库 enabled webhook 必须先停用 |
| 原生 LLM 调用正文表 | `LLM_TRACE_ENABLED=false` 必填；缺省原生值为true，因此缺省也拒绝 |
| 原生业务审计正文 | `AUDIT_LOG_ENABLED=false`；禁止 Bank/默认模板重新开启，旧 Bank 开启时启动/迁移拒绝 |
| ContextDB 管理审计 | `ctxdb_meta.audit_events` 继续在管理事务中记录，不受以上限制影响 |

UI 中原生调用正文和原生业务审计不会产生新记录。运行期 JSON 日志、任务状态、PG统计、指标和按需 OTEL 仍可用于定位；详见[运维手册](contextdb-operations-runbook.md)。这些限制针对尚未接入代次保护的写入路径，不通过删除原生表或修改记忆算法实现。

## 5. 最终源码服务烟测实录

以下每模式仅一条中英材料，模型与网络延迟会波动，不能按表内差值推断拓扑性能优劣。两模式均使用相同模型组合、独立空间及同一专用PG库；非容器配额对照。

| 模式 | API就绪 | Retain至任务排空 | 中文Recall | 英文Recall | Reflect |
| --- | --- | --- | --- | --- | --- |
| merged | 6.058秒 | 26.408秒 | 2.472秒/4条结果 | 1.339秒/4条结果 | 15.700秒/非空回答 |
| split | 7.029秒 | 13.504秒 | 5.987秒/4条结果 | 2.806秒/4条结果 | 16.613秒/非空回答 |

重复init保留原管理员及秘密。split模式停止Worker后API仍ready，异步Retain等待；相同稳定Worker ID重启后完成写入与合并。两模式结束均通过管理API清理测试工作空间。最终源码同版UI和14管理操作curl另行验证，详见验收报告。

## 同名重建的进程缓存处理

原生 Bank profile/config 缓存按(schema,bank_id)保存；删除只失效执行删除的进程，独立Worker可能在原生30秒TTL内持有旧配置。仅保护PG数据和任务不足以解决这个问题。

扩展层在每个进程记住最近见到的工作空间UUID，首次访问或UUID变化时调用原生缓存失效方法；同一代次继续使用原生缓存。HTTP/MCP认证、Worker完整执行准入和内部任务提交入口均覆盖，映射有界，不新增PG表或客户参数。PG统计缓存实际保存在业务schema表中，随DROP清理，无须一并禁用。测试使用1小时缓存TTL，通过真实API/Worker验证新空间的抽取提示词不含旧空间mission。


## 6. 容器功能与同预算小样本对照

最终同源镜像已构建，镜像内应用指纹与集成源码一致，UI产物校验通过。两种模式均通过离线初始化、API就绪、UI页面与静态资源、密码登录、管理代理，以及两个空间的异步Retain和Recall；split还通过Worker健康检查、停止Worker后API继续ready、相同Worker ID重启后排空。实际使用只读rootfs及按组件分开的只读秘密挂载，无OOM；测试对象已清理。后续图片入口负对照发现Next缓存mkdir日志异常，Compose补UI独立64MiB tmpfs后另行通过默认UID10001的真实镜像复验；负载样本运行早于该挂载补充，不将单项复验写成重新跑了负载。

**本机兼容条件：** 当前Colima ARM默认启动在cryptography50.0.0自带OpenSSL4.0.1导入时SIGILL；仅本轮测试使用 `OPENSSL_armcap=0` 后通过。正式镜像没有写入该覆盖，目标ECS默认启动尚未验收。诊断命令及OpenSSL官方说明见[运维手册](contextdb-operations-runbook.md)。不能把带兼容覆盖通过写成所有ARM机器原样可用。

预算为 merged API+内置Worker合计2CPU/4GiB；split API1CPU/2GiB加Worker1CPU/2GiB；两组UI各0.5CPU/512MiB。PG与本地确定性模型服务在预算外。每进程连接池上限6，split总连接预算较大；不是仅改变进程数量的严格因果实验。Mac绑定卷使用UID501/GID20，临时PG使用本机管理账号，运行期最小数据库权限另有专用服务角色链路验证。

每组8次预热写入后，执行3轮，每轮40次只读Recall、24次异步Retain与40次混合Recall；split另有1次Worker重启验证写入。模型服务人为延迟LLM50ms、Embedding20ms、Rerank10ms，仅验证机制。

| 指标：3轮各自统计的范围 | merged | split |
| --- | --- | --- |
| 只读Recall P50 | 76.0～81.1ms | 76.5～81.5ms |
| 混合Recall P95 | 169.3～184.9ms | 95.1～103.5ms |
| Retain接受 P95 | 42.4～47.4ms | 39.7～45.3ms |
| Retain至完成 P95 | 333.9～360.8ms | 337.2～353.1ms |

该环境中split混合查询尾延迟较低，只读及写入完成延迟相近；数据量、并发、顺序、连接数、CPU兼容覆盖和远端模型条件均限制结论，不能外推生产规格或SLA。独享版优先分容器的主要理由仍是资源限额和独立恢复，合并模式仍适合小规格。完整原始结果见本轮artifacts的 `container-topology-pilot-result.json`，源码烟测、真实MaaS和容器stub结果分别保留。
