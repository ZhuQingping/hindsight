# Agent Memory 友商评测报告

更新：2026-11-19（友商来源于11月18日收集，ContextBase完整基线于11月19日完成）。本文统一维护测试数据集、准确率、Token、时延、模型环境和来源，不再另设速查、来源或竞品分析文件。

## 管理层汇报摘要（2026-11-19）

| Benchmark | Mem0 | Hindsight | ContextBase |
| --- | ---: | ---: | ---: |
| LoCoMo | 92.5% | 92.0% | **基线92.14% → 优化93.64%（均1540题）** |
| LongMemEval-S | 94.4% | 94.6% | 尚未测试 |
| BEAM 1M | 64.1% | 73.9% | 尚未测试 |
| BEAM 10M | 48.6% | 64.1% | 尚未测试 |

**ContextBase第一版优化已全量完成：1442/1540，准确率93.64%，比基线净多答对23题（+1.49个百分点）。36题转对、13题回退；98道错题已逐条检查来源。**

| 指标 | 上一轮基线 | 本轮窗口优化 |
| --- | ---: | ---: |
| 准确率 | 92.14%（1419/1540） | **93.64%（1442/1540）** |
| 原版答案F1 | 27.65% | **28.01%** |
| 平均记忆上下文（o200k） | 7806 tokens | 7980 tokens |
| recall P50 / P95 | 15.31 / 19.47秒 | 21.99 / 32.91秒（混合资源） |

本轮提高了准确率，但F1只增加0.36个百分点，检索时延变长。变化为原文候选8K→64K及客户端问题相关消息窗口，最终上下文仍8K；原Bank、reader/judge模型、原AMB提示与裁判规则不变，未部署PG下推或全文新索引。模型为`gpt-6.1-sol`，与友商模型/硬件不同，不能据数值宣称同条件第一。

重排并发中途1→2，已单列851题切换前（P50/P95 17.68/29.80秒）、2题切换/恢复（28.58/43.45秒）、687题切换后（24.88/34.78秒）；不同题/负载，不能作为并发加速的同题对照。模型账目含19次未知用量尝试，已知答题/判题共12,786,184 tokens，不含retain及内部调用，不能当完整账单。

唯一重启中断q90已首次答题/判题并判对；其余1539题原答案和裁判逐条一致，旧运行6158份sealed记录哈希未变。原始失败仍留在旧目录。完整结果：[全量优化](results/locomo1540-window-20261119.json)；原因、配置和资源恢复证据：[逐题诊断](results/locomo1540-window-diagnostics-20261119.json)。

LoCoMo、LongMemEval为准确率，BEAM为平均分；各家模型和环境不同，表格不是统一条件排名。来源：[Mem0官方表](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026)、[Hindsight固定官方结果](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/results-manifest.json)、[ContextBase基线](results/locomo1540-baseline-20261119.json)和[优化全量结果](results/locomo1540-window-20261119.json)。

---

**ContextBase完整基线：1419/1540，准确率92.14%、答案F1 27.65%，平均上下文7806 tokens，检索P50/P95为15.31/19.47秒。** 全题完成、失败题0；121道错题均已逐条分析。原始指标、模型/预算/版本、全部答案及判定见[完整结果](results/locomo1540-baseline-20261119.json)，逐题诊断与两家官方答案见[错误分析](results/locomo1540-error-analysis-20261119.json)。这不是同模型、同裁判、同硬件的排名；更低的F1和更长的检索时延仍需改进。

**先看各家测什么，再看具体数值。** 这些是发布者各自条件下的结果，不是统一总榜；未知字段标为未见披露，不能填 0。测试数据集也不同于服务使用的 PostgreSQL、Qdrant 等存储数据库。

