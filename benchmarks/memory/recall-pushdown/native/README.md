# 实验性 PG 扩展源码

> 2026-11-20 归档说明：本文件保留当时的阶段记录（含“未提交/未推送”状态）。当前维护、发布与验收状态以[统一入口](../README.md)、当前进展和远程分支 HEAD 为准；代码发布不表示剩余验收通过。

- `contextbase_recall.c`：通用 C RRF/Top-K；本轮未修改融合公式，预算函数未接入当前 Recall。
- `contextbase_legacy_order.c`：临时复现原 Python 图检索的 UUID 字符串集合顺序。仅针对 CPython 3.11、64 位 SipHash13、`PYTHONHASHSEED=0`；实际回归解释器为 3.11.15。不是通用相关性策略，也不依赖 PG 内加载 Python。
- `LICENSE.cpython`：集合与哈希兼容算法的上游许可证。

实际开发源码位于私有 PG 工作区 `ContextDB-Research/.local-archive/recall-pushdown-20261119/pg-source/contrib/contextbase_recall/`。此处将对应源码与ContextBase/SQL纳入同一个commit，作为本次可审查、可构建的交付入口；文件与开发工作区逐字一致，不提交编译产物。原 PG 核心目录未改。完整清单见[提交源码清单](../evidence/commit-source-manifest-20261119.json)。

构建需要与目标 PG 匹配的开发头文件和 PGXS，在本目录执行：

```sh
make PG_CONFIG=/path/to/matching/pg_config
```

安装实验环境时使用独立、带版本的库名；不能覆盖正在被后端加载的动态库。C 函数必须由 DBA 显式注册，使用 SECURITY INVOKER、收回 PUBLIC 权限，再部署 [PG SQL](../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql)。该 SQL 依赖已注册的 `recall_probe.rrf_topk`、`recall_equiv.legacy_set` 和 `recall_equiv.legacy_union`；它不是一键生产安装脚本。

当前后端选择器为 `hindsight_api.engine.memories.pg.recall_pushdown:EquivalentPostgresRecallMemories`，采用标准 `HINDSIGHT_API_MEMORIES_EXTENSION` 和限定 Bank 的扩展配置。未支持形状在查询前退出接管，由原 store 处理；查询已开始后的错误会暴露，不静默重跑。不能直接替换生产服务配置。

## 第三阶段：精确 OR 评分快速路径

新增 `contextbase_rank_cd_or.c`，本目录为其开发源码；上面列出的两份首版 C 文件保持不变。它专门加速 PostgreSQL 两参数 `ts_rank_cd(tsvector, tsquery)` 的默认权重、无归一化形式，不是 BM25。

对无前缀、无词项权重约束的纯 OR 查询，每个最小覆盖是一处命中的词项位置。因此可以直接累加默认位置权重，避免构造/排序文档位置表示并反复解释查询树。重复查询词只计算一次；词项位置权重仍保留。AND、NOT、短语、前缀、词项权重或超过快速路径大小上限的查询都调用 PG 原函数。

缓存仅保存当前表达式的查询结构，在表达式内存上下文释放，不缓存文档、分数或测试题答案。当前目标为独立 PG 18.4；对应新适配为 `hindsight_api.engine.memories.pg.recall_rank:RankJsonPostgresRecallMemories`。它复用首版 C RRF，没有实现跨路并行。

构建新模块后，DBA 应以独立版本路径注册，不覆盖原有模块：

```sql
CREATE SCHEMA recall_rank;
CREATE FUNCTION recall_rank.rank_cd(tsvector, tsquery) RETURNS real
AS '/absolute/path/to/versioned/contextbase_rank_cd_or', 'contextbase_rank_cd_or'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE COST 1;
```

再部署 `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank_json.sql`。该候选入口返回 JSON，P3 的内部状态仍为 JSONB；候选、分数、原文和预算没有裁剪变化。chunk 键按原 JSONB 顺序输出。注册后按本地服务角色授予 schema USAGE、函数 EXECUTE，收回 PUBLIC 的函数执行权限。

`test_rank_cd.sql` 是可重复的字节相等检查，覆盖重复位置、权重、Unicode、空值和回退查询。阶段测试另有 50,480 个真实向量/查询组合及 7,560 个生成用例，均使用 `float4send` 比较；阶段性结果和待验证项见 [性能阶段交付](../beam1m/phase3-performance.md)。

## 当前维护约定

本目录是三个 C 模块的统一维护源码。上文私有 PG 工作区仅说明首版来源，不再作为另一份维护主源。安装步骤与权限见 [RUNBOOK](../RUNBOOK.md)，显式安装脚本为 [install.sql](install.sql)；SQL / PLpgSQL 保留在 ContextBase 运行时目录，通过相对引用部署。
