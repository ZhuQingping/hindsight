# 当前性能阶段交接入口

2026-11-20。当前归档到 `ZhuQingping/hindsight` 的 `memory-benchmark`；状态为实验版，停止后续研发，等待人工及剩余真实 BGE 测试。完整交接以[统一 Agent 说明](../AGENT_HANDOFF.md)和[使用手册](../RUNBOOK.md)为准。

当前平均 53.48→44.75 ms、P50 49.18→43.16 ms，排除模型。真实 BGE 仅完成 3/20。无新跨路并行，未切换常规服务或 LoCoMo。测量范围和限制见[性能报告](phase3-performance.md)。

发布前的私有 `phase3/handoff/phase3-base.bundle` 和 `phase3-uncommitted.patch` 是当时交接备份；当前远程提交已经包含这些代码，**取得当前分支后不要再次应用旧 patch**。数据库快照、向量、模型与凭据仍需私下另行准备，不在 Git 中。

最终 v2 仅修补查询缓存错误路径，全部评分位比较重跑；整轮时延与 3 题 BGE 是 v1 正常路径测量，不是 v2 整轮重新验收。下一步见[计划](../plan.md)。
