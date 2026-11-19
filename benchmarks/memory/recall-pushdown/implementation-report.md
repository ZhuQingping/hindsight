# Recall下推实现报告：PG与ContextBase等价适配

更新日期：2026-11-19。**当前实现已通过固定81题验证：PG一次候选调用完成四路检索、C RRF/Top-K和补全；ContextBase复用原BGE、评分和预算。RRF与真实本地BGE两种模式，各81/81题完整响应与未修改原始版一致。** 本文对应当前代码，不再将旧规范化A/B作为原始等价证据。

## 1. 当前交付

```text
原Recall HTTP请求
        |
ContextBase：认证、配置、embedding、时间条件
        |
        | 一次 SELECT recall_equiv.candidates($1::jsonb, $2::name)
        v
PG：原始四路检索顺序 -> C RRF / Top-K -> 正文与关联原文
        |
        | 完整候选包，释放查询连接
        v
ContextBase：原BGE / 最终评分 / 原文与事实预算 -> RecallResult
        |
原客户端pack_context；候选查询后不再补查PG
```

`full_recall`是ContextBase存储扩展接口。服务端选择`EquivalentPostgresRecallMemories`时接管支持的请求；默认store返回`None`，继续原路径。客户端HTTP协议和LoCoMo打包逻辑未改。

“一次PG调用”指候选业务阶段，API外层Bank/配置读取单列；PG函数内部仍执行多条SQL。本次不是PG内四路并行，也未新增融合CustomScan。

## 2. 两侧改动和提交范围

| 一侧 | 当前实现 | 主要代码 |
| --- | --- | --- |
| PG C扩展 | 哈希去重累分、有界堆RRF/Top-K；固定CPython图集合顺序兼容 | [C RRF](native/contextbase_recall.c)、[顺序适配](native/contextbase_legacy_order.c)、[PGXS与许可证](native/README.md) |
| PG SQL/PLpgSQL | 原查询形状、图/时间扩展、原始名次、C RRF调用、候选及关联原文一次补全 | [recall_equivalent.sql](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql) |
| ContextBase store | 接管范围检查、复用原SQL构造器、一次参数化查询、解码、释放连接后共享处理 | [recall_pushdown.py](../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_pushdown.py) |
| ContextBase引擎 | 追加runtime与候选包类型，提取共用BGE/评分/预算路径；预取模式不再hydrate或读原文 | [base.py](../../../hindsight-api-slim/hindsight_api/engine/memories/base.py)、[memory_engine.py](../../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) |
| 时间、启动和分发 | 已解析时间条件不重复解析；已有配置表允许只读启动；SQL随wheel发布 | [retrieval.py](../../../hindsight-api-slim/hindsight_api/engine/search/retrieval.py)、[system_config.py](../../../hindsight-api-slim/hindsight_api/engine/system_config.py)、[pyproject.toml](../../../hindsight-api-slim/pyproject.toml) |

本次没有PG core改动。PG与ContextBase是两个独立Git仓库；为在一个commit中保存完整改动，已将实际PG开发工作区的C源码、Makefile和CPython许可证逐文件一致地纳入本仓库`native/`，与ContextBase、SQL、测试和文档一并版本化。独立PG工作区仍保留相同源码，不将其伪称为另一个已提交的PG commit。

源码清单及哈希见[提交源码清单](evidence/commit-source-manifest-20261119.json)。不提交动态库、模型、凭据、查询向量或真实记忆回包。

## 3. 原始版、关闭与开启的对照结果

原始基线为改动前提交`0951c3664b3083a99268040c8c84113073a057b3`，不是8892历史部署。原始工作区产品源码未改，未给基线追加UUID排序。三组使用同一原PG、同一Bank、同一81题、固定真实查询向量、时间和预算。

| 核验项，每种模式81题 | 原始版 ↔ 新版关闭 | 原始版 ↔ 修复版开启 |
| --- | ---: | ---: |
| 完整业务JSON响应 | 81/81相同 | 81/81相同 |
| 融合候选ID、顺序与RRF分数 | 81/81相同 | 81/81相同 |
| 修复版融合名次与各路名次 | 基线回归；四路记录相同 | 81/81相同 |
| 实际BGE有序输入 | 81/81相同 | 81/81相同 |
| 原客户端reader正文和Token | 81/81相同 | 81/81相同 |

修复版RRF/BGE各81次候选SQL均与PG日志81次入口执行对应，后续补查均为0；两道时间题q047/q063均接管。RRF两侧Token总数均为629,045；BGE两侧均为624,297。Token节省均为0。

