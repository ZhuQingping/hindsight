# 完整 Recall 降时延：收益判断与最小验证方案

更新日期：2026-11-19。**本文件保留收益预审方案。用户随后已授权优先实现可行性首版，进展见[实现报告](implementation-report.md)；此处的分段诊断并未作为独立实验完成。**目标是降低完整 Recall HTTP 的平均耗时和 P50；一次 PG 调用是手段，不作为收益判据。

## 1. 当前建议

**暂不投入 6–9 小时实现完整候选下推，先用 1–2 小时的小范围诊断判断收益上限。** 当前证据支持减少候选搬运，但不支持它能明显降低本批 BGE Recall 的平均耗时/P50。若 PG 相关阶段即使全部消除也达不到目标，就停止本轮下推性能实验，转查模型推理、排队或其他实际大头；不为了完成一次调用而继续投入。

1–2 小时是获准启动后的有效准备、采样与分析估算，假设隔离环境可用；不是已启动任务，不包括环境恢复、资源等待或后续优化实现。

## 2. 已有证据说明了什么

| 证据及计时范围 | 平均耗时 | P50 | 能支持的结论 |
| --- | ---: | ---: | --- |
| 旧 81 题 RRF：完整 Recall HTTP | 308.30 ms | 260.78 ms | 这是无 BGE 的另一轮运行，不能与 BGE 相减作为模型耗时 |
| 旧 81 题 BGE：完整 Recall HTTP | 6397.09 ms | 6341.65 ms | 当前固定 Bank 的端到端参考值，包含 HTTP 内完整 Recall，不含 reader/judge |
| 早期受控 Python 融合适配层 | 6.778 ms | 6.597 ms | 独立热 PG；不含 embedding、时间分析、BGE、HTTP |
| 同一受控实验的 C 融合路径 | 6.579 ms | 6.363 ms | 平均点估计改善约 0.199 ms，P50 约 0.235 ms；不能外推为正式 HTTP 收益 |
| 三题 CPU BGE 微测 | 约 4040 ms/题 | 不作整体估计 | 仅 tokenize/predict，直接文本输入；与正式带 context/日期的模型输入不同，不能从 HTTP 总耗时中直接扣除 |

来源：[81题运行摘要](evidence/locomo-rerank-comparison.json)、[受控原型统计](evidence/prototype-results.json)、[本机 BGE 验证](../plan.md)。原参考报告为 ContextDB-Research/Recall下推到PG-源码契约与LoCoMo收益分析-20261119.html 第 4、8 章。

两轮 81 题存在并发及恢复差异；原型也有两道时间题回退，不是正式实现与原服务的完整 A/B。此次核对旧 BGE 81 份 retrieval 回包，trace 均为 None，无法由回包还原逐请求阶段占比。**目前不能声称 PG 只占完整请求的某个百分比，也不能把约 6 秒的差额全部算给 BGE。**

## 3. 真实 SQL 对研发取舍的约束

[普通题实际 SQL](evidence/current-sql/q000-01.sql)已经把向量与全文放在一次 UNION ALL 中。实际 SQL 如下，仅调整空白换行；这里全文使用 PG 的 ts_rank_cd，并非新实现了 BM25 算法：

```sql
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        1 - (embedding <=> $1::vector) AS similarity,        NULL::float AS bm25_score,        'semantic' AS source
 FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_units
 WHERE bank_id = $2   AND fact_type = 'world'   AND embedding IS NOT NULL   AND (1 - (embedding <=> $1::vector)) >= 0.3
 ORDER BY embedding <=> $1::vector LIMIT 1000)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        NULL::float AS similarity,        ts_rank_cd(search_vector, to_tsquery('english', $4)) AS bm25_score,        'bm25' AS source
 FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_units
 WHERE bank_id = $2   AND fact_type = 'world'   AND search_vector @@ to_tsquery('english', $4)
 ORDER BY ts_rank_cd(search_vector, to_tsquery('english', $4)) DESC LIMIT $3)
```

[图 SQL](evidence/current-sql/q000-02.sql)包含种子实体扩展、按关系两端查 memory_links、去重和聚合；实体分支已经有 LATERAL + LIMIT 200 的有界扩展。不能把已有限制再次包装为新研发能力。

[计数证据](evidence/current-sql-counts.json)：world-only 实验剖面的普通题候选为 2 次 fetch，时间题样本为 5 次，不含原文/鉴权/配置。它不是此前另一 Bank 的 19 次，也不等于正式默认类型请求的全部 SQL 数。

本 Bank 只有 109 条事实，低于融合后 Top-300；两个采集样本融合后均有 109 条。因此，把相同候选融合搬进 PG，不会自然减少 BGE 要评分的记忆。图贡献还可能影响 RRF 与最终排名，不能因事实已出现就随意删除图分支。

