# 实验性 PG 扩展源码

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
