# 第三阶段：性能优化阶段交付与人工验收

> 2026-11-20 归档说明：本文件保留当时的阶段记录（含“未提交/未推送”状态）。当前维护、发布与验收状态以[统一入口](../README.md)、当前进展和远程分支 HEAD 为准；代码发布不表示剩余验收通过。

2026-11-20。**当前阶段已停止研发，按后续明确指令统一归档到 memory-benchmark；等待人工与剩余真实 BGE 验收。**

## 1. 当前交付什么

采用两项改动：**PG C 扩展的全文 OR 评分精确快速路径，以及直接构造最终返回 JSON。** 原查询范围、候选数、同分顺序、C RRF、模型输入、最终评分和预算保持原规则。没有切换 BM25，没有恢复图并发，也没有实现新的跨路并行。

代码基线 `4016fed9b` 保留，当前开发分支为 `codex/recall-perf-phase3-20261120`。它仍位于工作区 `/Users/zhuqingping/Work/Database/Context/hindsight/.worktrees/beam1m-recall-perf-20261120`。PG 主干仓没有本轮修改；新增 C 扩展源码放在 ContextBase 仓并实际由 PG 执行。

## 2. 性能：相对原流程的净收益

| 冻结输入的 Recall 核心 HTTP 路径 | 平均 ms | P50 ms | P95 ms |
| --- | ---: | ---: | ---: |
| 原流程，关闭下推 | 53.48 | 49.18 | 125.24 |
| 已提交 P3 下推 | 53.06 | 52.55 | 66.87 |
| 本轮新版本 | **44.75** | **43.16** | **58.74** |

相对原流程，平均减少 **8.73 ms，约 16.3%**，P50 减少 **6.02 ms，约 12.2%**。这次没有用阶段性 248 ms 版本作为收益基线。当前改善尚未达到内部暂定的平均/P50各下降 20% 目标，不宣称最终性能目标已经达成。

三个独立 API 进程、一个外部客户端；每组 20 题 × 20 轮，共 400 个测量样本，另外排除两轮预热。问题和版本顺序随机交错，默认 GC 开启，全部响应与历史等价基线核对。**不包含 embedding、实际 BGE，也不包含 ContextBase 完整业务鉴权层。** 因此不能说完整生产 Recall 快了 16%；此前 CPU BGE 占主导的问题没有改变。

P95 包含 Python GC 影响，不能全部归因于 PG 算子加速。20 题中 17 题平均更快、3 题更慢，最大单题平均退化约 5.35 ms；逐题原因未完成因果归因，不能隐去退化题。按问题聚类的平均差值 bootstrap 95% 区间为约 -12.98～-5.01 ms，仅适用于这一固定会话。

依据：[1,200 次时延与响应哈希](phase3-evidence/external-http.json)、[逐题分析](phase3-evidence/analysis.json)。

## 3. 为什么能少做工作

- **精确 OR 快速路径**：普通 OR 查询的每个最小覆盖是一处命中位置。直接累加原默认位置权重，避免为每条候选构造/排序位置表示、反复解释查询树。重复查询词去重；只缓存表达式内的查询结构，不缓存文档或答案。AND、NOT、短语、前缀、词项权重和超限查询交给原 PG 函数。
- **直接生成 JSON**：P3 内部时间状态仍为 JSONB，最终候选与原文直接组装为传输 JSON，减少最后一轮 JSONB 构造。保留全部候选/原文，chunk 键按原 JSONB 顺序输出；Python 继续使用原候选模型和预算流程。

只推荐 `RankJsonPostgresRecallMemories`。`RankPostgresRecallMemories` 为单独归因 C 评分收益的对照。图仍串行；并行设置/批量收集、窄投影没有足够净收益，未采用。另一个完整融合 C 原型在合成 ±0 元数据的严格位比较中发现差异，已排除，没有放宽比较标准让它通过。

## 4. 已验证与待验证范围

| 检查 | 当前结果 |
| --- | --- |
| 真实向量/查询评分 | 50,480 次 `float4send` 逐位相等 |
| 生成评分用例 | 7,560 次逐位相等，含权重、重复位置、剥离位置及回退语法 |
| 可重复 SQL 用例 | 72 个逐位相等检查通过 |
| 默认请求 | 20 题响应、模型输入一致；外部测量 1,200 次响应一致 |
| 额外时间请求 | 2 题响应和模型输入一致 |
| 历史恢复库 | 109 事实 / 81 题完整候选包一致，未访问活动 LoCoMo |
| 实际本地 BGE | **已完成 3 题，响应和输入与历史原始基线一致；17 题待你们测试** |
| 相关单元测试 | 39 项通过 |
| 数据 | 测试后七张记忆表哈希不变 |

