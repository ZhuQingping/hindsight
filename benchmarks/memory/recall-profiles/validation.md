# recall_profile 服务端选窗迁移验证

日期：2026-11-20。对应[设计](design.md)、[客户端优化目的与历史效果](../locomo-optimization.md)。

`recall_profile` 在这里表示召回结果的上下文选择策略，不承诺检索提速。第一版只把 LoCoMo 的 BM25 式消息选窗从客户端等价移到 API 服务端；原四路检索、RRF、reranker 和 PG 插件不由这个参数切换。其他会话维护的检索下推代码不在本次修改范围。

## 实际实现

- HTTP 请求新增可选 `recall_profile`：省略或 `default` 保留原路径；`locomo` 启用固定的 `message_windows_v1`；预留 `beam` 返回 422。
- 服务器内部取至多 65536 tokens 的关联原文候选，执行原 BM25 式评分、完整消息解析、前后邻居合并和配额选择。事实配额 4000、原文配额 4000，总 JSON 上下文不超过 8192，tokenizer 为 `o200k_base`。
- 输出 `recall_context.text`；评测客户端原样注入 AMB，不进行第二次排序或打包。原 `results` 保留，内部候选不会作为原始 `chunks` 回包。
- session 日期来自调用方可见源文档的 `retain_params.event_date`。包括有事实但未返回 chunk 的文档；缺日期、无时区、跨 Bank、不可见等情况明确失败，不取当前时间补齐。
- LoCoMo 可选依赖为 `hindsight-api-slim[recall-profiles]`，固定 NLTK 3.10.4、tiktoken 0.12.0；默认路径不导入选择器。
- 未修改原始问题、gold、AMB reader/judge 提示词和评分规则。BEAM 没有实现策略或运行新实验。

## 环境与固定范围

使用独立工作树 `codex/recall-profile-locomo-20261120`，基于 `05d2894c5`。该基线已有之前会话的检索实现，迁移补丁未调整检索 SQL。当前源码基线与原 8892 部署的基础 `dd5521cb9` 及部署补丁不同，因此不能仅凭新旧分数相同宣称整个检索引擎完全复现。另做同一新实例内的客户端/服务端实时配对，直接检查迁移等价性。

### 推送前的 rebase 与复核

上述 1540 份重放和 81 题答题证据保留其实际验收基线 `05d2894c5`。按交付要求，随后仅将 recall_profile 的两笔提交 rebase 到远程 `zhuqingping/memory-benchmark` 的 `0951c3664`；不包含另一项尚未推送的 PG 下推提交。选择器与 HTTP 路由源码未变，MemoryEngine 仅增加文档日期读取方法，沿用远程基线的原检索实现。

rebase 后重新执行功能测试，结果为 113 passed、1 skipped（私有全量重放已在前述验收中单独执行）；Python SDK 相关 4 项测试通过。隔离 8894 实例已重启加载 rebased 源码，真实 PG/HTTP 冒烟确认 default 与 locomo 均为 200，选窗结果精确相同，default 不新增 recall_context 字段，beam 为符合声明格式的 422。该次上下文 SHA256 与迁移验收样本一致。

未在 rebased 基线上重新运行全部 81 题答题或 1540 份重放，不将此前分数标记为本次重新测得；历史验收和交付复核的源码指纹在 evidence.json 中分别保留。

原 8892 服务及模型配置未切换；测试 API 为 `127.0.0.1:8894`，使用本机 PG 的隔离副本 `contextbase_recall_profile_20261120`，关闭 Worker，不重新导入或抽取记忆。复制原 Bank `locomo1540_20261119_012639_conv_30`，核验 19 份 session 文档，复用既有 113 条 world facts。

本次真实答题预先固定 conv-30 全部 81 题：类别 1 多跳 11 题、类别 2 时间 26 题、类别 4 单跳 44 题；类别 3 开放域为 0 题。这是类别 1–4 筛选下的一个会话子集，不能称为四类均覆盖，更不是全量新答题。完整 1540 题只进行了历史上下文重放。

