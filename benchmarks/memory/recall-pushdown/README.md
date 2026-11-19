# PostgreSQL Recall下推：统一维护入口

更新日期：2026-11-19。**当前状态：原始等价适配已通过限定81题验收。C RRF保留PG；RRF/真实BGE各81/81题完整响应、融合结果及reader正文与未修改原始版一致，BGE输入一致。每题一次候选SQL、零后续补查。固定解释器/哈希环境的实验结论，未切换原服务。** 见[三组对照与修复验证](three-way-original-compatibility.md)。

| 阅读目的 | 文档 |
| --- | --- |
| 先看当前是否符合“一次PG调用、结果等价” | [三组对照与修复验证](three-way-original-compatibility.md) |
| 看两边改动及调用链 | [设计](design.md)、[实施计划](plan.md) |
| 看PG C与SQL代码 | [C源码说明](native/README.md)、[PG SQL](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql) |
| 看已完成和待完成 | [进展](progress.md) |
| 判断完整Recall平均/P50收益 | [最小收益验证](latency-validation-plan.md) |
| 查看历史规范化对照实验 | [原PG历史A/B](local-existing-pg-validation.md)、[隔离快照首版](implementation-report.md) |
| 查看分析与原始证据范围 | [分析](analysis.md)、[证据说明](evidence/README.md) |

## 当前范围

PG一次候选业务查询完成四路检索、C RRF、Top-K、候选正文与关联原文补全；ContextBase释放查询连接后复用原BGE、最终评分、事实/原文预算与组装，不再补查PG。下推的是ContextBase服务端的RRF，不是LoCoMo客户端打包。API外层配置读取单独计数。

修复保留原始各路名次，没有调整分数、权重和模型参数。当前严格验证限定原109条world事实、81题及CPython 3.11.15/64位SipHash13/哈希种子0；顺序兼容机制不是通用排序策略，未覆盖配置在查询前退出接管。不能据此宣布全部请求或生产8892已经等价。

## 收益边界

当前首先验收可行性和兼容性，没有证明完整Recall平均、P50或P95提升。冻结查询向量不含在线embedding耗时，实际本地BGE运行参与验证。结果等价不自动节省Token；没有新的reader/judge成绩，不继承历史76/81。查询内并行、动态剪枝、PG调用模型及PG评分/预算均未在本版实现。

## 与打榜及维护的关系

本专项使用旧Bank `locomo_conv30_20261118_200523`。全量1540题及V1使用自己的Bank、配置和冻结源码，以[打榜主入口](../README.md)为准，不混用分母。准确率评测继续使用既有runner/support和固定AMB，不维护第二套reader/judge。

本轮将PG扩展与ContextBase代码、文档和证据纳入同一提交；不推送或切换原服务；原PG和源Bank不重建。正文、设计与进展统一维护本目录，旧ContextDB-Research展示文件是历史快照。原始回包、向量、凭据、权重和编译产物保留在gitignored私有目录；脱敏摘要进入evidence，旧失败记录保留。