JSON 对象键的排列顺序不作为差异；数组顺序和数值没有误差容忍。三题实际 BGE 的旧观察器曾用 ASCII 转义计算输入哈希，RRF 观察器用 UTF-8；按相同输入重算两种编码后核对一致，观察器现已统一 UTF-8。原始记录未覆盖。

没有新增准确率评估或 Token 节省；不将真实 BGE 3 题说成 20 题全部通过。严格等价仍限定同一冻结数据、向量、时间、配置与已支持形状；多租户/并发写入/附件等一般用途发布覆盖不在本阶段完成。

## 5. 代码入口

所有代码均在上述开发工作区：

| 文件 | 内容 |
| --- | --- |
| `benchmarks/memory/recall-pushdown/native/contextbase_rank_cd_or.c` | 新 C 评分函数，独立编译模块 |
| `benchmarks/memory/recall-pushdown/native/test_rank_cd.sql` | 评分字节相等回归用例 |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank_json.sql` | 推荐候选入口，精确评分及直接 JSON 返回 |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank.py` | opt-in 适配；推荐 `RankJsonPostgresRecallMemories` |
| `benchmarks/memory/recall-pushdown/beam1m/verify_beam.py` | 新路径核对；serve-only 模式供独立客户端测量 |

专用 PG 55440 已注册新函数与独立模块路径。没有覆盖原共享库。**现有 8898/8899 服务没有切换到新版本，不能直接用 8899 判断本轮收益。** 常规服务接入需使用新代码、独立测试进程，并配置 `HINDSIGHT_API_MEMORIES_EXTENSION=hindsight_api.engine.memories.pg.recall_rank:RankJsonPostgresRecallMemories` 及原 Bank allowlist。不要替换活动 LoCoMo 服务。

## 6. 你们如何测试

私有数据、凭据、快照和完整响应保留在 `/Users/zhuqingping/Work/Database/Context/hindsight/benchmarks/memory/.local/beam1m-recall-20261120`，没有提交。以下命令只针对专用冻结库，使用单独的临时 API；输出标签不能重复。

先复核默认 Recall 的等价性，模型采用 RRF 透传：

```bash
R=/Users/zhuqingping/Work/Database/Context/hindsight
D="$R/benchmarks/memory/.local/beam1m-recall-20261120"
"$R/.venv/bin/python" "$D/runtime/tools/replay/beam_run_verify.py" \
  --database beam1m --path legacy --mode rrf --take 20 --label user-phase3-off
"$R/.venv/bin/python" "$D/runtime/tools/replay/beam_run_verify.py" \
  --database beam1m --path rank_json --mode rrf --take 20 --label user-phase3-new
```

对照 `results/user-phase3-off/verification.json` 与 `results/user-phase3-new/verification.json` 的逐题响应、模型输入哈希，以及两目录的完整响应文件。固定向量是同一份真实 embedding 快照；两次独立实时 embedding 可能数值不同，不能直接用于严格等价归因。

复测性能，仍排除模型：

```bash
"$R/.venv/bin/python" "$D/phase3/tools/replay_external.py" user-phase3-perf
```

这会临时启动三套独立 API，完成交错测试后关闭自己创建的进程。不要同时运行 BGE 或其他重负载。结果在 `phase3/user-phase3-perf/results.json`，每组 400 次。原流程及 P3 都会重测，不复用历史 52 ms。该私有重放脚本与已执行驱动仅有运行目录标签的差异，原脚本也已归档。

完整实际 BGE 核对可把上述模式改为 `--mode bge`、使用新标签。20 题单组约需 18～20 分钟；本阶段仅做完 3 题，未将剩余题静默继续运行。完整带模型时延若要比较，需要同配置、同输入、公平交错的新 A/B，不能拿历史耗时相减。

## 7. 检视和停止状态

C 扩展编译通过，目标 Ruff/ty 通过。要求的全仓 lint 已运行，仍只有原有 `http.py:5886` F841；无关 formatter 改动已排除。完整融合原型未被加入默认构建和选择器。

临时外部 API 已全部退出；实际 BGE 验证已按阶段交付停止。专用 PG 及原有常规服务保留供你们测试。没有继续并行研发或自动切换服务。后续按用户明确指令提交归档，人工验收仍未完成；代码发布不代表生产发布批准。

详细证据：[清单与源码哈希](phase3-evidence/manifest.json)、[真实 BGE 已完成部分](phase3-evidence/bge-prefix.json)、[时间请求](phase3-evidence/temporal.json)、[81 题恢复库](phase3-evidence/regression109.json)。

### 最终交接修补

末次检视只增加了缓存重建错误路径的指针置空，避免分配异常被捕获后保留旧指针；使用独立 `rank-build-v2` 库，没有覆盖已加载的 v1。最终库重新通过 50,480 + 7,560 个逐位评分检查。整轮性能和 3 题 BGE 仍是 v1 正常路径测量，未标成 v2 新测结果；本次不再启动长测，留给人工验收。源码、测量版和最终库哈希均已记录。