| 环节 | 本轮配置 |
| --- | --- |
| 既有记忆抽取 | 原 gpt-6.1-sol / medium 所建 Bank，本轮不调用 retain |
| Embedding | 原 doubao-embedding-vision，1024 维 |
| Rerank | 原本地 BAAI/bge-reranker-v2-m3，权重 953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e，CPU fp32、batch 8、并发 1 |
| 答题与判题 | 两边均 gpt-6.1-sol / low，通过既有 openai-codex provider；不是历史远程 BEAM 使用的 GLM/Qwen |
| 上游 AMB | 28b644bd4dd653c0207c7507280439390c829155；原 LoComoDataset、RAGMode、GeminiJudge、EvalRunner |
| 主评分 | 上游 judge 的 correct 通过题数 / 全部期望题数；原版 LoCoMo F1 为补充指标 |

## 等价性证据

| 验证层次 | 实际结果 | 能证明的范围 |
| --- | --- | --- |
| 合成选择器边界 | 17 项通过 | Unicode、截断 JSON、图片字段、同分、顺序、配额、输入不变、非法作用域等 |
| 1540 份历史回包重放 | 最终上下文 **1540/1540 字节一致**，全部 Packed 字段 **1540/1540 一致**，0 差异 | 生产服务端选择器对冻结客户端历史输入等价；没有新检索或模型调用 |
| 真实 FastAPI handler 集成 | 15 项通过 | 引擎边界受控；默认旧回包、内部预算、错误、日期/tag、依赖隔离和 OpenAPI 模型 |
| 真实 PG/HTTP 配对 | **81/81 上下文一致，81/81 全部 Packed 字段一致** | 独立数据库副本上的实际检索和日期接入，而非只调用纯函数 |
| 历史客户端 vs 本轮服务端 | **81/81 上下文一致，81/81 correct 标签一致** | 本子集输出复现；不能推论所有生产实例或其他数据 |
| 最终源码重启冒烟 | default 200、locomo 200，选窗精确相同；beam 422，错误符合声明格式 | 最终路由代码接入可用，default 无新 recall_context 字段 |

Packed 对照包括完整 JSON 文本、事实/chunk ID 及顺序、总 token、事实/原文 token、omitted 列表，不只比较 token 数或答案。实时两次 recall 的完整 fact 对象可能因内部 score 或元数据不同而不相等；本报告不宣称整个原始 recall 回包字节相等。所验证的是相同契约下实际交给答题模型的内容及选择记录一致。

## 答题复测结果

| 方案 | 上游通过题数 | 通过率 | 原版 LoCoMo 平均 F1 |
| --- | ---: | ---: | ---: |
| 历史客户端 v1（同一 conv-30 子集） | 79/81 | 97.53% | 26.43% |
| 本轮客户端独立答题/评分 | **79/81** | **97.53%** | 25.23% |
| 本轮服务端 profile 独立答题/评分 | **79/81** | **97.53%** | 26.11% |

| 类别 | 题数 | 本轮客户端通过 | 本轮服务端通过 |
| --- | ---: | ---: | ---: |
| 1 多跳 | 11 | 10 | 10 |
| 2 时间 | 26 | 26 | 26 |
| 4 单跳 | 44 | 43 | 43 |
| 合计 | 81 | 79 | 79 |

逐题 correct 标签 **81/81 相同**；迁移后新增正确题 **0**、新增错题 **0**。两边未通过的都是 `conv-30_q31`、`conv-30_q43`，也与历史客户端一致。上下文完全相同，但新生成回答的措辞和长度不同，F1 存在波动；不能以平均 F1 的微小变化认定服务端选窗质量有变化。

客户端对照使用实时 default recall 的回包，经原客户端 v1 选择器打包并保存；确认 81 份完整后，再独立运行全部 answer/judge。服务器侧通过 profile 请求在真实 API 上生成上下文。两边都有自己的冻结 run、调用记录和完整分母，没有只替换错题或沿用旧答案。

本次只有等价迁移，没有把既有错误修成正确作为目标。q31 的 “five months” 与 gold “six months” 存在日期口径冲突；q43 的上下文中包含 festival 表演证据，回答仍将照片关联到 studio vision；这是既有图文指代/回答理解问题，客户端也未通过，迁移没有引入新变化。详细新旧标签及类别统计见[脱敏证据](evidence.json)。不修改 gold 或裁判规则来消除这些错误。

## 成本、性能与限制

