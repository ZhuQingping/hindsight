# ContextBase Agent Memory 评测优化报告

ContextBase 第一阶段以 AMB fork 作为评测优化的开发和发布仓库，提供四集可复现工具包，在客户端验证补充检索、原文编排和预算调整；第二阶段再把稳定有效、可供实际业务复用的机制移植到 ContextBase 服务端。目标覆盖 LoCoMo 10、LongMemEval-S、BEAM 10M 和 PersonaMem。

Hindsight AMB 已采用按测试集配置抽取任务、召回预算、数据组织和答题提示的方式。针对性配置可以使用，但需要公开配置与成本，并与通用策略分开验证。

日期：2026年11月24日。上游代码基准：AMB `01bd83f3fa5245d6be3986cfab81fdd828f26acd`，以普通 RAG 和 Hindsight 适配器为主；历史成绩需按各自运行版本解释。

# Hindsight AMB 的针对性处理

## Bank 属性和记忆抽取

下表列出普通 RAG 路径中新建 bank、未设置 AMB 环境变量覆盖时，各测试集实际采用的配置。客户端选择并发送这些参数，ContextBase 服务端负责保存和执行。

| 配置项 | LoCoMo 10 | LongMemEval-S | BEAM 10M | PersonaMem |
|---|---|---|---|---|
| Bank 隔离 | 每个 conversation 独立 bank | 每道题独立 bank | 每个 conversation 独立 bank | 同一运行的共享 bank，以 user 标签隔离人物 |
| enable_observations | false | false | false | false |
| retain_extraction_mode | 继承服务端配置 | 继承服务端配置 | 继承服务端配置 | 继承服务端配置 |
| retain_mission | 继承服务端配置 | 继承服务端配置 | 设置 BEAM 专用抽取说明，见下文 | 继承服务端配置 |
| retain 源日期 | session 日期 | haystack 中的 session 日期 | 发言 time_anchor 解析的日期 | 从 session 文本提取的日期 |
| retain 会话说明 | 对话双方姓名、session 与 conversation 标识 | session 标识、日期及助手角色说明 | conversation 标识、源 user_info 及 session 序号 | 角色及 system 人物背景保留在原文中 |

“继承服务端配置”表示 AMB 不覆盖该项，实际生效值应从 bank 配置接口读取。ContextBase 当前代码的默认抽取模式为 concise；部署和 bank 覆盖值以实际运行记录为准。

**BEAM 专用 retain_mission 的内容：** 保留用户的经历、决定、问题、结果和计划，尤其准确保留实际设置、版本、数字、否定与矛盾表述；记录助手提出的技术方案并标明归属；排除助手代码和示例中的演示参数；不重复转述作为上下文提供的用户画像。这是一段自然语言抽取任务说明，用于指导模型选择和表达事实。

**配置入口与生效时机：** AMB 在创建 bank 时传入 enable_observations、抽取模式和 mission；导入文档时逐项传入日期、会话说明或人物标签。可用 AMB_ENABLE_OBSERVATIONS、AMB_RETAIN_EXTRACTION_MODE、AMB_RETAIN_MISSION 显式覆盖前三类配置。修改抽取模式或 mission 不会自动重抽已有记忆，跳过导入复测时应核验原 bank 的实际配置。

