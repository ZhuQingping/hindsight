# 当前设计：一次候选调用，保持原 Recall 结果

2026-11-20。以本文件描述当前实现；[首版设计](design.md) 和 [BEAM 设计](beam1m/design.md) 保留其阶段背景。

## 1. 接口和两边边界

客户端继续调用原 Recall HTTP API，不增加 `full_recall=true` 请求字段。ContextBase 服务端通过 Memories 扩展选择存储实现，构造 `FullRecallRequest`，由 `full_recall` 能力判断是否接管。默认存储继续原路径。

| 位置 | 实际工作 |
| --- | --- |
| ContextBase 候选查询之前 | 原租户认证、Bank 配置、query embedding、请求与支持范围检查 |
| PG 一次候选入口 | 查询词筛选、向量/全文/图/时间检索、原单路顺序、C RRF/Top-K、候选及关联原文补全 |
| ContextBase 候选返回之后 | 释放连接；复用原 BGE、最终评分、事实和原文预算、响应封装，不再读取 PG |

一次指**候选业务查询一次往返**，不是整个 HTTP 只有一条 SQL，也不是 PG 内部只执行一条语句。配置或鉴权读取单独计算。存储函数内部有多条 SQL，当前图扩展按事实类型串行执行。图扩展依赖向量种子，不能无条件把四路说成完全独立并行。

## 2. 代码索引与依赖顺序

仓库根目录下的运行时目录：`hindsight-api-slim/hindsight_api/engine/memories/pg/`。

| 文件 | 职责 |
| --- | --- |
| [contextbase_recall.c](native/contextbase_recall.c) | C RRF、按原首次出现顺序稳定处理同分、Top-K；首版已有 |
| [contextbase_legacy_order.c](native/contextbase_legacy_order.c) | 有限解释器环境的旧 Python UUID 集合顺序兼容；首版已有 |
| [contextbase_rank_cd_or.c](native/contextbase_rank_cd_or.c) | 两参数 `ts_rank_cd` 的纯 OR 精确快速路径；其他语法回到原 PG 函数 |
| [recall_equivalent.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql) | 首版四路、时间及顺序等价实现 |
| [recall_beam.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_beam.sql) | BEAM 查询词筛选、多事实类型及时间处理 |
| [recall_arrays.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_arrays.sql) | P3 类型数组实现，保留源游标与顺序 |
| [recall_rank.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank.sql) | 仅增加 C 评分的实验对照 |
| [recall_rank_json.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank_json.sql) | 当前推荐入口：C 评分、直接生成返回 JSON |
| [recall_pushdown.py](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_pushdown.py) | 原 SQL 模板、支持范围、一次参数化调用与原后处理衔接 |
| [recall_beam.py](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_beam.py)、[recall_rank.py](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank.py) | BEAM 参数及当前候选语句选择 |

安装顺序由 [native/install.sql](native/install.sql) 直接引用这些 SQL，保持一份来源；没有修改 PG 主仓核心代码。当前为普通 PG C 模块加 SQL / PLpgSQL 实验原型，没有实现 CustomScan 或通用优化器节点。

## 3. 等价约束

不得改变原四路候选、各路名次、RRF 累加顺序和同分首次出现顺序；不得给原基线增加 UUID 排序。模型输入与顺序、分数、事实预算、原文预算、最终返回也需要比较。JSON 对象键顺序忽略，数组顺序、数值及正文不容忍差异。

OR 快速路径保持原默认权重和 normalization=0；不适用语法直接调用原函数。只缓存表达式内查询结构，不缓存文档或答案。最终 JSON 的 chunk 键保持原 JSONB 顺序；P3 中间时间状态仍为 JSONB。

严格等价限定冻结 Bank、query 向量、参考时间和相同配置。当前保留 CPython 3.11 / 64 位 SipHash13 / `PYTHONHASHSEED=0` 的窄范围顺序兼容。BEAM 当前数据为 world、experience；observation 数据和未支持形状不能宣称覆盖。未覆盖的 tags、过滤、实体/来源事实补全等以 `supports()` 实际守卫为准，查询前拒绝接管。

## 4. 版本与证据

| 阶段 | 保留内容 |
| --- | --- |
| 首版 | 原提交 `05d2894c5`；当前分支整合后的首版提交 `b682cd693`，109 条事实 / 81 题等价 |
| BEAM P3 | `4016fed9b`，完整会话导入冻结、等价与阶段实验 |
| 当前性能版 | 本次归档提交中的源码、[阶段证据清单](beam1m/phase3-evidence/manifest.json) 与 [发布检视](PUBLICATION-REVIEW.md) |

阶段性能与 3 题 BGE 使用 v1；最终 v2 仅修补查询缓存分配异常路径，并重跑 58,040 个评分位比较。不得把 v1 的性能、BGE 记录写成 v2 的整轮新测量。当前仍等待完整 BGE 及人工验收。