Mem0、Hindsight 与 ContextBase 的 LoCoMo 题目、模型、裁判、预算及指标对齐情况，统一见[三家方案对照表](plan.md#mem0-hindsight-与-contextbase-方案对照)。

已完成 conv-30 单组结果的只读对比，发现上下文打包与评分尺度差异；详见[81 题诊断及 Hindsight 对比](plan.md#conv-30-结果诊断及-hindsight-对比)。该分析没有重跑或修改两家的原始标签。

## 各家测试数据集与公布指标

| 产品 | 已收集的测试数据集 | 质量指标 | Token 与成本指标 | 时间指标 |
| --- | --- | --- | --- | --- |
| **Mem0** | LoCoMo、LongMemEval-S、BEAM 1M/10M；DolphinBench | 问答准确率及分类结果；BEAM 连续平均分和通过率；工具任务通过率 | 平均上下文 tokens；DolphinBench 另报运行成本 | 主仓库报 P50；DolphinBench 另报任务中位耗时 |
| **Hindsight** | LoCoMo、LongMemEval-S、BEAM、PersonaMem、LifeBench、PrecisionMemBench、sde-bench；DolphinBench 官方对照 | 准确率、BEAM 平均分、检索 Active Pass/precision/recall、代码与工具任务通过率，分别属于对应套件 | AMB 结果文件报平均上下文 tokens；DolphinBench 另报成本 | AMB 报平均检索时间、写入时间；DolphinBench 报任务中位耗时 |
| **Cognee** | LoCoMo 修改范围版；BEAM 100K/10M；另有 HotPotQA 研究 | LoCoMo 裁判准确率；BEAM 连续平均分；HotPotQA 另有 EM/F1/语义正确性 | 当前收集的 LoCoMo/BEAM 主报告未见统一的 token 成绩表 | 当前收集的 LoCoMo/BEAM 主报告未见统一的 P50/P95 成绩表 |
| **阿里云 RDS ContextDB** | FinanceBench、SyllabusQA、Qasper、ClapNQ 四类知识库问答；标准记忆榜尚待核实 | 社区产品文章报告综合准确率 | 相对 LightRAG 的 Token 消耗比例 | 检索耗时；未明确给出 P50/P95 |
| **腾讯云 TencentDB Agent Memory** | PersonaMem；长会话设置的 WideSearch、SWE-bench、AA-LCR | PersonaMem 总准确率、事实召回率；其余为任务成功率 | 长任务总 tokens、相对节省比例 | 本轮所收集上述成绩表未见 P50/P95 |
| **火山 OpenViking** | LoCoMo；tau2-bench、ClawWork；HotpotQA 及五类单轮 RAG | Agent 问答准确率、任务成功率、经济模拟收益、知识库 QA 准确率 | 输入 tokens 总量；单题 tokens；建索引 tokens，按套件分别报告 | LoCoMo 平均问答时间；知识库 QA 检索时间，未统一为 P50/P95 |
| **Zep** | LoCoMo、LongMemEval | 总准确率、分类准确率 | 每题上下文 tokens 中位数 | 检索 P50 和 P95 |

来源：[Mem0 主仓库](https://github.com/mem0ai/mem0)、[Hindsight 结果清单](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/results-manifest.json)、[Cognee LoCoMo 报告](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/locomo/REPORT.md)、[Cognee BEAM 报告](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/beam/REPORT.md)、[Cognee HotPotQA 说明](https://www.cognee.ai/ai-memory-evals-0825)、[阿里云社区产品文章](https://developer.aliyun.com/article/1752686)、[腾讯产品页](https://cloud.tencent.cn/product/agm)、[腾讯官方仓库](https://github.com/Tencent/TencentDB-Agent-Memory/blob/82b1ab4a2c47a5d65b99845841b7c659ac6f8497/README.md)、[OpenViking 官方报告](https://blog.openviking.ai/post/openviking-benchmark-results/)、[Zep 官方结果](https://www.getzep.com/research/memory-benchmarks/)。

## 成绩、作答模型、裁判模型与效率

**模型是关键评测条件。** 分数同时受记忆系统、作答模型、裁判模型、题目范围和上下文预算影响；更强的作答模型可能提高正确率，换裁判也可能改变判定。下表把作答 / 裁判模型与成绩放在一起；抽取、向量及重排模型见后面的环境表。模型名称必须对应这次成绩，不能用当前默认值或旧运行补全。

下面按每个发布者自己的口径摘录，不构成统一条件的排名。K = 千，M = 百万；“未见披露”不能填为 0。

| 产品与测试 | 质量成绩 | 作答 / 裁判模型 | Token 指标 | 时间指标 | 口径与来源 |
| --- | --- | --- | --- | --- | --- |
| **Mem0 / LoCoMo** | 准确率 **92.5%** | 新版成绩未完整绑定；四月旧运行 GPT-5 / GPT-5 | 平均上下文约 **7.0K/题** | P50 **0.88s**，未在主表列 P95 | 托管平台 Top-200 单次检索；不是写入及作答裁判的全流程 tokens。[来源](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026) |
| **Mem0 / LongMemEval** | 准确率 **94.4%** | 新版成绩未完整绑定；四月 Top-50 样例 GPT-5 / GPT-5 | 平均上下文约 **6.8K/题** | P50 **1.09s** | 同上，不能当作完整答案生成时间。[来源](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026) |
| **Mem0 / BEAM 1M、10M** | 平均分 **64.1%、48.6%** | GPT-5 / GPT-5 | 平均上下文约 **6.7K、6.9K/题** | P50 **1.00s、1.05s** | 平均分不是题目通过率。[来源](https://github.com/mem0ai/mem0#new-memory-algorithm-april-2026) |
| **Hindsight / LoCoMo** | 准确率 **92.0%** | Gemini 3.1 Pro Preview / Gemini 2.5 Flash Lite | 平均上下文 **36,235/题** | **平均检索 0.964s** | 1540 题历史 AMB rag 运行；这是平均值，不是 P50。[结果文件](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/outputs/locomo/locomo-hindsight/rag/locomo10.json.gz) |
| **Hindsight / LongMemEval-S** | 准确率 **94.6%** | Gemini 3.1 Pro Preview / Gemini 2.5 Flash Lite | 平均上下文 **43,625/题** | **平均检索 0.675s** | 500 题历史 AMB rag 运行，非当前实例默认配置。[结果文件](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/outputs/longmemeval/hindsight/rag/s.json.gz) |
| **Cognee / LoCoMo** | 准确率 **90.7% / 91.3%** | GPT-5-mini / GPT-5.1（medium） | 主报告未见统一值 | 主报告未见统一 P50/P95 | 修改范围后的 1762 题，包含对抗题；不是 Mem0 常见 1540 题范围。[来源](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/locomo/REPORT.md) |
| **Cognee / BEAM** | 100K **79%**、10M **67%** | GPT-5 / GPT-5（独立调用） | 主报告未见统一值 | 主报告未见统一 P50/P95 | 100K 为一个留出会话 20 题的重复平均，10M 为探索结果。[来源](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/beam/REPORT.md) |
| **阿里云 / 四类知识库 QA** | 综合准确率 **79.32%** | 未见披露；文章仅称使用同一大模型 | 单题 Token 消耗约为 LightRAG **1/3** | 检索耗时 **1.64s** | 社区产品介绍文章自报；模型、分母和分位数未完整披露，非已核实的 LoCoMo 成绩。[来源](https://developer.aliyun.com/article/1752686) |
| **腾讯云 / PersonaMem** | 总准确率 **76.10%**；事实召回率 **79.07%** | Kimi-K2.5（OpenClaw 3.7）/ 未见披露 | 该表未见披露 | 该表未见披露 | OpenClaw 3.7 + Kimi-K2.5，589 题；两项百分比含义不同。[来源](https://cloud.tencent.cn/product/agm) |
| **腾讯云 / WideSearch** | 成功率 **33% → 50%** | 未见披露；不能沿用 PersonaMem 的 Kimi 配置 | 整轮 **221.31M → 85.64M**，节省 **61.38%** | 该表未见披露 | 长会话短期压缩评测；不是 PersonaMem 的单题上下文长度。[来源](https://github.com/Tencent/TencentDB-Agent-Memory/blob/82b1ab4a2c47a5d65b99845841b7c659ac6f8497/README.md) |
| **OpenViking / LoCoMo + OpenClaw** | 准确率 **82.08%** | 该成绩对应模型 / 裁判未完整披露 | 整轮输入 **37,423,456** | **平均问答 38.8s** | 包含 Agent 工作的时间，不是单独数据库检索耗时。[来源](https://blog.openviking.ai/post/openviking-benchmark-results/) |
| **OpenViking / LoCoMo + Hermes** | 准确率 **82.86%** | 该成绩对应模型 / 裁判未完整披露 | 整轮输入 **52,026,755** | **平均问答 27.9s** | Agent 集成配置单列，不与单轮 reader 的时延直接比较。[来源](https://blog.openviking.ai/post/openviking-benchmark-results/) |
| **OpenViking / LoCoMo + Claude Code** | 准确率 **80.32%** | doubao-seed-2-0-code-preview-260215 / 裁判未完整披露 | 整轮输入 **129,968,899** | **平均问答 20.4s** | 同上。[来源](https://blog.openviking.ai/post/openviking-benchmark-results/) |
| **Zep / LoCoMo** | 页面自报准确率 **94.7%** | GPT-5.4（medium）/ GPT-5.4（CoT 评分） | 上下文**中位数 5760/题** | 检索 **P50 87ms、P95 155ms** | 多 scope 组合检索；页面分类与总计数不一致，待逐题记录核实。[来源](https://www.getzep.com/research/memory-benchmarks/) |
| **Zep / LongMemEval** | 准确率 **90.2%** | GPT-5.4（medium）/ GPT-5.4（CoT 评分） | 上下文**中位数 4408/题** | 检索 **P50 104ms、P95 162ms** | 模型、scope 及预算见官方方法说明。[来源](https://www.getzep.com/research/memory-benchmarks/) |

## 指标怎么理解

| 指标 | 直白含义 | 阅读时注意 |
| --- | --- | --- |
| 准确率 | 有多少题被判为答对 | 核对 judge、评分宽容度、题型范围、样本量；固定 Mem0 prompt 允许日期相差 14 天、列表答中一项；与 F1、BEAM 平均分区分 |
| 答案 F1 | 回答与标准答案的词项重合程度 | 不能与裁判准确率直接比较；也不是检索证据的 F1@K |
| 上下文 tokens | 每题交给作答模型的记忆文本有多长 | 核对是否含 prompt、使用哪个 tokenizer、均值还是中位数 |
| 总输入 tokens | 整个运行累计输入了多少模型 tokens | 与每题上下文不同，需明确运行阶段和题数 |
| 平均时间 | 所有请求耗时的平均值 | 少量很慢请求可能明显拉高它，不等于 P50 |
| P50 / P95 | 约一半 / 95% 请求在此时间内完成 | 核对计时边界是检索还是完整回答，是否计入重试 |
| 相对 Token 节省 | 相比指定基线少用了多少 | 仅对该基线和场景成立，不代表绝对费用 |

答案 F1 并非每家都主报。例：[MemTensor MemOS 的历史官方表](https://huggingface.co/datasets/MemTensor/MemOS_eval_result/blob/1e791b0b305cef8a4385ce7ef09c5c9343baefa6/README.md)同时给出正确率 75.80%、答案 F1 45.27 和 tokens 2640；[BAI-LAB MemoryOS](https://github.com/BAI-LAB/MemoryOS)则以 F1、BLEU-1 为研究指标。两者是不同项目，历史值不代表当前最佳成绩。

## 记忆侧模型及完整评测环境

| 产品 | 已披露的模型与环境 | 检索和评分方式 | 尚缺的关键信息 |
| --- | --- | --- | --- |
| **Mem0** | 官方评测仓已有结果样例使用 **GPT-5 作答、GPT-5 裁判，Azure provider**；平台新算法与 OSS 分开 | Top-200；同时评估 Top-10/20/50/200；单次检索后生成答案，再裁判；BEAM 有平均分和通过率 | 当前宣传成绩未与完整逐题运行环境逐一绑定；平台内部抽取、embedding、服务 build 不宜用 OSS 默认配置代替 |
| **Hindsight** | AMB 指定结果文件中，LoCoMo、LME-S、PersonaMem 及 BEAM 10M 的 reader 为 **Gemini 3.1 Pro Preview**，judge 为 **Gemini 2.5 Flash Lite** | 前三项为 rag；BEAM 历史结果为 single-query；LoCoMo/LME 平均返回上下文约 **36.2K/43.6K tokens** | 这些结果头部未完整披露记忆抽取、embedding、重排及硬件；不能以当前 CI 配置替代历史环境 |
| **Cognee / BEAM** | embedding：**text-embedding-3-large**；100K 抽取 **GPT-5**，10M 抽取 **GPT-5-mini**；reader/judge 均 **GPT-5**；10M 在 **Modal 分布式环境**写入 | 100K 固定 hybrid retrieval；10M 按题型路由；BEAM rubric 每项 0/0.5/1，先按题平均再汇总 | 10M 特定分布式编排未全部公开；路由使用题型标签且在报告题集上选择；硬件规格未完整给出 |
| **Cognee / LoCoMo** | **GPT-5-mini** 抽取、摘要及作答；**text-embedding-3-large** 向量；**GPT-5.1 medium** 裁判；Cognee 1.5.4 | hybrid 检索 passages/entities/facts 各最多 20；二元正确率 | 重排模型及硬件未完整披露；与 BEAM 使用的模型配置不同 |
| **阿里云 RDS ContextDB** | 托管服务；文章称采用**同一大模型**横评四类知识库问答 | 报告准确率、Token 消耗和检索耗时 | 模型名称、样本量、judge、top-k、硬件、逐题结果均未充分披露；社区发布身份与正式评测版本待进一步确认 |
| **腾讯云 / PersonaMem** | **OpenClaw 3.7 + Kimi-K2.5**；产品页明确给出 20 画像、6462 上下文、589 题 | 对比原生 OpenClaw 与记忆增强后的 PersonaMem 表现 | PersonaMem split、judge、记忆抽取/embedding、检索预算、逐题结果及硬件未完整披露；当前 DeepSeek 默认配置不是该次 Kimi 环境 |
| **OpenViking** | 主仓库标注评测版本 **0.3.22**；Claude Code 复现文档记载原始实验使用 ARK 上的 **doubao-seed-2-0-code-preview-260215** | 各 Agent 有独立导入、QA、judge 流程；SDK 预写入与真实 hook 自动捕获是不同实验 | 官方报告未逐项固定所有 Agent 模型、judge、题目分母及运行参数；当前脚本默认值不能证明复现了发布成绩 |
| **Zep / LoCoMo、LongMemEval** | **GPT-5.4 medium** 作答、**GPT-5.4** CoT 裁判；记忆抽取及 embedding 模型未见完整披露 | 多 scope 组合检索，cross-encoder 重排；重排模型名称未披露 | 托管系统内部模型及硬件；LoCoMo 页面总计与分类差异仍待核实 |

模型与数据范围来自成绩表及文末链接的官方报告和结果文件；同一模型用于不同调用不代表评分没有方差。

**ContextBase 首轮必须逐项记录：**记忆抽取/摘要模型、embedding 模型及维度、重排模型或排序算法、作答模型、裁判模型，以及各自的精确版本、provider、reasoning 配置、temperature、输出上限和 prompt。记忆侧模型影响存储和召回，作答模型影响生成，裁判模型影响正确率判定；答案 F1 不依赖 LLM 裁判，但仍受生成答案的模型影响。跨产品对照应固定作答、裁判及预算，分别报告记忆侧配置；厂商原始成绩保留其原配置。

### Hindsight LoCoMo：哪些参数可以追溯

针对上表 **92.0%（1417/1540）** 这一组 AMB 历史结果，公开程度如下。结果文件中的实测记录与源码默认值分开列示：

| 证据层级 | 已核实内容 |
| --- | --- |
| **该次结果文件明确记录** | `dataset=locomo`、`split=locomo10`、`mode=rag`、`oracle=false`；1540 题，272 份导入文档；reader `gemini:gemini-3.1-pro-preview`，judge `gemini:gemini-2.5-flash-lite` |
| **该次结果文件记录的统计值** | 导入耗时 330205.8ms；平均检索 964.1ms；平均上下文 36235.4 tokens/题。这些是实测统计，不是预算配置 |
| **固定 AMB 源码的 LoCoMo 默认检索参数** | `budget=high`、`max_tokens=32768`、`include_chunks=true`、`max_chunk_tokens=16384`、`include_entities=false`；问题截取前 1900 字符；token 上限可被环境变量覆盖 |
| **固定 AMB 源码的生成与写入默认行为** | Gemini 生成 `temperature=0`；seed 仅在设置 `OMB_SEED` 时传入；内嵌 provider 配置写入模型 `gemini-2.5-flash-lite`；observations 默认关闭，可由环境变量启用 |
| **尚不能绑定该次成绩的完整配置** | 服务端抽取模型及精确版本、embedding 模型/维度、重排模型、chunk 参数、全部环境变量覆盖、seed、服务 build、PG/机器规格、并发及冷/热状态 |

**结论：已公开结果和可运行代码，但该次成绩的完整配置快照仍不齐。** 源码默认写入模型及检索预算可用于准备复现，不能据此宣称它们就是 92.0% 运行的全部生效配置。`32768` 是事实返回预算，原文 chunks 另有预算；总上下文还受序列化方式影响，不能把它当作完整 reader 输入硬上限。

来源：[该次结果文件](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/outputs/locomo/locomo-hindsight/rag/locomo10.json.gz)、[固定 AMB Hindsight 适配器](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/src/memory_bench/memory/hindsight.py)、[固定 Gemini 调用代码](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/src/memory_bench/llm/gemini.py)。

## 其他任务评测

| 发布者 | 项目 | 原生基线 → 增强后 | 适用范围 |
| --- | --- | --- | --- |
| 腾讯云 | WideSearch | 成功率 **33% → 50%**；tokens **221.31M → 85.64M** | 长会话中的短期上下文卸载和压缩 |
| 腾讯云 | SWE-bench | 成功率 **58.4% → 64.2%**；tokens **3474.1M → 2375.4M** | 每个 session 连续 50 项任务的设置；不能当作标准独立 SWE-bench leaderboard |
| 腾讯云 | AA-LCR | 成功率 **44.0% → 47.5%** | 长会话设置，非 PersonaMem 长期偏好评测 |
| OpenViking | tau2-bench Retail / Airline | **70.94% → 77.81% / 54.38% → 66.25%** | Agent 经验记忆提升任务成功率，非长对话 QA |
| Mem0 DolphinBench | Hermes / GPT 5.6 Luna | 内置记忆 **394/600**；Mem0 **424/600**；Hindsight **417/600** | 600 项模拟工具任务，同一 harness/model 行内对照 |

来源：[腾讯官方仓库](https://github.com/Tencent/TencentDB-Agent-Memory/blob/82b1ab4a2c47a5d65b99845841b7c659ac6f8497/README.md)、[OpenViking 官方报告](https://blog.openviking.ai/post/openviking-benchmark-results/)、[DolphinBench 官方运行记录](https://github.com/mem0ai/dolphinbench/blob/81cb6f8405b40a9e76089cef650806a80af06ea2/results/README.md)。腾讯公布的“+51.52%”是 WideSearch 相对提升，不能写成增加 51.52 个百分点。

OpenViking 还公布 HotpotQA top-20 **91.00%**、检索延迟 **0.23s**，以及五类单轮 RAG 平均 **66.87%**、检索延迟 **0.19s**；这些是知识库问答，不能与其 LoCoMo Agent 问答耗时 20–39 秒混用。

## 数据范围与版本说明

1. **Mem0 的旧文件与新宣传值有时间差。** 官方 2026-05-14 更新文章明确将 LoCoMo **91.6% → 92.5%**、LME **93.4% → 94.4%**归于四月算法到五月时间推理更新。仓库四月文件中的 1410/1540 与 467/500 与旧值一致，不宜再笼统称为“原因未知的冲突”。Top-50 README 94.8% 与指定 JSON 90.4% 的对应关系仍待核实。[官方更新](https://mem0.ai/blog/the-token-efficient-memory-algorithm-now-has-temporal-reasoning)
2. **Cognee 的技术报告比宣传摘要限定更严。** 100K 79% 为 20 题的四轮平均，10M 67% 属于同题选配置的探索结果；重复轮数不增加独立样本量。它们不能直接证明优于 Hindsight 的完整 BEAM split。[技术报告](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/beam/REPORT.md)
3. **阿里云的 79.32% 存在来源口径差异。** 2026-08-03 产品介绍将其用于四类知识库问答，2026-09-08 社区文章又称为 LoCoMo，2026-10-15 文章给出四类 RAG 平均 79.3%。产品页与快速入门未核实到标准记忆榜分数。当前按“RAG 自报值、LoCoMo 待核实”收录，且不把开发者社区域名本身视为官方身份保证。[八月文章](https://developer.aliyun.com/article/1752686)、[九月文章](https://developer.aliyun.com/article/1761547)、[十月文章](https://developer.aliyun.com/article/1771153)

4. **Zep 的页面总计与分类有差异。** LoCoMo 总表报 1459/1540，分类正确数合计 1436、分母合计 1539，故只按页面自报值收录，不据此排名。它同时公布上下文中位数与检索 P50/P95。[来源](https://www.getzep.com/research/memory-benchmarks/)
5. **LoCoMo 评分方法要写清。** 原始问答代码主要使用词项 F1；Mem0 当前常见口径是 LLM 裁判正确率，类别 1–4 共 1540 题，不含 446 道对抗题。四类题型不是四种评分指标。[原始代码](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py)、[Mem0 评分定义](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/benchmarks/locomo/prompts.py)
6. **其他项目的历史指标分别保留。** MemTensor MemOS 同时公布 Overall 75.80%、答案 F1 45.27、tokens 2640；BAI-LAB MemoryOS 报 F1/BLEU-1，是不同项目。Membase 本地引擎报 LoCoMo 准确率 93.1%，40 题计时样本的上下文均值 6562，检索 P50/P95 1.67/7.02 秒、端到端 8.30/18.0 秒；这些都不是托管 API 指标。[MemOS 历史结果](https://huggingface.co/datasets/MemTensor/MemOS_eval_result/blob/1e791b0b305cef8a4385ce7ef09c5c9343baefa6/README.md)、[MemoryOS](https://github.com/BAI-LAB/MemoryOS)、[Membase](https://docs.membase.com/evaluation/benchmarks/)

## 其他已收集结果

下列数据用于后续选题，不与不同协议的主表混排。

| 产品及项目 | 结果与口径 | 来源 |
| --- | --- | --- |
| Hindsight / PersonaMem 32K | 510/589，86.6%；平均上下文 15811.6 tokens、平均检索 674.9ms | [结果文件](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/outputs/personamem/hindsight/rag/32k.json.gz) |
| Hindsight / BEAM | 500K 71.1%、1M 73.9%、10M 64.1%；官网 100K 显示 75%，固定结果清单一组为约 73.4%，分开维护 | [官网](https://benchmarks.hindsight.vectorize.io/)、[固定清单](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/results-manifest.json) |
| Hindsight / LifeBench EN | 1433/2003，71.5% | 同一 AMB 固定清单 |
| Hindsight / PrecisionMemBench | AMB 移植版 66/77、Active 33/43；原项目公布的 Hindsight 为 11/77、Active 0/43。版本、分类及过滤不同，不将差值归为引擎提升 | [AMB 固定清单](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/results-manifest.json)、[原版](https://github.com/tenurehq/precisionmembench) |
| Hindsight / sde-bench、locomo-fixed | coding 部分配置 61/61，也有 60/61，部分无记忆基线接近满分；一组 Gemma4 + agent 的 locomo-fixed 为 1284/1502、85.5% | 同一 AMB 固定清单 |
| Mem0 OSS / LongMemEval | 按不同抽取模型约 88.6%–91.0%；特定 Qwen embedding、GPT-5 作答及裁判，非默认安装成绩 | [固定评测 README](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/README.md) |
| Mem0 / Top-50 及 BEAM 通过率 | LME Top-50 自报 474/500、94.8%；BEAM 1M 通过率 491/700、70.1%，10M 为 101/200、50.5%，与连续平均分分别报告 | 同一 Mem0 固定评测 README |

## 来源与追溯

各结果在表内直接链接来源。固定源码快照为 AMB `28b644bd4dd653c0207c7507280439390c829155`、Mem0 评测仓 `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`、Cognee `5870f15d2488b99e80f71dd6e8e146b228749356`、OpenViking `2f41f1c7e95be5e7819d1f948fd6d220c5e0454a`、TencentDB Agent Memory `82b1ab4a2c47a5d65b99845841b7c659ac6f8497`，不把当前 main 的默认值当成历史实测配置。

- Mem0 四月 LoCoMo 结果为 1410/1540，LME Top-200 文件为 passed 467/500；两个 BEAM 文件的平均分与 README 一致。Top-50 文件为 452/500，仍须与新版运行匹配。LoCoMo/LME Top-50 样例为 GPT-5 作答与裁判、Azure provider。[LoCoMo 文件](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_results.json)、[LME Top-200](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/longmemeval_results.json)、[LME Top-50](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/longmemeval_top50_results.json)、[BEAM 1M](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/beam_1m_results.json)、[BEAM 10M](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/beam_10m_results.json)
- Hindsight 的 LoCoMo、LME、PersonaMem 文件头及前轮已读取的 BEAM 10M 结果均记录 Gemini 3.1 Pro Preview 作答、Gemini 2.5 Flash Lite 裁判；LoCoMo现已补齐并核验完整1540题逐题结果；LME、PersonaMem的该次本地记录仍以头部元数据为主。[BEAM 10M 文件](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/outputs/beam/hindsight/single-query/10m.json.gz)
- Cognee 的 LoCoMo 审计排除 143 题，其中与 96 道开放域重合 15 道，总排除 224、保留 1762；保留全部 446 道对抗题。两次结果为 1598/1762 与 1608/1762。[技术报告](https://github.com/topoteretes/cognee/blob/5870f15d2488b99e80f71dd6e8e146b228749356/cognee/eval_framework/locomo/REPORT.md)
- 阿里云正式产品页及快速入门用于确认产品身份，社区文章的作者归属和正式评测版本仍待进一步核实；不以同名 contextdb.ai 或 contextdb.tech 项目替代。[产品页](https://www.aliyun.com/activity/database/contextdb)、[快速入门](https://help.aliyun.com/zh/rds/apsaradb-rds-for-mysql/rds-contextdb-quick-start)
- OpenViking 原始 Claude Code 实验模型由其专用复现文档说明，不能推广到全部 Agent；当前 e2e、SDK 预写入、Mem0 单轮 QA 及 RAG 路径是不同实验。[评测说明](https://github.com/volcengine/OpenViking/blob/2f41f1c7e95be5e7819d1f948fd6d220c5e0454a/benchmark/README.md)、[Claude Code 环境](https://github.com/volcengine/OpenViking/blob/2f41f1c7e95be5e7819d1f948fd6d220c5e0454a/benchmark/locomo/claudecode/README.md)

原始证据保存在本机研究目录 `/Users/zhuqingping/Work/Database/Context/ContextDB-Research/.local-archive/benchmarks/official-20261118/`，manifest 记录 URL、日期、哈希及抓取失败，不随 Git 自动共享。Mem0 时间推理更新文章已通过网页工具核对，本地 HTML 抓取返回 403。执行安排与待办统一见[测试计划](plan.md)。

## 固定官方快照：1540题逐题对照

夜间离线核验并保存了 [逐题对照数据](results/official-locomo1540-20261119.json)。1540个问题均与固定LoCoMo的会话、原始索引、文本、类别和gold一致；没有依赖文件行顺序拼接。以下为已归档的历史运行，不能替代当前产品首页的新成绩。

| 指标 | Mem0 固定快照 | Hindsight 固定快照 | ContextBase 本机8K基线 |
| --- | --- | --- | --- |
| 正确数 / 分母 | 1410 / 1540，另有1道ERROR，计入分母 | 1417 / 1540 | 1419 / 1540，失败0 |
| 原裁判正确率 | 91.56% | 92.01% | 92.14% |
| reader / judge | GPT-5 / GPT-5 | Gemini 3.1 Pro Preview / Gemini 2.5 Flash Lite | GPT-6.1-sol low / GPT-6.1-sol low |
| 原版答案F1，本地离线计算 | 45.96% | 31.34% | 27.65% |
| 逐题检索P50 / P95，本地离线计算 | 3055 / 6002 ms | 882 / 1431 ms | 15307 / 19465 ms |
| 平均上下文 | 此逐题文件未提供 | 36235 tokens | 7806（o200k）/7930（cl100k） |

F1使用固定LoCoMo原版规则：类别1使用multi-answer F1，类别3使用分号前的首答案，其余为词项F1；逐题取均值。两家的正确判定保留原文件，不重新判题。检索百分位使用文件中的 `search_latency_ms` / `retrieve_time_ms`，不把它们当作相同边界的端到端时延。F1和百分位是我们的派生统计，**不是厂商额外发布的指标**，也不代表模型、预算和裁判一致的横评。完整版本URL、原文件SHA-256、每题答案及两家判定均在JSON记录。[Mem0来源](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_results.json)、[Hindsight来源](https://raw.githubusercontent.com/vectorize-io/agent-memory-benchmark/28b644bd4dd653c0207c7507280439390c829155/outputs/locomo/locomo-hindsight/rag/locomo10.json.gz)。

### ContextBase完整基线的环境、账目与下一轮

本机Apple M5、24GiB内存；API为8892，PG18.4/pgvector0.8.6。导入GPT-6.1-sol medium，答题/裁判均为GPT-6.1-sol low；向量为doubao-embedding-vision、1024维。重排为固定BGE revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`，CPU FP32、batch8、重排并发1，QA并发2。完整Bank为272份session文档、1942条事实、588个chunk，observations关闭。

API事实/原文预算各8192；reader总预算8192、事实/原文各4000，算法`complete-json-separate-budgets-v2`。全部1540题沿用固定AMB原reader/裁判模板及原版LoCoMo F1，数字gold保留原类型。运行前后10个Bank的公开配置和服务版本快照逐字一致，原文与导入任务也经只读核验；没有在途调参或按错题反复抽样。

上下文共12,021,123 tokens，平均7805.92；完整答题prompt平均8001.61（均o200k估算）。provider已知答题用量11,539,009、判题811,225，合计**12,350,234 tokens，加12次失败尝试的未知用量**；不包括retain及记忆服务内部模型用量。12次均按预设max4重试后成功，未产生失败题。检索时延是完整HTTP recall边界，包含本机串行重排等待，不是纯PG SQL时间，也不包含答题/判题。

| 原始类别 | 正确 / 总数 | 准确率 | 答案F1 |
| --- | --- | --- | --- |
| 1 多跳 | 263/282 | 93.26% | 30.47% |
| 2 时间 | 288/321 | 89.72% | 26.53% |
| 3 开放域 | 67/96 | 69.79% | 13.92% |
| 4 单跳 | 801/841 | 95.24% | 28.69% |

当前主要限制分为：未返回的原文、最终事实/原文打包遗漏、reader对具体事件或caption定位失误、开放域推断与非唯一推荐gold，以及明确人物/日期标注冲突。121道错题均有原问题、gold、实际答案、裁判理由、原文核验结论及下一步验证建议。分类诊断不等于已修复数量；含争议题仍按原判定计错，不删题、不改gold。

与固定历史判定逐题对照：相对Mem0，我们独对75题、对方独对66题；相对Hindsight，我们独对60题、对方独对58题。只比较总百分比会掩盖大量不相同的错题，而且reader/judge不同。92.14%也没有超过Mem0主仓库另一版本的92.5%或已收集Zep自报94.7%；不能据此宣布榜单第一。共同裁判复判仍是待执行的派生实验，不能替代友商新服务运行。

已启动独立窗口候选`locomow8_20261119_0308`：同一10个Bank，只读复用、无新导入、全部1540题重新按新方法答题。保持reader8K和事实4K/原文4K，仅将API原文候选预算8192→65536，并用预先冻结的`query-turn-windows-v1`选择完整消息窗口。模型/裁判保持相同；运行前只读verify已通过。此轮结束前不报告候选分数，基线和旧结果完整保留。

### PostgreSQL增强前提核验

本机应用连接以只读事务查询：PG **18.4**、pgvector **0.8.6**、pg_trgm **1.6** 已安装；`pg_search`、`pg_textsearch` 不在可用扩展列表，PGroonga和AGE可用但未安装。因此不能把现有英文GIN/`ts_rank_cd`称为BM25，也不能宣称已有原文BM25。当前账号不能读取 `shared_preload_libraries`，已记录未知，没有提权或变更配置。

指定研究HTML的SHA-256为 `96049e2b258fe09de7ac0f404c3a0fe934984c8528b7b6a7b24759d6f3c7ea79`。其中PG16/旧vector测量与本机版本不同，SQL下推的收益需要重新测量。当前优先分清两类问题：原文窗口打包可解决“已返回却未入上下文”，原文全文检索可补“事实抽取遗漏导致候选缺失”；SQL融合、延迟物化和图递归下推主要降低数据库耗时，不直接证明正确率上升。完整基线运行期间不变更共享数据库扩展、索引或服务参数。

官方两份快照逐题交叉：双方都正确1330题、都错43题，只有Mem0判对80题、只有Hindsight判对87题。conv-30分别为71/81、74/81；我们的旧Bank BGE运行是76/81，但模型、裁判和预算不同，不能把这三项当作严格同环境竞赛。

裁判差异可从原答案直接看到：conv-30_q31的gold是“six months”，Mem0回答“about 4 months and 13 days”仍标为CORRECT；Hindsight回答“5 months and 1 day”标为WRONG。q073的gold为“magical”，Mem0回答“Joy”标CORRECT。这里保留原判定，不擅自重标；它说明需要同时看实际答案、F1和裁判规则，不能只看准确率。具体答案可查上方JSON对应question_id。

### 原文预算三题诊断

独立优化分支提交 `1ab6dfb17`，旧Bank只读实测：保持事实API预算8192，仅将原文API预算8192→65536；三题的事实ID、内容和顺序完全相同，原文由8192增至19843 tokens，31个返回chunk均无截断。q073的“magical”原句因此进入回包，再由窗口选择进入最终8K上下文。q037的Shia、q044的graceful原句也保留。最终上下文为7984/8001/7976 tokens，单次recall为6.70/6.30/6.04秒；未调用reader或judge，不报告新准确率。

这表明q073首先可通过**较大原文候选预算+固定reader预算内的窗口选择**验证，暂不需要为这一题引入全文扩展。该结论只针对这三题和当前Bank；其他题仍可能缺原文候选。每次probe前后核验19个原文文档、公开Bank配置和服务版本，原档案不写回；原始回包、来源脚本和哈希保存在独立worktree `.local/conv30-raw64k-probe-20261119/`，精简统计为该分支 `results/conv30-raw64k-probe-20261119.json`。

全量新基线导入后实测：**10个Bank、272文档、1942条事实、588个原文chunk，embedding 1024维**。PG18.4/pgvector0.8.6下，检查到的事实GIN和HNSW等相关索引全部有效。`budget=high`的实际Bank配置为fixed high=1000，部署源码的通用rerank候选上限默认300，未在api.env覆盖；该预算不等于实际返回事实数，返回事实还受请求的max_tokens限制。原文获取是在事实token过滤之前从候选事实关联chunk独立执行，仍会受原文预算和“没有事实关联的chunk”限制。相应配置/源码/SQL核验均保存在run档案，不能以索引有效宣称参数最优。

### 基线首批错题：标注与裁判差异

conv-26_q5问Melanie何时参加慈善赛跑。D2:1原文是“last Saturday”，session时间为2023-05-25，事实抽取和我们的答案均为**Saturday, May 20, 2023**；gold却写此前的Sunday，我们的裁判因此判错。原文、抽取、答题在这一例中一致，属于标注冲突，不应归为抽取日期算错，也不会修改gold或分母。

更直接的横评差异是：Hindsight公开答案与我们的答案**逐字相同**，但官方标为正确；Mem0回答May 20也标正确。因此准备沿用我们的固定GPT-6.1-sol low及AMB原裁判prompt复判两家已公开答案，共享完全相同输入的判定；保留两家原始成绩并另列共同裁判的派生结果。此举不重新调用友商记忆系统，也不能消除reader、检索预算和硬件差异。当前仅完成脚本和离线验证，尚无新的统一裁判成绩。

另两个初期错题conv-26_q21（picnic时间）及q26（读书年份）没有在8K API原文中找到其参考证据，回包均有预算截断；它们将进入完整基线的逐题诊断和已冻结原文预算候选验证，尚不据此断定某个优化必然答对。

运行归档问题说明：首152题生成完成后，原保存schema因6个数字类型gold中的2022报错。已修复为保留原始字符串/数字类型，完成真实1540题schema审计和恢复回归；未改变参考答案、评分或重新采样已完成答案。当前完整基线接续于 `locomo1540r_20261119_030518`，旧目录、全部调用记录与导入Bank保留。此故障及中断召回的恢复记录见plan，不把部分结果发布为完整成绩。

### 已归档错题的逐题排查

首两组233题封存后，已检查其中20道错题。暂分为13道涉及上下文可见性/事件选择、4道时间或人物指代标注疑点、2道人设推断、1道图片内容解释；这是诊断归纳，**不是已修复数量，也不是完整榜单成绩**。原文、参考答案、模型答案及建议逐题保存在 `.local/triage-first233-v2-20261119.json` 和 `.local/triage-first233-review-20261119.json`，由analysis.py只读生成基础证据后逐题检查原文，没有额外benchmark答题或判题调用。

q132尤其说明ID覆盖不等于答案覆盖：参考ID D16:7是Caroline从17岁画画的说法，下一轮D16:8才是Melanie做艺术七年。API回包包含后一句，最终上下文遗漏；固定v1窗口离线回放已恢复该原句，但尚未调用reader验证。q13则同时存在泛称服装店的1月营业线索与3月明确网上店开张说明，须恢复被打包省略的后者，不能仅凭答错认定抽取凭空造假。

官方说明LoCoMo对话由赋予人设与事件时间线的虚拟LLM代理生成，再经人工过滤和修订。q50出现了对角色属性推断的拒答，q59还有证据强度不足的歧义，故后续可另立**全局说明合成人设来源**的reader实验，准确限定为本合成数据的虚拟对话者。当前未改变基线/窗口候选或裁判，也不把此做法套用于真实人物的敏感属性推断。[LoCoMo官方项目](https://snap-research.github.io/locomo/)

分类统计采用原数据数字编号：1多跳、2时间、3开放域、4单跳；本次固定AMB版本的展示标签把1/3/4依次叫作single-hop/multi-hop/open-domain，与原始评测含义不一致。因此本地归档保留原编号，不用这些展示名字直接横拼分类分数；1540题总范围、原QA和评分模板均未因此更改。[固定AMB分类代码](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/src/memory_bench/dataset/locomo.py)

第四组conv-42落盘后，已将全部44道已落盘错题合并保存到[逐题诊断数据](results/locomo1540-error-analysis-20261119.json)，来源范围584题，仍不是完整成绩。新发现包括：q14昵称Jo的原句未返回；q34、q91的部分书名/dragons线索只在原始图像搜索query，固定v1窗口未保留此字段；q92灯色连文本、caption和query都没有，不能承诺扩大文本预算即可解决。任何图像或元数据增强均须另列输入口径及模型成本。

q54尤其不能误诊为抽取幻觉：10月23日原文D25:4明确说third time，抽取据此标第三次；题目和gold却把这次上映叫第二部。q24原文two weekends later与gold的weekend after June3、q43约三个月与gold含首尾四个月，也存在时间表述歧义。q62同时有未明确为信的拒绝被reader计入，以及gold未计童年兄弟信的范围问题。后续优化需分开检查可修复的无依据计数和原始标注争议，不能删去不利原文或修改gold追分。

第五组conv-43落盘后，累计762题中的60道错题均完成原文检查，更新同一逐题诊断JSON。其中新增明确人物/时间冲突：q135的visualize方法属于John而非Tim；q164的Spanish也是John，Tim实际提French；q6在7月16日说last week，gold却给June；q60在12月11日说last Friday，gold用session当天。q56还有violin/piano前后混用。它们不能靠提高检索或错误转写人物来修复。另有多道开放域推荐题将一个特定商店、组织、书名或瑜伽样式作为唯一gold，而原文只提供兴趣条件；reader给其他建议即被判错。后续保留原判定并做共同裁判对照，不修改gold，也不将合理性争议直接记为系统正确。

第六组conv-44完成后，885题中70道错题均已检查。q39的companionship原句已返回未打包，是可直接验证的窗口改进目标；q17则需要区分计划的重复叙述与独立徒步事件。q5的last week及q57的Scout收养月份有原文/gold冲突。q43/q44可能依赖地图图像，文本、BLIP caption和image query均没有州/公园名称；原图网页获取失败，未声称已识别地图，也不把其他照片的Oregon URL当作确定居住地。扩大原文预算不能自动解决视觉信息缺失。

第七组conv-47完成后，1035题中80道错题已逐题检查。q147现已出现实际错题对应此前零事实关联chunk：gamepad/timing原文没有经事实关联返回。这是独立原文检索值得验证的具体依据，单纯放大关联原文预算不保证触达；后续必须按题目做通用检索，不能按gold证据ID补原文。q71则是已返回的宠物帮助offer未打包。q31的7月11日至20日被gold写成19天、q11的4月20日two days ago被题目问为4月10日，均保留源冲突。q62另需区别初识/早期约会与正式确立关系两个时间锚点，不能简化成日期算错。

第八组conv-48完成后，1226题中95道错题均已逐题检查。q74/q99是原数据重复问题，保留两个索引和1540分母；咖啡/糕点原句均已返回未打包。q119则caption已在上下文，reader却回答图片所代表的待办压力而非可见desk/notebook/monitor，属于答题定位问题。q101提示应保留相对日期及session锚点；仅报January2022时，只有a year ago的无上下文gold无法验证等价。q116/q174还出现人物归属冲突，q87把Deborah的Bali对应成Thailand，而明说Thailand的是Jolene。

运行中conv-48_q57 judge一次UpstreamHTTPError、q127 answer一次CodexStreamError，均第二次成功，未生成失败题。两次失败尝试usage为null，最终Token只能报告已知用量并另列未知尝试；没有HTTP状态码等证据将其直接认定为限流。原失败尝试及后续成功用量和调用哈希均保留。

第九组conv-49完成后，1382题中112道错题均已逐题检查。q32直接说明事实打包也有瓶颈：丢钥匙事实已在API第44/69位，最终4K事实预算没有保留，相关原文也未返回；仅增大API预算并不等于增大reader可见预算。q123所需lost tourist原句与Sam评论已经在上下文，仍被泛称户外爱好覆盖，属于reader定位问题。q153也重复出现caption有kayak而reader只描述文字中的sunset。另有明确源/gold冲突：q54 knee/ankle、q74 Tuesday/Thursday、q80 2024/2023，以及q24/q144人物调换；全部保留原判定，不修改数据追分。

后续reader与32K实验已离线准备：简洁答题/正确使用caption及时间锚点采用显式不同的reader-v2协议，原裁判不变；通过完整检索快照重放可避免数小时重复CPU检索。它会重新回答并判定全1540题，不混合各轮最优答案，借用的检索时延单独标记。配置与来源哈希预登记，当前未执行；没有新准确率或F1。此指导基于已查看的全量基线错误设计，后续成绩属于公开开发集调优，不宣称留出泛化。

窗口候选首组152题的配对诊断显示8道旧错转对、1道回退（q68），详见[部分诊断数据](results/locomo1540-window-diagnostics-20261119.json)。这不是全量候选成绩。q68和q132问同一艺术年限，只有后一题的8K选窗保留了Seven years；这证明现有窗口仍有措辞敏感性。q66已有部分营火活动支持却未答出，也存在reader定位问题。既定32K仅离线重打包恢复了q68原句，不代表新准确率；全量窗口运行和预登记方法保持不变。

窗口候选conv-30的81题完整落盘：同一新Bank由基线75/81变为79/81，4道转对、无回退；旧Bank的76/81仍单独保留。Shia和graceful均有新上下文与明确答案支持；magical虽然已进入上下文，reader仍未说出该词、F1仍0，只是原judge把joy/freedom判为同一感受，因此不能把4道转对全部归为目标原词准确恢复。剩余q43在上下文已有festival原句时仍回答象征意义，q31保留五/六个月的时长争议。前两组共233题配对更新同一部分诊断JSON，仍非1540全量成绩。

网络切换后窗口轮从`locomow8r_20261119_011537`接续：原591个完成调用逐条不变，10个Bank重新只读核验通过；仅补中断未返回的阶段，未重导入、未改模型/提示/预算。旧窗口目录和配对证据保留，不能把两个目录各自当成两轮独立完整成绩。最终汇总将沿恢复链统计，当前仍没有全量窗口成绩。

窗口conv-41完整152题：143对→147对，5道转对/1道回退。q4新旧均为December19–25、F1均0，却被judge按不同周定义判为错/对；q45也有谨慎语气的判定差异，不能将全部净增解释为检索收益。新回退q94的真实菜品答句D13:18已在接口回包，同一chunk中D13:16/17被选入而18被遗漏；既定32K仅离线重打包保留该句，尚无新准确率。累计385题部分对照为17转对/2回退，完整窗口仍未结束。

窗口恢复轮的耗时抽样（conv-42进行中，非全量性能成绩）：50次完成答题的P50为4.65秒，50次完成判题为3.33秒，51次有效recall HTTP为16.92秒。此时主要等待在检索链路；recall含embedding、服务排队、检索与rerank，不能将16.92秒全部归为模型计算，也没有证据据此认定LLM限速。各阶段并行重叠，不能直接将三个中位数相加预测总时间。逐项统计与限制已附在同一[部分诊断数据](results/locomo1540-window-diagnostics-20261119.json)，原记录哈希保存在私有归档，未改变当前实验配置。

conv-42进行中的四题源文核查还区分了预算与输入信息问题：q14昵称Jo已在API原文中，却未进入reader上下文，属于打包遗漏；q34的Little Women已入上下文，但原句讲电影，另一本书名只见于图片搜索query；q91的dragon同样只见于所引图片的搜索query，BLIP描述仅为桌上的书；q92所引图片的文字/caption均未描述红紫灯光。当前声明的窗口方法不把图片搜索query当作图片观察，也未重新读取图片，故后两题不能承诺靠扩大预算解决。四题仍保留原judge判错，未更改本轮输入规则；这是局部源文诊断，不是该Bank或全量新成绩。

对conv-47_q147的只读PG核查补充了原文检索方案的边界：相关session_30已被事实检索命中，但D30:18位于同文档的另一个零事实关联chunk（index=1），所以当前按chunk_id回查不会带回它。若把所有命中文档的chunk都补齐，该题的事实结果实际上覆盖31/31个session，会把候选扩成整Bank的64个chunk；这不宜被包装成一次小范围邻接补齐。后续应优先验证按问题进行的、有限额的独立原文检索/排序，并继续固定reader预算，而非直接无条件把整Bank当上下文。此处只做可行性核查，未把补查原文送给模型或修改运行中的API。

按冻结manifest顺序固定前518题、逐条核验已完成答题/裁判/检索记录后，同范围配对结果如下（含conv-42前133题，非1540全量成绩）：

| 指标 | 上轮基线，同518题 | 本轮窗口，同518题 |
| --- | --- | --- |
| 答对数 / 准确率 | 475 / 91.70% | 490 / 94.59% |
| 答案F1 | 25.90% | 26.93% |
| 平均上下文tokens | 7812 | 7976 |
| 检索P50 / P95 | 13.28 / 18.15秒 | 14.51 / 21.56秒 |

18题错转对、3题对转错，净增15题（+2.90个百分点）；其中conv-42前133题是1修复、1回退、正确数持平。这里只比较同一批题，不拿上轮1540题总分替代同范围基线，也不按是否成功或快慢筛题。第一518题按固定题目顺序选取，未声称重建10:08时两路并发完成顺序的瞬时边界。部分转对有judge波动，具体因果仍需逐题核查。结构化数据与来源哈希见同一部分诊断JSON及私有快照。

窗口候选第四组conv-42的199题已完整落盘：基线184/199，本轮仍184/199，F1从27.61%到27.48%；1修复（q60机型推断更具体）、1回退（q23）。q23两轮都没有明确答出第一部drama/romance，旧judge接受部分重合、新judge拒绝，不能简单归因于新窗口截掉该事实。15道本轮错题及修复题均补了源文诊断：q14昵称原句持续漏选；q53把其他户外活动也算散步；q78涉及参与/获胜与事件去重；q195有邀请方向冲突。前四组共584题净增15题（18修复、3回退），仍不代表其余956题，配置和裁判不变。

原文检索方向另做了不调用模型的全1540题离线候选可行性检查：只读快照588个存储chunk，按问题对可观察文字/caption做BM25式top4检索，再补同文档相邻chunk，候选最多12个、平均7.87个。与原8K-raw基线候选取并集后，121道旧错题中“含至少一个参考ID”由99到115，“含全部参考ID”由83到103；q147的D30:18可由FIFA相关种子chunk及其相邻chunk触达。单独词法分支覆盖反而低于原检索，故只支持互补分支假设。**这是参考ID覆盖，不是20道题已修复，更不是PG原生BM25性能；还未做reader预算打包、新答题/判题或部署。** 当前64K窗口轮仍运行，后续须对其完整回包重新检查增益，不能把针对旧8K候选的增益直接加到新分数上。实现与全1540候选已独立哈希复验，不修改共享数据库、索引、服务配置或当前实验。

窗口候选第五组conv-43完整落盘：基线162/178，本轮160/178，1转对、3回退，F1从26.58%到25.90%。前五组762题总体由702题正确（92.13%）到715题正确（93.83%），净增13题（19修复、6回退）；不再用较早584题的95.03%代表最新阶段。新旧同范围F1为26.74%→27.23%，上下文7812→7978 tokens，检索P50/P95为15.23/18.68秒→16.99/29.32秒。18道本轮错题与1道转对已逐题记录。

本组回退暴露了窗口输入策略的具体差异：q48/q49旧JSON上下文含图片搜索query的ankle说明，新窗口只保留正文和腿部包扎caption；November16 injury事实仍存在，但与ankle的关联可能减弱。固定AMB的_session_content直接json.dumps原始turns，包含原有query元数据；这些字段不是QA gold。今后若恢复原始元数据，应明确标为source image-search query（不冒充图片观察），作为全局固定的新协议单独验证，不能在当前轮只为错题补齐。q166的gold证据则属于Tim而题问John，两个因素不能混为“单纯截断”。当前V1保持不变，所有旧答案和原判保留。

元数据候选已固化为独立`query-turn-windows-metadata-v2`：统一保留原有图片搜索query并显式标记为source metadata，不冒充图片观察。78项离线检查通过；六题旧v1打包逐项复现，新候选可在8K内保留ankle/dragon/书名搜索元数据，但不会生成不存在的灯光信息。候选没有新答题/判题分数，当前V1冻结代码哈希已核对不变；完整缓存来源门禁已实际拒绝未完结来源。后续先单独验此输入差异，再组合reader提示/预算，历史准备配置和结果均保留。

重排并发短测现已完成（独立进程、原实例同时运行，两个保存问题各176/184条返回事实，ABBA顺序1/2/2/1）：相同两题任务平均45.92秒→36.92秒，耗时降低19.6%、吞吐增加24.4%；8次推理的两题全部分数与排序完全一致。它不是API端到端P50，不覆盖内部完整候选，也不是全题质量保证。10核/24GiB机器可试2并发，但不会据此预期翻倍；8892未改并发、未重启。PG实际当前10Bank数据+索引共92495872 bytes（约0.092GB），加旧LoCoMo Bank98648064 bytes；模型文件和结果归档不在该值内。协作交接统一在plan，成绩简表保持精简。

用户随后授权8892改为2并发：评测暂停23.42秒后原进程恢复，851题已完成记录原样保留；模型/精度/batch/QA并发和记忆不变。当前V1后半轮使用2并发，初始manifest仍记录起始1并发，有效资源阶段详见部分诊断JSON。切换期间预先捕获两条在途检索，其中一条无响应HTTPFailure待限次传输恢复；不重答已完成答案。最终时延将分段报告，不把此轮混合资源的时延当作统一1/2并发性能基线；质量仍要求完整1540题。

按最终成功judge完成时间固定最先完成的881题（不按对错筛选），本轮823对/881=93.42%，同题基线811对/881=92.05%，20修复、8回退、净增12题；这与此前按完整Bank选762题的范围不同，两份快照都保留。中断q90尚无语义结果，不计入“已完成881题”的分母，最终成绩仍必须1540题完整。原记录哈希和题目清单已归档；收尾只补有暂停前哈希证明的未返回请求，不重答语义错题。

前七组1035题中已完成1034道语义QA（q90中断待补）：基线954对92.26%，本轮968对93.62%，23修复、9回退，净增14；F1仅27.27%→27.42%。新增两组所有语义错题、修复及回退均已核查，现有89条配对诊断（含修复题），不会把运行中断当语义错题。q37几乎同一日期回答在两轮获不同判定；q55的safe-space事实已在上下文，却被误解为狗托管空间；q56明确来访原句漏选，但其他sister事实仍在。q147虽然判对，D30:18及timing仍缺失，仅controls被宽松接受，不能称独立原文检索问题已解决。

F1格式实例：q39新答案明确包含companionship，但实际文本为companionship—a，原始F1归一化产生词项连接，分数仍0；只在离线诊断中加分隔空格得到0.20，未改变真实答案或固定评分。旧上下文事实原已包含companionship，新窗口增加原文帮助定位，不能说原系统完全没召回相关信息。后续简洁答题格式可能影响F1，属于待单独验证项，不替换本轮成绩。
