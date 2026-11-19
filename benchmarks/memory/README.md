# ContextBase Agent Memory 打榜

本目录统一维护打榜脚本、配置、测试、执行计划和友商报告。工作分支为 `memory-benchmark`，基于个人远端 `zhuqingping/contextbase_v1` 的 `4cdec7b54a2c818bd17e3addf36f9de9bd95372a` 创建。

## 唯一维护版本

**只维护本仓库 `memory-benchmark` 分支中的 `benchmarks/memory/`。** 执行入口为本目录 `runner.py`，配套修改同目录 `support.py`、`analysis.py` 和测试；所有改动提交到这一个分支，不在 `.local` 中开发另一套。

- 同事开发、离线验证、新建测试：使用本目录维护版；当前V1方法使用 `config.window-v1.example.json`，记录实际Git提交号。
- 新测试初始化时自动将源码和配置冻结到新的run目录，之后该次运行始终使用自己的快照。
- `.local/runs/<run_id>/` 是历史证据和运行快照，不是维护版本：不更新、不覆盖、不提交Git。旧Bank、旧结果保持原样。
- 正在执行的本轮不替换脚本；其结束后，新运行统一从本目录维护版创建。维护一个源码版本，同时保留每次运行证据。
- 客户端代码维护分支与8892服务端部署版本分别记录；推送评测代码不会自动升级服务端。

