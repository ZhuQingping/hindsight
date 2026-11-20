# 当前性能阶段证据

这些文件是测量及阶段停止时的脱敏快照，保留原 `baseline_commit`、分支和 `committed=false` 等历史字段。后续归档发布不回写历史测量；当前状态见[统一入口](../../README.md)。

- `external-http.json`：三组各 400 次、合计 1,200 次的逐题时延和响应哈希；模型采用 RRF 透传。
- `analysis.json`：逐题差值、退化及 bootstrap；只代表一个固定会话。
- `rank-correctness.json`：最终 v2 的 58,040 个逐位评分检查；`rank-correctness-measured-v1.json` 保留测量版。
- `http20.json`、`temporal.json`、`regression109.json`：默认题、额外时间请求和独立恢复库的等价范围。
- `bge-prefix.json`：真实 BGE 只完成 3/20，剩余待验。
- `rank-pg-entry.json`、`json-pg-entry.json`：分轮消融，只能在同一轮比较，不跨轮拼接基线。
- `manifest.json`：数据摘要、源码/库哈希、测试和限制。v1 性能/BGE 与最终 v2 评分检查分开记录。

不含模型权重、凭据、事实正文、query 向量或完整 Recall 响应。完整私有记录的移交需另行准备。
