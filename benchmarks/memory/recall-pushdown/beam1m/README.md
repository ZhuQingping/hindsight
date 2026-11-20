# BEAM 1M Recall 下推实验

更新：2026-11-20。当前代码、手册与状态统一在[专项入口](../README.md)。

**当前性能阶段：核心路径平均 53.48→44.75 ms，P50 49.18→43.16 ms，排除模型。** 三组各 400 次测量响应相同；17 题平均改善、3 题退化。真实 BGE 当前版完成 3/20，剩余待人工验收。没有跨路并行或完整 Recall 加速结论。

- 当前：[性能报告](phase3-performance.md) / [HTML](phase3-performance.html)、[脱敏证据](phase3-evidence/README.md)、[使用手册](../RUNBOOK.md)、[交接](../AGENT_HANDOFF.md)。
- 当前代码：`native/contextbase_rank_cd_or.c`（本目录上一级），ContextBase 的 `recall_rank.py`、`recall_rank_json.sql`；P3 和首版保留作对照。
- 规模：一个完整官方会话，50/50 文档、约 985k 输入 Token，2,524 事实、62,031 关系；不是百万向量数据。冻结后同一 Bank 测试。

## 历史阶段

[早期报告 HTML](BEAM1M-Recall下推性能验证报告.html) · [Markdown](BEAM1M-Recall下推性能验证报告.md) · [SQL 与次数](SQL交互证据.md) · [早期设计](design.md) · [早期检视](review.md)

上一轮 P3 做完 20 题×3 轮×两组的真实 BGE 共 120 次测量，响应一致；排除模型时平均约 52 ms 基本持平。该记录不能替代当前性能版剩余 BGE 验收，也不能把 248 ms 的中间实现作为原始基线。

原首版 `05d2894c5` 保持干净，P3 `4016fed9b` 保留。远程整合基础 `18be05bde` 的回归记录见 [rebase-validation.md](rebase-validation.md)。LoCoMo 原环境未修改，当前临时压测和模型验证已停止。