本子集服务器上下文平均 7947.17 个 `o200k_base` tokens，峰值 8007。内部候选扩大不代表最终上下文扩大。迁移减少候选传到客户端的需要，但新增服务端文档日期读取、分词和反复 token 计数；日期当前复用已有逐文档 store 接口，并非一次批量元数据查询。

服务器 QA 记录的 recall 平均耗时 14723.77 ms，受同时进行的配对检索和离线重放等负载影响。客户端 HTTP 耗时不包含本地选窗，服务器耗时包含选窗，测量窗口也不同时，不能据此计算迁移提速比例。原 8892 reranker 的并发历史还经历过 1→2，本轮隔离实例固定 1，因此也不能与全量历史时延直接比较。

模型 usage 为供应方已返回部分之和；缺失 usage 的尝试单独记录，不当作零消耗。初始化模型健康探测、原记忆抽取不计入 answer/judge 汇总。本轮不证明其他会话、开放域类别、BEAM、非 PG 后端、远程 GLM 或并发极限下具有同样分数与耗时。

## 测试与工件

功能测试合计 **113 passed、1 skipped**。跳过的是需要私有 1540 题归档的全量重放测试，它已单独通过（该次 18 passed，包括 17 个合成用例）。常规 CI 没有私有原文时不会伪造这份证据。

在工作树根目录，用已准备的依赖与本机 AMB 路径执行：

```bash
export PYTHONPATH="$PWD/hindsight-api-slim"
export CONTEXTBASE_AMB_CHECKOUT=/path/to/amb-28b644b
python -m pytest -q benchmarks/memory/tests/test_server_recall_profiles.py \
  benchmarks/memory/tests/test_runner.py benchmarks/memory/tests/test_recall_profile_migration.py

RECALL_PROFILE_REPLAY_RUN_DIR=/path/to/locomow8c_20261119_1506 \
  python -m pytest -q -s benchmarks/memory/tests/test_recall_profile_migration.py
```

真实复测使用维护版 runner 的 `init → verify → run`；客户端配置保留默认 profile 和原 v1 packing，服务端配置仅显式增加 `"recall_profile":"locomo"` 并指向隔离实例。两边声明原文候选 65536、固定 packing 参数。各次初始化冻结 runner/support/AMB/input，恢复时使用该 run 内冻结入口，不修改在跑快照。

OpenAPI 已从实际 API 生成，并按仓库脚本同版本生成 Python、TypeScript、Go 客户端；Rust 由 OpenAPI build.rs 生成。Docker daemon 不可用，Python/Go 代码生成用相同 7.10.0 Java generator 运行脚本原步骤。生成过程还补齐基线已有但旧 spec 漏掉的 file-storage System API 类型；未新增或改动该业务端点。

SDK 验证：Python 新契约及 prefer_observations 共 4 项通过；Go 新契约及选定离线现有测试通过（不运行会写 localhost 服务的在线测试）；TypeScript tsup 的 CJS/ESM/DTS 构建通过；Rust `cargo check --locked` 通过。新选择器的 ruff、ty 检查通过。整个旧 http.py 的 ruff 尚有基线原有 F841（无关的 unused config），本轮未扩展修复。

完整原文、凭据及模型记录仅在根工作目录的 `benchmarks/memory/.local/recall-profile-native-20261120/`；生产选择器重放档案在本工作树 `.local/recall-profile-migration-20261120/`。可提交的[脱敏 evidence.json](evidence.json)包含范围、分数、逐题标签与上下文 SHA256，不包含数据库/OAuth/API 密钥。

## 最终检视与回退

检视中已补上：SDK 默认字段省略、响应 serializer 保留有类型 OpenAPI schema、422 错误体匹配声明、有事实但无 chunk 文档的归属、客户端拒绝不匹配候选预算、缺选窗结果不静默降级。这些修复都有对应回归测试。

特性仅在隔离 8894 实例启用测试；尚未替换原 8892 服务。准备正式使用时依照[本地启动文档](../../../hindsight-extensions/contextdb-service/docs/deployment-local.md)构建并启动配套 API/扩展，安装可选 extra，显式发送 profile 即可。关闭策略为省略该字段并恢复原客户端打包；无需改表、改插件或重建 Bank。BEAM 保留 422，不自动套用 LoCoMo 策略。
