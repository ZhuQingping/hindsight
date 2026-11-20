# PostgreSQL Recall 下推：代码、进展与使用入口

更新：2026-11-20。维护仓库：[ZhuQingping/hindsight](https://github.com/ZhuQingping/hindsight/tree/memory-benchmark/benchmarks/memory/recall-pushdown)，分支 **`memory-benchmark`**。

**已实现一次 PG 候选调用：四路检索 → C RRF / Top-K → 候选与原文补全；rerank、最终评分和 Token 预算仍在 ContextBase，接管成功后不再补查 PG。** 本目录保存可构建的 PG C 插件、设计、使用手册、验证工具和脱敏证据；依赖的 SQL / PLpgSQL 只有一份，继续保留在 ContextBase 运行时代码中。

## 当前进展与实测收益

| 同一冻结 BEAM 会话，排除模型的 Recall 核心 HTTP 路径 | 平均 | P50 | P95 |
| --- | ---: | ---: | ---: |
| 原流程，关闭下推 | 53.48 ms | 49.18 ms | 125.24 ms |
| 上一版 P3 下推 | 53.06 ms | 52.55 ms | 66.87 ms |
| 当前性能版 `rank_json` | **44.75 ms** | **43.16 ms** | **58.74 ms** |

相对原流程，平均降低 **16.3%**，P50 降低 **12.2%**。每组 400 次测量，三个独立 API 进程与外部客户端交错执行；全部 1,200 次响应一致。P95 包含 Python GC 影响，不能全部归因于 PG。20 题中 17 题平均改善、3 题退化，尚未达到平均/P50 各下降 20% 的阶段目标。

**上述不包含在线 embedding、真实 BGE 和 ContextBase 完整业务鉴权层，不是完整生产 Recall 的提速结论。** 当前版本真实 BGE 仅完成 3/20 题，其余 17 题待验；没有新增准确率或 Token 节省结论。BEAM 1M 指约百万输入 Token，本次为一个完整会话、2,524 条事实，不是百万向量。详见 [性能报告](beam1m/phase3-performance.md) 和 [逐次测量](beam1m/phase3-evidence/external-http.json)。

## 实际做了什么

```text
ContextBase：鉴权、配置、query embedding
                    |
                    | 一次参数化候选 SQL
                    v
PG：原四路检索 -> C RRF / Top-K -> 候选、关联原文一次返回
    全文 OR 精确评分快速路径       最终直接生成 JSON
                    |
                    v
ContextBase：原 BGE rerank -> 原评分、事实/原文预算 -> 响应
```

第一版完成结果等价适配；BEAM 版补齐混合事实类型、查询词选择和时间处理，并用类型数组减少中间 JSON 开销。当前性能版进一步优化全文 OR 评分和最终 JSON 生成。**没有新增跨路并行、动态剪枝、BM25 或 PG 调用模型；PG core 没有修改。** 未满足支持条件时在候选查询前退出接管；查询已经开始后的错误会暴露，不静默再跑原流程。

## 从哪里开始看

| 目的 | 入口 |
| --- | --- |
| 构建、部署到独立测试库、开启/关闭、复测、回退 | [使用手册](RUNBOOK.md) |
| Agent 或同事交接，确认当前状态和操作边界 | [Agent 交接说明](AGENT_HANDOFF.md) |
| 已完成、未通过与待验项 | [当前进展](progress.md) |
| 下一步工作和验收标准 | [实施计划](plan.md) |
| 两边代码及设计契约 | [当前设计](DESIGN-CURRENT.md) |
| 当前测量、逐题差异与限制 | [性能报告](beam1m/phase3-performance.md)、[HTML](beam1m/phase3-performance.html) |
| PG C 插件 | [native](native/README.md)、[构建文件](native/Makefile)、[显式安装脚本](native/install.sql) |
| SQL / PLpgSQL 与 Python 接管 | [ContextBase PG 存储层](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/) |
| 首版 LoCoMo 81 题等价验证 | [原始 / 关闭 / 开启三组对照](three-way-original-compatibility.md) |
| 早期 BEAM 实验及曾经没有收益的记录 | [BEAM 历史报告](beam1m/BEAM1M-Recall下推性能验证报告.md) |

## 目录约定

- `native/`：PG C 插件源码、许可证、PGXS 构建和数据库级测试；不提交动态库。
- `beam1m/`：数据规模、设计与历史实验；`phase3-evidence/` 为当前性能版脱敏测量，不包含事实正文、查询向量或完整回包。
- `evidence/`：首版 SQL、契约及 LoCoMo 回归证据，保留历史失败记录。
- ContextBase 运行时代码中的 `recall_*.sql` 是 SQL 的唯一维护位置，本目录通过链接和安装脚本引用，不再复制一套。
- 数据快照、模型、凭据、进程日志、完整响应存放在 gitignored 私有目录，换机器需另外准备，不能从代码仓恢复真实数据。

首版原提交 `05d2894c5` 和性能前基线 `4016fed9b` 均保留。当前发布是**实验代码与证据归档**，不等于生产验收；未切换原 LoCoMo 或现有常规服务。本次之后不自动继续性能研发。