源码依据：[Bank 配置和 BEAM 抽取说明](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/memory/hindsight.py#L213)、[导入字段映射](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/memory/hindsight.py#L536)、[LoCoMo 数据组织](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/locomo.py)、[LongMemEval 数据组织](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/longmemeval.py)、[BEAM 数据组织](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/beam.py)、[PersonaMem 数据组织](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/personamem.py)。

## 四集的数据组织和答题处理

| 测试集 | 客户端数据与查询处理 | 答题处理 |
|---|---|---|
| LoCoMo 10 | 按 session 保存对话和日期，按数字顺序处理 session，以最后有效会话日期作为问题参考时间 | 强调直接证据、相对日期转换、矛盾与多次事件；普通 RAG 优先将完整 recall 响应 JSON 放进提示 |
| LongMemEval-S | 每题独立 bank；按 session 导入并传日期；移除 has_answer 标记；为重复文档 ID 加后缀 | 专用提示覆盖计数、知识更新、偏好推荐、比较和日期计算；优先使用完整 recall 响应 JSON |
| BEAM 10M | 展开嵌套对话；按 session 和长度拆文档；保留角色、time_anchor、Turn ID | 统一要求扫描、组合证据、解析间接指代、保留具体值及证据不足时拒答；不按金标题型切换答题提示 |
| PersonaMem | 按 system 消息划分 session；保留角色；检索只用人物姓名和用户问题，答题时再提供选项 | 依据历史选择最合适回复，输出 a、b、c 或 d |

数据、查询和提示实现：[LoCoMo](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/locomo.py)、[LongMemEval](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/longmemeval.py)、[BEAM](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/beam.py)、[PersonaMem](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/dataset/personamem.py)。

## 召回预算

| 测试集 | 记忆结果正文预算 | 关联原文预算 |
|---|---:|---:|
| LoCoMo 10 | 32768 tokens | 16384 tokens |
| LongMemEval-S | 32768 tokens | 16384 tokens |
| BEAM 10M | 12288 tokens | 8192 tokens |
| PersonaMem | 4096 tokens | 10240 tokens |

四集默认使用 `budget=high`，主动开启关联原文、关闭额外实体观察返回。记忆正文是抽取或整合后的记忆，关联原文是其来源 chunk；两者可能重复。上述是返回正文上限，不是每题固定用量，也不是答题模型的输入上限。最终输入还含 JSON、元数据、问题和提示词，需单独记录实际 tokens。

客户端覆盖入口为 `AMB_ENABLE_OBSERVATIONS`、`AMB_RETAIN_EXTRACTION_MODE`、`AMB_RECALL_MAX_TOKENS`、`AMB_RECALL_MAX_CHUNK_TOKENS`。前两项作用于 bank，后两项随每次 recall 请求发送；无需为不同测试集重启服务。[预算源码](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/memory/hindsight.py#L733)

## 客户端编排与评分

适配器按 memory ID 去重事实，同一 chunk 原文只内联一次。LoCoMo 和 LongMemEval 普通 RAG 优先使用原始回包 JSON，因此格式化文本中的去重不能直接视为最终提示已经完成去重。普通 RAG 采用一次召回后答题；仓库另有 agentic-rag 多次检索模式，以及调用服务端原生答题的 agent 模式，应分别报告。[适配器](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/memory/hindsight.py#L69)、[RAG 流程](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/modes/rag.py)、[多次检索模式](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/modes/agentic_rag.py)

评分属于固定协议：LoCoMo 当前适配排除类别5并使用模型裁判；LongMemEval 按题型选择判题提示；BEAM 逐 rubric 要点评分，当前事件排序也走 rubric；PersonaMem 对选项做确定性匹配。尤其 BEAM 当前评分与作者原版的事件排序指标有差异，不能混用分数。[评分入口](https://github.com/vectorize-io/agent-memory-benchmark/blob/01bd83f3fa5245d6be3986cfab81fdd828f26acd/src/memory_bench/runner.py)

# ContextBase 的实施方案

## 方案依据

| 已有实验 | 观察结果 | 对方案的启发 |
|---|---|---|
| LoCoMo 原文候选与窗口编排 | 同一批1540题，1419→1442；36题改善、13题回退 | 原文证据可见性值得优化，必须同时检查窗口丢失的证据 |
| LongMemEval-S 原文补读与问答编排 | 固定 Reader high，原生检索462/500（92.4%）→原文组织v5为473/500（94.6%）→v7最高476/500（95.2%）；v7四轮均值94.55% | 补足原话、保持问答关系、调整事实与原文配额值得优先验证；重复运行确认波动 |
| BEAM 10M 补充检索 | 同 Reader 对照，62.99→66.05；同时增加检索次数和阅读空间 | 补充查询值得验证，需要拆分预算与查询的贡献 |
| PersonaMem 事实重排 | 同 bank 配对512→509/589，无显著增益 | 单纯重排不能预设有效，应验证是否补足关键证据 |

**LongMemEval-S 的具体方法与条件：** 客户端在 recall 后通过只读 SQL 补读本题 bank 的源文档，优先保留用户原话；用 BM25 选择相关助手问答，并为“是的”“两次”等短答保留必要前文。v7在48K最终材料上限内增加原话配额、移除抽取摘要正文；平均材料由v5的40657降至34847 tokens。其意义是组织更完整的证据，而非单纯扩大窗口。复测工具包应通过正式、带鉴权的 API 获取所需原文，补足相应服务接口。

该实验复用既有记忆库和冻结召回，原文导入有1段占位替换，答题视图另有涉及27题的安全筛选；95.2%是单轮最高值，四轮结果为476、470、475、470/500。因此，方法可供优化设计参考，成绩按这些处理条件解释，不作为完全未修改原始输入的严格复现或同条件领先结论。

这些是各自配置下的实验观察，尚不足以证明同一策略可稳定提升四集。[LoCoMo 记录](https://github.com/ZhuQingping/hindsight/blob/memory-benchmark/benchmarks/memory/locomo-optimization.md)、[LongMemEval-S 记录](https://github.com/RSIXDB/hindsight/issues/115)、[BEAM 记录](https://github.com/RSIXDB/hindsight/issues/119)、[PersonaMem 记录](https://github.com/RSIXDB/hindsight/issues/118)

## 第一阶段 基于 AMB fork 发布可复现评测工具包

**目标：交付可一键复测四个 benchmark 的 AMB fork，提供基线与增强配置、完整运行记录和对比报告，确认各项优化的准确率收益与成本。**

交付名称建议为 **ContextBase Agent Memory 评测方案与复测工具包 基于 AMB**。以 AMB fork 为基础保留数据加载、答题和评分实现，补充 ContextBase 适配器、检索与上下文编排、四集配置和实验报告。同一个仓库提供上游基线与增强方案的一键复测入口。

### 仓库分工和维护方式

| 仓库 | 职责 |
|---|---|
| ContextBase 的 AMB fork | 第一阶段优化与复测的主要维护入口：适配器、补充检索、BM25编排、上下文预算、四集配置、执行与报告 |
| ContextBase 服务仓库 | 记忆服务本身，以及第二阶段验证成熟的通用增强能力 |

采用“小范围 fork”，控制的是对上游代码的修改范围：保留 AMB 默认行为；优化通过独立模块和显式配置启用；自定义 Reader 提示、模型或运行模式单独记录。定期同步上游，每次评测固定上游基准、fork 提交和配置；适合上游的改动再提交回 AMB。

现有 ContextBase 仓库中的评测脚本逐步归并到 fork，历史结果和运行快照保留，并记录新旧入口对应关系，避免长期维护两套执行入口。AMB 负责评测，ContextBase 负责提供被评测的记忆服务。

### 两人协作和执行步骤

第一阶段按测试集分工，第二阶段按通用模块分工。以下用成员A和成员B表示两位负责人；各自负责的工作由对方评审。

| 步骤 | 成员A | 成员B | 完成条件 |
|---|---|---|---|
| 1 建立 fork 和公共骨架 | 建立 AMB fork，固定上游版本；建立共用入口、配置格式、上下文输入输出和运行记录格式 | 确认 LongMemEval-S、BEAM 所需字段及接口；参与一次接口约定 | 一份接口说明；共用入口可跑通小样本；两人从同一提交创建工作分支 |
| 2 并行完成两组测试集 | 负责 LoCoMo 10、PersonaMem 的基线、优化、配置、测试、复测脚本和报告 | 负责 LongMemEval-S、BEAM 10M 的基线、优化、配置、测试、复测脚本和报告 | 四集均提供基线与增强运行方式，保存实际 prompt、结果和成本 |
| 3 交叉复测并发布 | 用成员B的说明复测其两集小样本；负责合并、四集完整验收和版本发布 | 用成员A的说明复测其两集小样本；协助排查复现差异，完成自己两集的完整运行 | 同一 fork 提交可运行四集；两人分别提交自己负责测试集的完整证据；发布统一工具包 |

成员A维护公共入口、ContextBase provider、配置结构和公共记录格式。成员B维护独立的补充查询与多次检索模块；成员A维护独立的原文选窗与证据组装模块。各自测试集特有的策略、配置、测试和报告放在各自目录，通过共同接口调用模块。

公共入口和 provider 的修改由成员A合并，成员B通过小PR提交需求；两人均不在各自分支复制一套 runner。模块暂时无法统一时可保留显式实验实现，完成对照后再合并，避免为了统一算法阻塞复测。

共用配置至少区分召回事实预算、原文候选预算、最终阅读预算和额外模型调用上限。第一阶段先冻结统一策略验证四集，再发布必要的分测试集配置。

### 复测交付

| 工作 | 交付内容 |
|---|---|
| 冻结基线 | 数据与 AMB 版本、服务端版本、bank 配置、抽取 mission、Reader 与 Judge 参数、提示和预算 |
| 统一执行 | 导入、完成核验、召回、答题、判分、断点续跑、结果导出；复用已有 bank 时核验配置 |
| 客户端优化 | BM25式原文选窗、问答邻域补全、去重、阅读预算分配、查询改写与补充检索 |
| 实验对照 | 原生基线、仅改预算、仅改编排、仅补充检索、组合方案；先固定 Reader 与评分，提示优化另设对照 |
| 可复核产物 | 配置快照、逐题查询与回包、最终 prompt、答案与判分、token 与时延、改善与回退题 |

提供“基线／增强”一键配置入口。先冻结统一策略在四集验证，再比较分测试集参数。抽取模式或 mission 的对照需使用新的记忆版本；检索和编排试验尽量复用相同 bank。

验收同时看准确率或原评分、重复运行波动、逐题配对变化、费用和时延。多次补充检索与 Reader 多次作答分别记录，不按题拼接最优答案。

## 第二阶段 将有效的通用机制移植到服务端

| 机制 | 建议位置 | 原因 |
|---|---|---|
| Reader 模型、提示、最终阅读窗口、评分与报告 | AMB fork 客户端 | 与答题模型和评测协议直接相关 |
| 召回预算与抽取配置 | AMB fork 选择，ContextBase 服务端执行 | 现有接口可以表达，先完善复测配置 |
| 查询改写、补充检索、原文邻域展开、去重与证据组装 | 先在 AMB fork 验证，再按跨集收益及业务复用需求移入服务端 | 减少调用方重复实现、重复请求和原文传输 |
| 独立原文搜索 | 按需新增 ContextBase 服务端能力 | 找回未被事实检索覆盖的原文，需要索引和访问控制支持 |

### 第二阶段职责和接口边界

第二阶段按“检索编排／证据组装”拆分，两人均围绕 recall 增强工作。复用冻结 bank，先迁移第一阶段验证有效且业务可复用的机制。retain 抽取、mission 调整与独立原文索引另立任务，不混入本阶段的配对对照。

| 负责人 | 职责 | 模块交付 | 边界 |
|---|---|---|---|
| 成员B 检索编排 | 原问题召回、查询改写、补充检索、授权范围内的原文与邻域读取；控制查询次数、候选预算、超时和回退 | 候选证据批次、来源与查询关系、费用和耗时记录；REST、配置、核心入口、OpenAPI与SDK集成 | 保留来源和不同事实，不生成最终答题上下文，不改写原文，不调用Reader判答案 |
| 成员A 证据组装 | 对候选做词法与语义相关性选择、完整问答选窗、重叠窗口合并、内容去重和最终预算分配 | 最终证据上下文、引用位置、选中与省略记录、token统计；AMB fork 调用适配与四集复测调度 | 只处理B提供的证据，不直接查询数据库、发起额外检索或修改bank；本阶段不新增LLM组装调用 |

#### 模块交接接口

流程固定为：问题与范围 → B检索编排 → 候选证据批次 → A证据组装 → B统一封装REST响应。下列对象是接口设计约定，具体字段名在编码前冻结。

| 交接 | 必备内容 | 约定 |
|---|---|---|
| 调用方 → B | 原问题、bank与授权过滤条件、问题参考时间、增强开关；检索次数、候选预算、总超时和费用上限 | 所有补充查询、原文及邻域读取继承相同授权和可见历史范围；启用失败须返回明确状态 |
| B → A | 原问题、不可变候选批次；memory/document/chunk标识、原文和位置、已知角色与日期、命中查询和排名来源；截断、失败及检索成本记录 | B按约定窗口预取所需邻域，A不自行补查；未知角色或日期标为缺失；同一证据多路命中保留来源，不把同chunk的不同事实合并丢失 |
| 组装配置 → A | 最终上下文token上限、tokenizer及版本、选窗和去重参数 | 候选预算与最终阅读预算独立；输出预算包含证据标签、日期及来源标识，Reader提示和问题的剩余空间由客户端预留 |
| A → B | 最终context、引用的来源标识及原文位置、选中和省略原因、token数量、组装版本与状态 | 可追溯到候选原文；只做选择、排序、拼接，不生成事实；超长条目按完整消息或段落边界处理并记录，缺失必要邻域时明确标记 |
| B → 调用方 | A的组装结果、实际生效模式、端到端耗时、额外模型用量、部分失败及回退原因 | 回退原生召回必须标记，不能将其报告为增强成功 |

成员A提出组装所需字段和邻域规则，成员B统一维护接口定义与公共集成文件；双方评审接口变更后再实现。B的检索与读取在调用A前完成，A不得通过隐式回调增加检索，保持模块边界和成本可审计。

#### 验收标准和集成顺序

| 验收对象 | 必须满足的标准 | 负责人 |
|---|---|---|
| B 检索编排 | 原问题检索保留；补充查询遵守次数、候选、超时及费用约束；注入失败时按固定策略终止或回退；所有查询和原文读取保持bank、标签和历史范围隔离；候选来源与用量可复核 | B提交测试和trace，A评审 |
| A 证据组装 | 固定候选和配置得到可重复结果；输出不超token上限；保留必要问答关系和出处；同chunk不同事实不因去重丢失；省略、裁剪可追溯；执行过程中不访问网络或数据库 | A提交固定样例和测试，B评审 |
| 接口与兼容 | 默认关闭时原生路径和响应行为保持兼容；未知参数或不支持的增强版本明确报错；实际生效模式可核验；公共schema、REST和SDK一致 | B负责集成，A核对客户端 |
| 客户端到服务端迁移 | 固定bank、问题、模型、提示和预算，对比第一阶段客户端增强与服务端增强；固定改写结果回放以隔离LLM波动，核对候选、来源与最终context；有差异时归因后重做质量对照 | A执行对照，B定位服务差异 |
| 四集质量与成本 | 冻结统一策略后完整复测四集，保留失败及全量分母；报告原指标、逐题回退、重复运行波动、token与P50/P95时延。运行前约定可接受的质量回退范围和成本上限，未达标的策略保持实验状态 | A、B沿用第一阶段的测试集责任，互相复核 |

先共同冻结接口和固定候选样例，再并行实现两个模块；A用样例开发组装逻辑，无需等待B的真实检索。模块验收通过后由B串联服务入口，A切换AMB适配器进行回放核对、小样本端到端验证和四集完整复测。公共入口、API、配置和生成代码仅由B统一合并，两人不同时修改同一核心文件。

增强模式默认关闭，按请求显式启用；控制补充查询次数、候选量、原文范围、token、超时及额外模型费用。返回实际生效模式和回退记录，避免参数被忽略却被误报为开启。服务端按问题和授权范围处理证据，客户端记录测试集身份。

能力迁移到服务端后，AMB fork 保留调用适配和实验配置，统一调用服务端实现。迁移前后先核对证据和预算，再复测质量与成本。四集收益不一致时，明确发布适用范围或分测试集配置。

### 减少冲突的协作规则

- 同一个 fork、两个工作分支；LoCoMo和PersonaMem一组，LongMemEval和BEAM一组，分别维护配置、测试和结果目录。

- 公共文件只有一个合并负责人：第一阶段客户端公共文件由成员A负责，第二阶段服务端公共文件由成员B负责。公共接口变更先更新约定，再提交小PR，由对方评审。

- 每次运行冻结提交、配置和 bank 版本，运行中不替换代码。两人使用各自的 bank、run目录和结果文件；共享服务不在评测中途修改全局配置。

- 共享 embedding、reranker 和模型配额时，统一分配并发与运行时段。开发可并行，性能对照使用受控负载，避免把资源竞争误认为算法退化。

- 先合并公共骨架，再并行完成模块与两组测试集；交叉复测小样本后，由各负责人执行自己两集的完整验收，集成负责人汇总发布。

## 复测和发布要求

- 检索、改写器和 Reader 只接收正常任务输入及允许访问的记忆；gold、rubric、参考证据标签和历史判分用于独立评估。

- 遵守每题的用户、bank、时间和历史可见范围，PersonaMem 尤其要核对未来消息隔离。

- 保留题目、选项、参考答案、评分实现和完整分母；技术失败及原始数据处理例外单独记录。

- 自定义提示、额外模型调用、检索次数和更大预算均公开。满足指定运行模式与榜单要求后再作同口径比较，其他结果标为自定义实验配置。

- 在 AMB fork 发布上游默认基线、ContextBase 统一增强配置及必要的分测试集配置，分别报告结果。先完成客户端可复现优化，再依据跨集证据和业务需求决定服务端能力范围。
