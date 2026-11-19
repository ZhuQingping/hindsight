# Recall下推设计：一次PG候选调用，保持原始结果

更新日期：2026-11-19。本文对应当前`EquivalentPostgresRecallMemories`实现，不再使用早期UUID规范化对照作为等价基线。实现与验收见[实现报告](implementation-report.md)，逐题差分和修复过程见[三组验证](three-way-original-compatibility.md)。

## 1. 目标与已验证范围

**PG一次调用完成四路检索、RRF融合、Top-K和候选补全；ContextBase继续完成原有模型重排、最终评分、预算和响应组装，返回后不再补查PG。** 首先保持原始结果，不在此次改动中调整排序策略。

已验证原PG 18.4、109条world事实Bank和固定81题。在RRF及真实本地BGE两种模式中，修复版各81题的完整业务JSON、融合结果、最终reader正文和Token均与未修改原始版一致；BGE有序模型输入也一致。两道时间题q047/q063均接管。

严格兼容验证限定CPython 3.11.15、64位SipHash13、`PYTHONHASHSEED=0`。未知解释器/哈希配置在查询前退出接管；未验证任意部署、执行计划、Bank规模和请求形状。没有修改PG core、生产服务或LoCoMo客户端协议。

## 2. 实际调用链

```text
LoCoMo或其他客户端：原有 Recall HTTP 请求
                         |
ContextBase：认证/Bank配置、查询向量、时间条件解析
                         |
                         v
MemoriesExtension.full_recall(request)
  关闭：默认PostgresMemories返回None -> 原检索与Python RRF
  开启：选择EquivalentPostgresRecallMemories
                         |
                         | 一次参数化候选SQL
                         v
SELECT recall_equiv.candidates($1::jsonb, $2::name)
  ├─ 原始向量/全文UNION
  ├─ 依赖向量种子的实体、语义和因果图扩展
  ├─ 有时间条件时执行原时间入口与有界关系扩展
  ├─ 保留原单路名次 -> PG C RRF / Top-K
  └─ 一次返回候选正文、各路信号和关联原文
                         |
                         | 返回候选包，释放PG连接
                         v
ContextBase共享finalize_candidates
  原BGE重排或RRF模式 -> 最终评分 -> 原文/事实预算 -> RecallResult
                         |
原HTTP响应 -> 原LoCoMo pack_context；不再补查PG
```

`full_recall`是服务端存储扩展接口，不是新HTTP参数。“开启”表示服务端选择实验store并接管支持的请求；“关闭”表示使用默认store。配置开关不由LoCoMo客户端按题目决定。

**一次调用限于候选阶段。** API外层Bank/配置读取、启动/预热与PG函数内部语句分别计数；整个HTTP请求并非只执行一条SQL。当前函数组织内部SQL连续处理，不代表四路已经在PG内并行。

## 3. ContextBase与PG的职责

| 工作 | 当前执行位置与实现 | 改动性质 |
| --- | --- | --- |
| 认证、Bank/租户解析、query embedding | 原ContextBase引擎；schema来自认证上下文 | 复用 |
| 时间条件解析 | 实验store调用full_recall前解析，回退不重复解析 | ContextBase衔接 |
| 四路检索与关系扩展 | `recall_equiv.candidates`、`temporal_candidates`；复用原SQL构造器、PG/pgvector及现有索引 | SQL/PLpgSQL集成 |
| 融合、去重、Top-K | 已有C `recall_probe.rrf_topk`，按原始单路名次执行 | PG C扩展，非core补丁 |
| 原图集合顺序适配 | C辅助函数兼容固定CPython集合构造/联合顺序 | 实验性兼容代码 |
| 候选正文及关联原文 | PG同次查询返回，携带日期、来源名次、分数及已加载附件标识 | SQL补全和内部候选协议 |
| BGE、最终评分、预算、组装 | 连接释放后调用ContextBase共享后处理 | 提取复用原逻辑，未移植到PG |
| 客户端打包、reader/judge | 原LoCoMo流程 | 未修改；本轮未重新答题/判题 |

C扩展源码随ContextBase同一提交保存在[native目录](native/README.md)，与实际PG开发工作区源码逐文件一致。PG SQL保存在store包中并进入wheel；不需要替换postgres二进制。

## 4. 内部候选契约与连接生命周期

`FullRecallRequest`末尾追加请求级`FullRecallRuntime`，绑定认证后的backend及共享finalize回调，不把模型实例或tokenizer写入PG。原请求位置参数顺序保持不变，默认store仍返回`None`。

一次SQL传入Bank、事实类型、查询向量、全文词项、时间窗口、检索与候选上限、阈值，以及由服务端原SQL构造器生成的查询模板。HTTP调用者不能提交任意SQL模板；租户schema单独绑定并按标识符引用。

返回包经`CandidatePayload`校验，包含：