协作仓库统一为 [ZhuQingping/hindsight 的 memory-benchmark 分支](https://github.com/ZhuQingping/hindsight/tree/memory-benchmark)。同事从该分支派生自己的工作分支，改动经PR汇总；正式评测由主控统一调度，避免同时占用8892的CPU reranker。新工作目录可用：

```bash
git clone --branch memory-benchmark https://github.com/ZhuQingping/hindsight.git
git rev-parse HEAD
```

记录实际提交号后，按下文执行离线验证。原始`.local`档案、OAuth/数据库密钥和模型权重不在Git中；同事可先做离线开发，真实复测需按环境清单准备服务及对应Bank。

| 文件 | 用途 |
| --- | --- |
| [locomo-optimization.md](locomo-optimization.md) | 客户端窗口优化的目的、1540题效果、36题改善与13题回退、成本与限制 |
| [locomo-optimization-cases.md](locomo-optimization-cases.md) | 全部49道变化题及原始档案定位 |
| [recall-profiles/design.md](recall-profiles/design.md) | recall_profile服务端选窗迁移设计；与PG检索下推独立 |
| [recall-profiles/validation.md](recall-profiles/validation.md) | 默认兼容、1540份重放、81题真实对照与复测验收 |
| [plan.md](plan.md) | LoCoMo 通俗流程、模型和评分口径、公平对比、待办、历史结果及错题分析 |
| [report.md](report.md) | 友商 benchmark、模型、分数、Token、时延与原始来源 |
| [recall-pushdown/README.md](recall-pushdown/README.md) | PG Recall 下推专项：首版实现、81题可行性验收、设计与执行证据；尚未部署 |
| [runner.py](runner.py) | 唯一执行入口：init、preview、ingest、verify、run、report |
| [support.py](support.py) | 配置类型、完整条目/原文窗口打包、HTTP 导入核验、原始 LoCoMo F1；没有独立执行入口 |
| [analysis.py](analysis.py) | 完整结果导出、官方对照、只读进度、错题证据与离线覆盖诊断 |
| [probe.py](probe.py) | 本地重排和只读 recall 小样本诊断，不答题、不判题 |
| [config.example.json](config.example.json) | 早期conv-30模板，不是当前V1配置 |
| [config.window-v1.example.json](config.window-v1.example.json) | 当前V1方法复测模板：复用10个旧Bank，64K原文候选、8K最终上下文 |
| [requirements.txt](requirements.txt) | 仓库 Python 环境之外的评测/测试补充依赖 |
| [tests/test_runner.py](tests/test_runner.py) | 固定 AMB 代码＋合成会话＋模拟服务/模型的离线检查 |

**当前状态：两轮1540题均已完整完成并通过核验。** 基线1419/1540（92.14%），窗口优化1442/1540（93.64%），净增23题；F1 27.65%→28.01%，平均上下文7806→7980 tokens，检索P50/P95 15.31/19.47秒→21.99/32.91秒。本轮资源中途reranker1→2，时延为混合条件，已分段归档。见[完整优化结果](results/locomo1540-window-20261119.json)、[逐题诊断](results/locomo1540-window-diagnostics-20261119.json)和[报告](report.md)。84项离线检查、Ruff和类型检查通过；既有全局http.py F841另记。

**本轮优化发生在哪里：**服务端核心检索代码、PG索引、原Bank未改。客户端把recall原文预算从8192提高到65536，然后在`support.py:pack_query_windows()`用Python的BM25式词面评分（另含相邻词加分）选择消息及前后各一条；最终仍是约4K事实＋4K原文。它不是PG执行的BM25，也没有额外调用大模型。答题/裁判模型及指令模板不变，改变的是给答题模型看的记忆内容。运行资源另有reranker并发1→2，独立分段记录。

**对外口径：**“ContextBase＋客户端窗口打包，在LoCoMo类别1–4共1540题上，固定AMB裁判准确率93.64%、原版答案F1 28.01%”。这是LoCoMo数据集上的可复现方法实验，不是官方论文完整模型/设置的复现，也不是同条件友商排名。原数据/gold/评分不改；QA参考证据只用于事后诊断，不参与检索与打包。官方也提供不同数据库与检索设置的RAG实验：[LoCoMo说明](https://github.com/snap-research/locomo#code)，[原评分代码](https://github.com/snap-research/locomo/blob/main/task_eval/evaluation.py)；当前准确率来自[固定AMB的模型裁判流程](https://github.com/vectorize-io/agent-memory-benchmark/blob/28b644bd4dd653c0207c7507280439390c829155/README.md)。

**同事协作入口：**见[plan中的协作交接](plan.md#协作交接2026-11-19)。本轮36题转对、13题回退，98道当前错题均有来源检查；传输补齐只新增q90的answer/judge，其余1539题原答案和判定原样保留。当前仅归档交接，未自动启动元数据、reader/32K、共同裁判或PG新QA实验。

历史conv-30：旧版91.36%、F1 25.15%；新AMB协议RRF为70/81、86.42%、F1 21.98%；旧Bank接入BGE后为76/81、93.83%、F1 26.64%。完整基线使用全新抽取Bank，其conv-30为75/81，不能把旧Bank成绩拼入全量。各次旧结果和Bank均保留，prompt/裁判不同的运行不作为单一打包改动的因果对比。

## PG Recall 下推专项

**等价实现更新：** 原始版、修改关闭、修复开启已完成独立对照，RRF/真实BGE各81题完整响应、融合结果及reader正文与原始版一致；每题一次候选SQL、零后续补查。限定固定81题与哈希环境，未切换原服务；见[首版报告](recall-pushdown/implementation-report.md)。现有打榜服务、Bank和成绩不变。

下推设计和分析已统一到 [recall-pushdown/](recall-pushdown/README.md)：[当前设计](recall-pushdown/design.md)、[分析报告](recall-pushdown/analysis.md)（[HTML](recall-pushdown/analysis.html)）、[进展](recall-pushdown/progress.md)和[下一步计划](recall-pushdown/plan.md)。今后在此维护，旧研究目录保留历史快照。

**状态：首版候选下推已实现并完成81题可行性验收。** PG一次四路检索、RRF和补全，ContextBase复用BGE/评分/预算，无后续补查；RRF与本地BGE各81题HTTP响应、reader输入及一次查询检查均通过，见[首版报告](recall-pushdown/implementation-report.md)。仅针对旧conv-30，不更改全量打榜服务或源Bank；尚未部署，也未证明端到端提速。

## 配置归档与同事复测版本

**客户端与服务端分别固定版本，不能用一个“最新代码”代替。** 同事使用包含本节的`memory-benchmark`提交及其V1模板，记录实际`git rev-parse HEAD`；已有运行继续使用自己run目录中的冻结源码。

| 归档 | 位置与内容 |
| --- | --- |
| 可提交的V1配置 | [config.window-v1.example.json](config.window-v1.example.json)：模型、类别1–4共1540题、10个旧Bank、recall事实8192/原文65536、最终上下文8192（事实4000/原文4000）、窗口算法、QA并发2；新复测统一reranker并发2 |
| 可提交的环境清单 | [environment-20261119.json](results/environment-20261119.json)：客户端/AMB版本、服务端部署基础commit、497份服务源码指纹与13份差异、依赖版本、脱敏env、模型权重版本、PG插件/索引/可见参数 |
| 本机完整运行档案 | `.local/runs/locomow8r_20261119_011537/`：manifest.json、冻结源码、检索回包、打包上下文、answer/judge完整交互；不随Git推送 |
| 资源变更档案 | 上述run的`performance-epochs.json`及`performance/reranker2-switch-20261119/`：原运行reranker从1切到2的时间线；env备份含密钥，只留本机 |
| 服务端实际配置 | `/Users/zhuqingping/.local/share/contextbase/deployments/gpt61-20261107/runtime/api.env`，含密钥，不提交 |
| PG只读审计 | `.local/pg-baseline-audit-20261119/`；插件、索引与关键参数的脱敏副本已合入环境清单。审计连接参数不能证明API每条查询的SET LOCAL值 |

当前8892部署为`gpt61-20261107-dd5521cb9`，基础commit为`dd5521cb948beff39a24d604f625bc4108d1aac2`，另有部署源码差异；**不是当前memory-benchmark分支的服务端代码**。清单用于核验，不是可安装的服务端镜像，仅checkout该基础commit不能保证完全相同。

同事若复测当前方法：固定本分支提交，用V1模板和自己的凭据/路径，连接当前8892及原10个Bank（远程访问需配置可达地址），按init → 冻结runner verify → run，不执行ingest。独立机器需恢复同一批Bank及匹配服务环境；重新导入或部署本分支最新服务端代码，应标记为新环境实验。不要直接执行manifest中的本机绝对路径。

模板统一使用当前reranker并发2；原运行是1→2的混合资源，因此方法复测不等于原时延逐值复现。模型输出也不保证逐字相同。PG密码、OAuth凭据、模型权重及原始`.local`均不会随Git推送，须按同事实际环境单独准备。

## 同一runner选择上一轮或本轮方案

**使用 `--config` 选择方案，没有 `--v1` / `--v2` 开关。** 为避免与内部算法版本号混淆，配置按“baseline（上一轮）”和“window（本轮）”命名：

| 选择 | 复测配置 | recall原文候选 | 打包方法 | 最终记忆预算 |
| --- | --- | --- | --- | --- |
| 上一轮基线方案 | [config.baseline-reuse.example.json](config.baseline-reuse.example.json) | 8192 | complete-json-separate-budgets-v2，response_order | 8192，事实4000/原文4000 |
| 本轮窗口优化方案 | [config.window-v1.example.json](config.window-v1.example.json) | 65536 | query-turn-windows-v1，query_relevance | 8192，事实4000/原文4000 |

两份均固定原10个Bank、1540题、相同答题/判题模型、AMB原裁判，不重新导入。旧的`config.full-baseline.json`用于创建新Bank的完整基线，不用它直接复测原Bank。模型/凭据/数据与AMB路径准备见下文；这里的模板默认当前8892、当前reranker并发2，不能逐值重现旧基线并发1或本轮1→2混合资源的时延。配置声明不会自动修改服务端，先核对环境清单。

在仓库根目录执行以下命令；先选择其中一个配置，每次使用全新的run目录和run_id。**以下命令会发起真实复测，当前整轮未完成前不要同时启动。**

```bash
# 二选一：上一轮基线方案
BENCH_CONFIG=benchmarks/memory/config.baseline-reuse.example.json
# 或本轮窗口优化方案：
# BENCH_CONFIG=benchmarks/memory/config.window-v1.example.json

BENCH_RUN=benchmarks/memory/.local/runs/my_retest_001
.venv/bin/python benchmarks/memory/runner.py init --config "$BENCH_CONFIG" --run-dir "$BENCH_RUN" --run-id my_retest_001
.venv/bin/python benchmarks/memory/runner.py verify "$BENCH_RUN"
.venv/bin/python benchmarks/memory/runner.py run "$BENCH_RUN"
```

这三步为：冻结配置与代码 → 只读核验原Bank → 答题与判题；**不执行ingest**。启动期间固定同一个Git提交，init会自动存下运行快照，无需到旧运行目录挑脚本。中途维护代码变化时校验会拒绝混用；恢复旧任务按其已归档运行快照处理。

## 离线验证

在代码仓根目录执行。已有仓库 `.venv` 时，只需按需补充评测依赖；安装命令不启动服务或模型：

```bash
uv pip install --python .venv/bin/python -r benchmarks/memory/requirements.txt
```

测试只需要固定版本 AMB 的源码，不需要真实 LoCoMo 数据、业务密钥或模型账户。当前机器已准备源码；其他机器先准备同一 commit 的 checkout，再设置路径：

```bash
export CONTEXTBASE_AMB_CHECKOUT="/path/to/agent-memory-benchmark"
.venv/bin/python -m pytest benchmarks/memory/tests -q --override-ini addopts=''
.venv/bin/python benchmarks/memory/runner.py --help
```

测试使用合成会话和临时本地模拟 HTTP 服务，不会访问 8891/8892 或调用真实模型。缺少 AMB checkout 时相关测试会显示跳过，不能将这种结果当作完整验证通过。

## 后续实测

先阅读 [执行计划中的命令与指标说明](plan.md#固化脚本与复测方法)。`init`、`preview`、`report` 为离线操作；`verify` 只读取产品服务核验，不调用模型；`ingest` / `run` 为实测阶段。

复用已有记忆时，在配置中设置 `reuse_banks`，例如 `{"conv-30": "locomo_conv30_20261118_200523"}`。新运行依次执行 init → verify → run；不能执行 ingest。脚本会核对原文、导入任务、公开配置和服务版本，并在 HTTP 层只允许指定 Bank 的 GET 与 recall，禁止创建、写入、删除和 reflect。留空则仍是新建 Bank 的导入模式。

连接中断后，可在新运行中通过 `checkpoint_source` 引用原 manifest 的路径与 SHA-256。脚本要求题目、Bank、模型、预算、prompt 协议和依赖一致，复制并校验全部已有检查点；已完成的对错判定不重新生成。仅在显式声明 `resume_connection_failures=true` 且每次增加一次尝试上限（总上限 4）时，允许没有任何响应的连接失败再尝试一次，并可降低恢复并发；未收到回包的中断检索可重新读取；原失败记录和未知用量全部保留。逐题操作失败会计入失败并继续余题，不再中断整组。

当前模板指向本机 API `127.0.0.1:8892`。部署基础为 `dd5521cb…`，并有后续 UI/网关更新；它与本分支不完全一致。脚本经 HTTP 测试部署实例，模型连接及辅助代码来自本分支，两部分版本分别归档。目录整理阶段未升级部署；2026-11-19 已按用户指令补齐本地模型依赖、切换 BGE 并重启，部署源码版本未变。

## 证据与维护

打榜正文在本目录的 README、plan、report 维护；PG Recall 下推专项正文统一在 [recall-pushdown/](recall-pushdown/README.md) 维护。旧的 `scripts/benchmarks/amb-contextbase*`、`contextbase-locomo*` 和独立旧驱动不再作为维护入口，也不进入本次提交。

原始数据、官方逐题文件、旧结果与验证证据继续保留在现有研究目录 `/Users/zhuqingping/Work/Database/Context/ContextDB-Research/.local-archive/benchmarks/`，本次不移动、不提交。新运行可放在本目录已忽略的 `.local/runs/<run_id>/`。任何凭据、运行数据、第三方源码 checkout、环境和缓存都不进入 Git。

## Reranker 小范围验证

`rerank_preview.py` 复用完成运行的召回快照，调用华为 `bge-reranker-v2-m3`，只重排事实，再按原预算打包；不访问 Bank，不导入，不调用 reader/judge。只传题目与候选事实文本，不传参考答案或证据标注。候选范围已经过原 recall 的预算限制，不能当作服务端全候选 rerank 的完整替代。

```bash
.venv/bin/python benchmarks/memory/rerank_preview.py \
  --source /path/to/completed-run-matching-current-harness \
  --output benchmarks/memory/.local/rerank-new-run \
  --key-file /path/to/private/modelarts-rerank.json \
  --questions conv-30_q27 conv-30_q29 conv-30_q73 \
  --interval 30
```

私有凭据文件为 `{"secret":"<API key>"}`，权限 600，不能提交。默认并发 1、请求起始间隔至少 30 秒；429 至少等待 30 秒并遵守数值 Retry-After，仅允许重试一次，超长等待或其他错误停止。归档请求、响应、全部尝试、排序与打包差异以及来源哈希；配置中只记录密钥文件路径。输出目录必须全新，旧结果不覆盖。三题实测及限制见 [执行计划](plan.md#bge-reranker-三题验证)。

本机固定版本 BGE 已完成相同三题的独立 CPU 测试，模型放在 `/Users/zhuqingping/Work/llm-learning/models/bge-reranker-v2-m3/`；版本、环境、速度与 MaaS 排名对照见 [本机验证记录](plan.md#本机-bge-固定版本验证)。2026-11-19 已按用户指令接入现有 8892，81 题复测已完成：76/81（93.83%），F1 26.64%，检索 P50/P95 为 6.34/6.85 秒；[完整对照](plan.md#8892-接入本地-bge-与-81-题复测) 单独归档。

## 分析数据与完整夜间基线

已提交的 [conv-30 逐题分析数据](results/conv30-bge-20261119.json) 包含81题的新旧答案、判定、F1、上下文与耗时、原文证据ID覆盖，以及模型/预算/数据和脚本哈希；不包含密钥或原始大上下文。`analysis.py` 仅离线读取并校验冻结档案，拒绝把未完成运行导出为有效基线，也拒绝覆盖已有导出。

```bash
.venv/bin/python benchmarks/memory/analysis.py \
  --run-dir /path/to/completed-run \
  --baseline /path/to/same-scope-baseline \
  --output benchmarks/memory/results/new-run.json
```

完整1540题配置使用 [config.full-baseline.json](config.full-baseline.json)，QA并发2、BGE重排并发1；凭据通过环境提供，数据与AMB路径按模板设置。`init` 后优先执行运行目录里冻结的 `runner.py ingest`，成功后执行 `runner.py run`。当前夜间实际基线及授权/边界/复核项见 [夜间任务记录](plan.md#2026-11-19-夜间自主任务)。旧Bank不复用为新导入目标，所有旧结果保留。

`probe.py` 固化了此前本机独立CPU与真实recall的诊断方法，两种模式均不答题、不判题，输出目录必须全新。`local` 只用已保存候选，核验固定模型权重，预热单列并记录重复计时；`recall` 通过强制只读Bank传输仅调用指定题目的recall。

```bash
.venv/bin/python benchmarks/memory/probe.py local \
  --source /path/to/completed-run --output /path/to/new-probe \
  --questions conv-30_q27 conv-30_q29 conv-30_q73 \
  --model-path /path/to/bge-reranker-v2-m3/953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e
```

真实recall验证使用相同参数并将 `local` 改为 `recall`、去掉 `--model-path`。源manifest中的模型配置是历史声明，实际服务版本及模型配置需同时归档，不能仅凭历史manifest声称部署配置已验证。

夜间守护使用 `night.py --run-dir <run> --record <new-status.json> [--original-pid <launcher-pid>]`。它监视现有执行者和运行锁；原进程退出且无其他执行者时才调用同一份冻结 runner 接续。它不增加模型尝试上限，不重答已有结果，不把失败基线导出为成功，也不自动提交/推送。完成后在本机 run 内生成 `public-results.json`，经复核后再保存到 results/ 并提交。

`analysis.py --run-dir <frozen-full-run> --official-mem0 <locomo_results.json> --official-hindsight <locomo10.json.gz> --output <new-file.json>` 离线整理固定官方快照。输入必须匹配指定版本哈希，逐题校验原数据的会话索引、问题、分类及参考答案，拒绝重复或缺题。已保存 [1540题官方逐题对照](results/official-locomo1540-20261119.json)：保留两家的原始判定，另算原版答案F1和检索P50/P95；后两项明确标记为本地派生值，不当作厂商公布指标。该入口不调用任何模型或记忆服务，也不将官方答案输入我们的答题流程。

运行中查看真实进度使用 `analysis.py --run-dir <run> --progress`，只读校验已封存的逐题检索、answer/judge记录，打印完成阶段与失败/未知用量，不输出部分准确率、不写源目录。固定AMB的LoCoMo隔离路径会在每个Bank的QA批次完成后写逐题results；answer/judge更早单独保存，所以该目录暂为空不代表未答题。进程是否存活需另外核实；此入口不替代完整结果验证。

## 用统一裁判复判公开答案

`rejudge.py` 将已归档的两家1540题答案交给我们的同一裁判，保留官方原分数，并另报派生对照。它不调用Mem0/Hindsight服务，不访问Bank，不重新答题。完整judge prompt逐字相同时，优先复用基线已有判定，再共享单次新调用，避免同一答案在两家重复判题得到不同结论。所有复用有源调用哈希，新增Token用量单独统计。

```bash
.venv/bin/python benchmarks/memory/rejudge.py prepare \
  --source /path/to/full-baseline \
  --public-results benchmarks/memory/results/official-locomo1540-20261119.json \
  --output /path/to/new-common-judge-job --run-id common_YYYYMMDD
.venv/bin/python /path/to/new-common-judge-job/source/rejudge.py run /path/to/new-common-judge-job
```

prepare只做离线冻结；run必须等源基线完整有效，并使用冻结代码。重复执行复用原判定，已完成的错误答案不重答、不重判择优。该结果只能称“历史公开答案在共同裁判下的派生分数”，不能称友商新的产品实测或最新官网成绩。

数字gold（年份、计数）按原始类型归档，不强制变成字符串。新建Bank运行中断后，可在新配置中将 `reuse_banks` 显式设为源manifest的完整Bank映射，再用 `checkpoint_source` 接续；只允许这组原Bank，必须重新只读verify。保留原模型调用、源配置/版本快照、导入耗时和累计QA时间。若有未收到回包的中断召回，显式设置 `resume_connection_failures=true`；不增加已完成答案的尝试次数，也不重新导入。

错题原文诊断使用 `analysis.py --run-dir <run> --wrong-snapshot --output <new-file.json>`。它仅分析已封存且判错的记录，列出原文参考句及相邻一轮、session时间、原答案和裁判理由、原文/最终上下文中的ID覆盖，并单列操作失败。可用于运行中逐组排查，但输出kind明确不是成绩，不绕过完整基线验证；不访问Bank或模型、不把QA参考原文补进答题上下文。源片段来自原始合成数据，保存在本机诊断档案，Git报告只保留脱敏归纳。


窗口候选已统一到本分支：`packing.algorithm=query-turn-windows-v1`、`chunk_order=query_relevance`。它只用已返回的完整消息及题目选择相邻原文窗口，保留speaker/dia_id/BLIP caption，不读取gold、参考证据或未召回原文；当前v1不保留图像URL或image query。reader总预算仍为8192、事实/原文各4000；API原文候选预算调到65536需另在recall配置声明，不能称API预算不变。

`analysis.py --run-dir <completed-run> --coverage --output <new-json> [--contexts-dir <new-directory>]` 只离线比较原打包和v1窗口的证据ID覆盖，不调用模型，不输出新准确率。已有[81题覆盖诊断](results/conv30-window-coverage-20261119.json)及[三题原文预算诊断](results/conv30-raw64k-probe-20261119.json)均保留原来源哈希。

`probe.py recall` 可加 `--overrides <json>`，仅允许recall/packing两组类型校验后的设置，并在probe目录冻结；调用前后核验服务版本、公开配置及原文文档，不写源Bank或源运行状态。维护脚本更新后，已有运行仍必须执行运行目录内封存的代码，不能直接拿今日runner接续旧manifest。


## 独立答题提示与检索快照实验

默认`reader_profile=amb-default`保持AMB原reader prompt逐字不变。新实验必须同时声明`reader_profile=locomo-grounded-concise-v1`和`protocol=amb-locomo-cat1to4-reader-v2`，追加统一的合成人设来源、简洁答案、speaker归属、caption、时间锚点、事件去重和合理推断规则。原裁判prompt、gold、F1和分母不变。它不再称为“原reader prompt完全相同”的运行，完整提示和用量仍逐调用归档。

在新配置中使用`retrieval_source: {"path": "/path/to/completed-source/manifest.json", "sha256": "<SHA-256>"}`，并设置源运行的完整`reuse_banks`映射，可复用源运行的检索回包进行全范围新实验。与`checkpoint_source`只能二选一：后者接续同方法的已有判定，前者**不继承任何答案或判定**。源必须完整有效；范围、Bank、API recall预算、记忆配置、答题/裁判模型、数据和固定AMB源码均须一致，只允许另声明reader/packing及执行并发/尝试上限。

流程仍是init → 冻结runner verify → run，不执行ingest。脚本核验源全部检索、模型调用、结果、F1、状态和隔离，保存来源文件哈希及快照；可按新packing配置重打包，但不能从未召回的原文补信息。新运行对整个原范围重新答题和判题，已完成的新判定不重答择优。缺失快照直接失败，禁止悄悄回退live recall。之后的同方法故障接续也保留检索来源。

`summary.retrieval_measurement=reused-source-recall`表示检索P50/P95沿用来源的测量，**不是新测速**；`retrieval_source_run_id`标明来源。新Token账目只统计新答题/判题调用；上下文及prompt长度按新打包实计。当前已通过71项离线检查，并只读审计真实1540题源；新reader提示和32K配置仍只是离线准备，没有新成绩。

独立候选打包方法 `query-turn-windows-metadata-v2` 保留返回原文自带的图片搜索 `query`，标注为source metadata，和BLIP caption分开；不抓图、不生成新caption，不读取QA gold。默认complete-JSON及`query-turn-windows-v1`行为不变，不能在原运行中途切换。六题已有回包的离线重打包通过预算与来源核验，原v1序列化结果逐题完全复现；候选尚未产生答题/判题成绩。初始化缓存复测时仍要求完整有效1540题来源，当前未完成的来源已实际拒绝且未创建输出。配置和代码冻结于`.local/metadata-v2-offline-validation-20261119/`，摘要见既有部分诊断JSON。

重启在途HTTP错误恢复：只有`resume_connection_failures=true`且已记录的服务重启证明与源manifest、暂停前待返回record的完整序列化哈希一致，且不存在recall结果/answer/judge调用，才允许补齐。任意HTTPFailure不会一律重试。新检查点归档原proof和资源分段，但不复制为可递归重用的重启授权。真实q90证据已通过只读核验，84项离线测试覆盖有效恢复、缺失证明、外来manifest、错误preimage、已有语义调用和未完成重启。当前评测仍使用自己的冻结代码，收尾配置在`.local/window-restart-recovery-prepared-20261119/`，未启动。

最终完整结果导出会附`resource_epochs`：绑定`performance-epochs.json`的SHA、原始资源标签、1并发/切换在途/2并发三段的题数与检索P50/P95；三段必须严格覆盖全部题目且不重复。总体准确率/F1不删任何题，整体原始时延标注为混合资源条件，阶段时延也不称为同题加速对照。来源缓存复测明确沿用历史时延。普通无资源切换的旧运行字段为null，旧文件不覆盖。导出不会读取env或凭据文件，也不调用API/模型。收尾冻结导出源码位于`.local/window-restart-recovery-prepared-20261119/export-source/`，其SHA见export-audit.json。