| PG 侧改动 | 怎样减少工作 | 对当前任务的判断 |
| --- | --- | --- |
| 窄列候选、RRF 后批量取正文 | 避免 UNION/图分支重复搬运 text/context，减少宽行聚合和解码 | 有原型证据，但改善为零点几毫秒量级；只有正式服务的搬运/往返确为大头才继续 |
| 多次调用合并、关联原文批量读取 | 减少驱动往返与连接等待；原文一次取足避免后查 | 先量实际 RTT、池等待及原文读取；提前传更多 chunks 可能抵消收益，一次调用本身不能保证提速 |
| 图/时间访问路径与并行 | 只有实际扫描、宽聚合或独立分支等待显著时，才能缩短关键路径 | 小热库暂无大收益证据；不先开发新图存储、CustomScan 或并行框架，图仍依赖种子 |
| 检索更少候选送入 BGE | 真正减少 query-document 模型对数 | 会改变召回策略，非当前等价方案；现有 ContextBase 已能裁剪候选，不是 PG 独有缺失能力 |

目前没有证据证明这批工作负载存在一个值得先投入的大规模 PG 内核改动。若目标仍是严格等价，不能用减少模型输入、调高阈值、删分支或缩短文本冒充收益。

## 4. 最小验证：先测上限，不先做下推

### 4.1 样本与运行条件

使用冻结旧 Bank，保留现有 HTTP 请求、默认类型、budget、模型和 tokenizer；不重新 retain。取 8 道：两道已有时间窗口题，加上按模型输入长度短/中/长确定的 6 道普通题；不依据正确答案选题。预热后单请求并发，每题 3 轮，固定种子打乱顺序，共 24 次真实 Recall。

在隔离实例或实验克隆上运行，不重启 8892、不抢占现有评测资源。仅采集 Recall，不调用 reader/judge；保留最终响应及 pack_context 供输入差分。8 题只作瓶颈筛查，不能替代 81 题性能与等价结论。

### 4.2 每次请求记录什么

| 阶段 | 必须拆开的时间或计数 |
| --- | --- |
| 客户端 | 从发送 Recall 到完整响应读取结束的 wall time，以此计算平均值/P50 |
| 前置处理 | 鉴权/配置、连接等待、query embedding、自然语言时间解析；各自独立，不统算成 SQL |
| PG 与数据准备 | 每条业务 SQL 的驱动往返、PG 执行、池等待、返回行/字节；RRF、候选补全及原文读取单列 |
| 模型 | 模型就绪、线程池排队、实际 tokenize/predict、候选对数与 token 长度；现有 rerank 总跨度包含其他工作，不能直接当纯推理 |
| 后处理 | 最终评分、原文预算、事实预算、响应组装/序列化 |

使用请求 ID 和单调时钟关联。PG 语句与应用驱动记录交叉核对，追踪实际依赖；并行 SQL 取关键路径，不能把所有执行时间相加。现有轻量阶段埋点优先复用，避免全量 trace 正文构造干扰计时。若需补埋点，仅作隔离诊断，不顺带实现新 Recall。

### 4.3 怎样判断值得继续

对每个请求 i，记录完整耗时 T_i，以及拟由 PG 改动影响、互不重叠的关键路径时间 D_i：候选 SQL/往返、融合、补全、原文读取等；鉴权、embedding、时间解析、模型推理不因候选下推而自动消失。

先做乐观敏感性计算：假设 D_i 全部降为 0，其他阶段保持不变，得到 T_ideal,i = T_i - D_i。分别计算这组值的平均和 P50，再与基线比较。这是理想计算边界，不是优化实测；不能用两个阶段的 P50 直接相减，也不用于预测并发饱和时的排队变化。

**建议预设业务门槛：完整 Recall 的平均和 P50 均至少下降 10%，同时报告绝对毫秒。** 这是立项筛选建议，不是已获收益。若理想边界也达不到门槛，结束当前下推性能实验；若只有某些时间题获益，按其请求占比报告，不能外推到整体平均。

若边界足够大，只改实际最热的一处 SQL/往返路径，保持候选、模型输入和预算一致，先作小样本 A/B；不直接启动完整 6–9 小时工程。仅在方向成立后扩大到同一 81 题、每路径多轮交错，计算成对差异/区间，并核对全部响应与 reader 输入。单并发先过，再按固定小并发观察排队、吞吐和失败；P95 作为回退监控，平均/P50 是主指标。

## 5. 若 PG 上限不够，下一步是什么

优先处理真实占比大的模型推理或排队，保留相同权重和输入时先比较可用推理实现与资源；这属于模型运行时工作，不能算作 PG 内核收益。既有运行时已提供 batch、线程池及长度分组等能力，先核实实效，不把已有参数当新研发。

若允许改变结果策略，可以另测 RRF 后 Top-64 等模型前筛选。例如某题有 109 对输入时，改为 64 对会少 45 对，约 41% 的模型对数；不代表耗时线性减少，更不保证答案不变。现有 trim_merged_candidates 已具备这一裁剪位置，先用应用侧对照，不能把配置调整包装为 PG 创新。质量必须另按固定协议完整评测。

**结论：一次 PG 调用值得作为接口/执行组织验证，但当前不应直接当作 BGE 完整 Recall 平均/P50 优化项目。先完成上限诊断，有足够收益空间再开发。本轮可行性实现的实际状态以[首版报告](implementation-report.md)为准；不能把该实现自动当作性能收益证明。**