BGE使用实际本地`bge-reranker-v2-m3`，权重revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`、CPU FP32、batch 8、模型并发1；没有回放模型分数。核验融合有效字段、模型输入、完整业务JSON和最终reader正文；内部调试payload包含预加载标识差异，不宣称内部对象字节完全相同。

证据：[原始三组摘要](evidence/threeway-original-compatibility-20261119.json)、[修复后摘要](evidence/equivalent-original-validation-20261119.json)、[修复后逐题检查](evidence/equivalent-question-validation-20261119.json)。

## 4. 为什么旧版失败，新版如何修复

旧下推添加`score DESC, id`，同分候选名次改变；RRF按名次累分，因而原始版与旧下推在RRF模式下81题响应均不同。原始与修改关闭仍81题一致，问题出在下推输入顺序。

将原始各路名次直接送入PG C RRF，81题融合结果完全相同，已排除C公式算错。修复复用原向量/全文完整UNION、原图SQL，兼容固定CPython图集合顺序，并保持时间扩展的首次出现、稳定排序和浮点计算次序。RRF继续留在PG，没有移回ContextBase，也没有调分数或权重。

旧失败记录、旧规范化对照和修复记录分别保留。完整根因见[三组对照与修复验证](three-way-original-compatibility.md)，历史原库规范化A/B见[历史报告](local-existing-pg-validation.md)。

## 5. 验证环境和保护措施

复用本机PG 18.4、端口5432、数据库`contextbase_gpt61_20261107`及原Bank `locomo_conv30_20261118_200523`。数据包含109条world事实、2212条关系、373条事实实体关联、115个实体、19份文档和36个chunks。

原Bank七张表逐行摘要未变，PG启动时间未变；没有initdb、迁移、重导入或替换postgres二进制。原8892/8891服务未重启、未切换。独立临时API/模型进程退出，辅助快照PG已停止，原PG保留实验namespace和版本化扩展库。

候选查询使用非超级用户、目标表仅SELECT。原始引擎启动检查已存在配置表时的临时CREATE权限，在启动后撤回并恢复只读；记忆请求期间连接只读。新引擎通过已有表检查避免重复DDL。详细记录在验收摘要中。

## 6. 代码、测试与审查

| 检查 | 状态与范围 |
| --- | --- |
| RRF和真实BGE各81题、模型输入、reader差分 | 通过，使用未修改原始基线，无输出归一化 |
| 应用计数与PG日志 | 通过，各81次候选入口、零后续补查 |
| 目标数据与原PG完整性 | 通过，七表摘要及启动时间不变 |
| 接管边界、原始fallback、连接释放、取消、缺失字段、启动与计数隔离 | 30项通过 |
| C集合兼容独立随机差分 | 600组构造＋600组联合通过，真实CPython内置集合对照 |
| 新PG模块Ruff、类型检查与wheel内容 | 通过；wheel包含当前SQL及store |
| 全仓lint | 已执行，原有`api/http.py`的F841阻塞；无关自动格式化已撤回 |
| HTML布局、粗体和本地链接 | 重新导出后验证，见[展示检查](evidence/commit-document-validation-20261119.json) |

产品源码与执行冻结版本的原有类方法AST一致；交付另增加经过单测的原始fallback覆盖，防止不支持的请求继承旧Canonical排序。全部核心计算复用原引擎，不维护第二套BGE/评分/预算算法。验收和审查记录见[实现审查](implementation-review.md)。

## 7. 性能、质量与当前限制

| 顺序正确性运行的HTTP观测值 | 原始版 | 修复下推版 |
| --- | ---: | ---: |
| RRF平均 / P50 / P95，ms | 22.01 / 19.70 / 40.44 | 17.07 / 15.69 / 23.11 |
| BGE平均 / P50 / P95，s | 7.276 / 7.085 / 8.901 | 6.913 / 6.622 / 8.740 |
| BGE非模型部分平均，ms | 28.99 | 35.80 |

这些是顺序正确性运行，冻结查询向量不含在线embedding时间，不是重复交错的性能A/B。模型运行时有波动，非模型部分本轮反而增加，因此不能将完整耗时下降归因于PG。尚未证明完整Recall稳定提速。

本轮没有重新答题或运行judge，不继承历史76/81成绩。等价上下文未省Token，也不能推导准确率提高。109条事实低于Top-300，尚不足以验证大规模裁剪、传输或索引访问收益。

严格兼容仅验收CPython 3.11.15、64位SipHash13、哈希种子0及当前81题形状。当前未覆盖生产进程的随机哈希、通用多类型数据、附件、实体/来源补全、其他过滤、大Bank或并发写入；PG调用模型、PG评分/预算、查询内并行、动态剪枝及CustomScan均未实现。

## 8. 交付后的边界

本次将PG扩展、ContextBase实现、测试、设计、实现报告和脱敏证据合并为一个可审查commit，不推送或切换生产。用户现有数据与服务保持原状。

后续如继续，先扩展真实部署运行环境与请求覆盖，再按[性能验证计划](latency-validation-plan.md)做交错、重复的完整Recall A/B。执行位置优化与排序/证据策略调整分别验收，不以减少调用次数代替性能收益。
