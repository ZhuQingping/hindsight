# BEAM 1M Recall 下推实验

**已完成：单个完整会话导入、冻结、等价验证和多轮性能测试。**

[展示报告 HTML](BEAM1M-Recall下推性能验证报告.html) · [报告 Markdown](BEAM1M-Recall下推性能验证报告.md) · [SQL 与次数](SQL交互证据.md) · [设计](design.md) · [代码与复现](handoff.md) · [检视结论](review.md)

20 题、3 轮真实 BGE 对照：120 次测量响应一致。排除模型的数据库路径 P95 从 124.71 ms 降至 65.11 ms，平均约 52 ms 基本持平；补充归因显示该 P95 长尾与 Python GC 同步，不能作为 PG 检索算子加速证据。完整 Recall 约 56 秒，主要耗在 CPU BGE，尚未证明 PG 下推显著降低完整平均时延或 P50。

BEAM 1M 是约 100 万输入 Token，本次形成 2,524 条事实，不能当作百万向量测试。正式等价测试固定相同检索向量和参考时间，仍计入真实 embedding 请求和真实 BGE 耗时。

第一版 `05d2894c5` 保持干净。开发位于 `.worktrees/beam1m-recall-perf-20261120`；已 rebase 到远程 `memory-benchmark` 的 `18be05bde`，本轮设计、实现和证据纳入同一个特性提交，未推送。LoCoMo 原环境未修改。整合记录与新增验证见 [rebase-validation.md](rebase-validation.md)。