| 内容 | 用途 |
| --- | --- |
| 有序`MergedCandidate` | 保留ID、RRF分数/名次、各路名次及有效原始分数 |
| 候选正文、上下文、日期、类型、来源、标签、元数据与证据字段 | 复用原模型输入与最终评分 |
| `chunks`查找表 | 模型排序后按原顺序去重、截断原文，无需查库 |
| 已加载标识 | 区分“已知为空”和“尚未读取”，防止响应层补查 |

PG不知道BGE最终选中哪些候选，因此预取候选所需的关联原文并集，不能按最终事实预算提前丢弃。模型推理在`acquire_with_retry`上下文退出后开始，不占用该查询连接或快照。共享后处理对原路径保留原有延迟读取，对完整候选包跳过读库分支。

缺失必要字段、已发现的附件数据或数据库执行错误会暴露为失败，不静默补查或重跑旧路径。当前Bank无附件，未验收带附件单次调用。

## 5. 等价规则：保留单路名次，不另定排序策略

旧下推采用`score DESC, id`，改变了同分名次。RRF按`1 / (60 + rank)`累分，同分候选交换位置也会改变融合结果。此次修复保持原公式、权重、上限和模型参数：

1. 向量/全文复用原完整UNION查询，保留原返回顺序。
2. 图路复用原SQL，兼容原字典集合构造及联合后的顺序，再按原分数稳定排序。
3. 时间路保留种子、批次、邻居首次出现与排序规则；保持原浮点乘法顺序。
4. 原单路名次交给C RRF，融合后的同分规则继承原首次出现顺序。
5. 不给原始基线补排序，不在比较时忽略分数或重排响应。

集合兼容辅助函数仅处理规范UUID字符串、固定哈希环境，不加载Python运行时。它不是新的通用排序策略。今后若定义稳定并列规则，须作为独立策略变更重新评估，不冒充本次无损下推。

## 6. 接管与回退边界

当前实验store限定配置的Bank、原生英文全文、`link_expansion`图检索、RRF或cross-encoder模式，以及当前无标签/创建时间过滤、无实体/来源补全等请求形状。完整条件以[支持检查代码](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_pushdown.py)为准。

默认请求可包含world/experience/observation类型，但本轮Bank实际只有world数据。PG查询会检查是否存在请求涉及的非world事实；发现则报范围错误，不返回近似结果。形状或运行环境可提前判断不支持时，返回`None`并调用原store，明确绕过历史Canonical排序；查询后才发现的数据范围问题不静默回退。

`SECURITY INVOKER`保留调用者权限；表访问由Bank谓词、限定种子和认证schema约束。验证账号目标记忆表仅SELECT，不在请求中执行迁移、初始化或数据写入。

## 7. 代码位置

| 文件 | 作用 |
| --- | --- |
| [base.py](../../../hindsight-api-slim/hindsight_api/engine/memories/base.py) | runtime、候选包/原文类型及接管前时间解析能力标识 |
| [recall_pushdown.py](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_pushdown.py) | 当前Equivalent实验store、支持检查、原SQL构造与单次查询；旧Canonical仅供历史诊断 |
| [recall_equivalent.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql) | 当前PG检索、时间扩展、融合调用、补全与候选包 |
| [contextbase_recall.c](native/contextbase_recall.c) | 通用RRF/Top-K；其中预算函数未接入当前路径 |
| [contextbase_legacy_order.c](native/contextbase_legacy_order.c) | 固定CPython集合顺序的实验兼容辅助函数 |
| [memory_engine.py](../../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) | full_recall衔接、共享后处理及预加载数据复用 |
| [retrieval.py](../../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py) | 已解析时间条件的回退复用 |
| [system_config.py](../../../hindsight-api-slim/hindsight_api/engine/system_config.py) | 已有配置表的只读启动，避免不必要DDL |
| [pyproject.toml](../../../hindsight-api-slim/pyproject.toml) | PG SQL进入wheel |

旧`recall_pushdown.sql`和Canonical store保留以复核历史失败，不作为当前开启路径。当前选择器是`hindsight_api.engine.memories.pg.recall_pushdown:EquivalentPostgresRecallMemories`。

## 8. 验收与收益边界

原始固定提交、修改关闭、修改开启三组对照均不对原始结果补排序。核对各路名次、融合ID/顺序/分数/名次、实际模型输入、完整业务JSON及原客户端reader正文/Token；应用计数与PG日志交叉验证一次调用和零补查。

81题来自109条事实，低于Top-300，不足以验证大规模裁剪收益。本轮未实现查询内并行、动态剪枝、CustomScan、PG模型通信或PG评分/预算。Token节省为0，没有新的准确率成绩，也未证明完整Recall稳定提速。后续性能判断见[最小收益验证](latency-validation-plan.md)。
