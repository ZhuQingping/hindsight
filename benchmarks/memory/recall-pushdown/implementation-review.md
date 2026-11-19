# Recall下推实现审查记录

**当前状态：原始等价适配已通过限定81题验收。C RRF保留PG；RRF/真实BGE各81/81题完整响应、融合结果及reader正文与未修改原始版一致，BGE输入一致。每题一次候选SQL、零后续补查。固定解释器/哈希环境的实验结论，未切换原服务。** 见[三组对照与修复验证](three-way-original-compatibility.md)。

当前提交范围：PG C扩展、一次候选SQL、ContextBase共用后处理及文档证据，限定旧Bank的81题；未部署或推送。代码在独立工作区实现后同步主工作区；当前有效路径与执行冻结版本的既有方法AST一致，另加已单测的原始fallback覆盖。

## 早期原型审查（历史记录）

- PG JSON日期固定UTC，避免与asyncpg返回UTC的字符串表示差异。
- full_recall返回完整RecallResult；原评分/BGE/预算提取共用，不复制算法，不返回半成品冒充完成。
- 查询连接在BGE前释放；候选原文一次带回，B路径跳过hydration/原文读库分支。
- 完整空附件标识直接复用；部分标识仍走原授权/读取流程，观察记忆来源处理不跳过。
- 新runtime字段追加FullRecallRequest末尾，保持现有位置参数顺序；默认store仍None回退。
- 扩展配置使用标准小写bank_id，实际加载器回归通过；非目标Bank及不支持形状查库前拒绝。
- 所有multi-bank SQL显式限定bank_id，junction经限定种子关联；schema来自认证上下文并经format(%I)引用，SECURITY INVOKER，无advisory lock。
- 运行中错误不静默补查或旧路径重试；取消与缺失必需字段有测试。
- SQL计数用请求ContextVar，隔离后台任务；3项专门测试覆盖无请求归属、父子任务阶段和并发请求。
- 索引试验发现79/81候选一致，因LIMIT等权边选择差异而拒绝采纳，未加入主验证schema。

## 实际检查

| 检查 | 状态 |
| --- | --- |
| 两路径RRF/BGE各81题真实HTTP、PG及输入差分 | RUN/PASS |
| 原冻结pack_context逐字与Token比较 | RUN/PASS，162对相同 |
| 应用计数与PG执行日志 | RUN/PASS，162次下推候选调用对应162次PG入口执行 |
| 定向回归75项、计数隔离3项 | RUN/PASS |
| 变更文件Ruff/格式、新PG模块ty | RUN/PASS |
| wheel包含PG SQL及store | RUN/PASS |
| 全仓lint | RUN/BLOCKED：基线api/http.py F841 |
| 全仓存储边界AST扫描 | RUN/BLOCKED：基线system_config.py BOM；新增代码无跨层SQL/PG模块导入 |
| 共享文件ty | RUN：基线44条、当前43条，诊断所在源码行均存在于基线；新增PG模块独立通过 |
| 生产部署、在线更新、多租户写并发、其他请求、reader/judge | NOT RUN |

结论：限定工作负载内无遗留新增must-fix，允许交付可行性原型。不是生产验收；不把顺序单轮时延差额归因于PG，也不继承历史准确率。详细数据见[实现报告](implementation-report.md)和[证据摘要](evidence/single-call-implementation-20261119.json)。

## 后续原PG验证审查

用户追加授权后，使用原PG、原Bank、不同临时接口，RRF/BGE各81题A/B已通过，模型有序输入和reader正文一致；每题一次候选业务SQL、无补查，原数据和PG启动时间未变。账号非超级用户、目标表仅SELECT，辅助维护关闭，不重启原服务。首轮只读启动遭初始化DDL拦截的失败保留，修正后重新全量运行。

本轮14项启动/目标/存储边界测试通过，Ruff和格式通过；旧BOM随修改模块格式化移除，存储边界AST现已通过。执行冻结源码与当前startup模块仅格式差异，AST已比对一致；其他产品核心文件哈希一致。全仓lint仍受原F841阻塞，无关格式化撤回。功能可行性通过，性能结论仍有限：本轮BGE均值与非模型部分点值均未改善，不作为切换原服务的提速证据。见[原库报告](local-existing-pg-validation.md)。

## 原始基线兼容性补充审查

重要缺口：A/B共用修改后源码，A使用CanonicalPostgresMemories调整各路分数/UUID顺序并前移时间解析。现有81题证明共同规范化基线与下推一致，不能排除共享重构错误，不能保证未修改原版行为完全保持。候选顺序会影响RRF和预算，不能视为展示格式差异。需补做O/U/B独立差分；目前未执行，结论收敛为限定对照的可行性通过，原版兼容性尚未验收。


## 原始等价修复的最终审查

此前“未执行O/U/B”是历史缺口，已补齐。原始与修改关闭RRF/BGE各81题完全一致；旧下推失败保留。修复版在原PG上RRF/BGE各81题完整JSON、融合ID/顺序/分数/名次、reader正文及Token相同，BGE实际有序输入相同。每题一条候选SQL、零后查，PG日志各81次对应。

新增等价store的未支持请求显式调用原store回退，防止继承Canonical诊断排序；已新增回归。执行冻结版本的所有既有类方法AST与交付文件一致，交付另加已单测的原始fallback方法。C适配范围固定CPython 3.11/64位SipHash13/种子0，实际回归3.11.15，1200组真实内置集合差分通过；未知配置不接管。原始SQL行序在其他执行计划下的稳定性仍不作通用承诺。

30项定向测试、新模块Ruff/ty、wheel包含新SQL通过；全仓lint阻塞于已有http.py F841。源Bank七表摘要、PG启动时间不变，临时CREATE权限撤回、测试角色恢复只读，原始工作区干净。新C与PL/pgSQL仍使用调用者权限，SQL模板仅来自服务端构造器，schema引用受认证上下文控制，bank谓词或限定种子保持隔离，无新API直连DB或advisory lock。

结论：限定契约内的功能原型通过；未遗留已识别的新增must-fix。解释器/种子范围、生产生命周期、完整系统故事与跨规模/并发性能不在生产验收范围。没有新准确率或Token收益，不据单轮完整耗时认领PG收益。当前证据见[修复验收](evidence/equivalent-original-validation-20261119.json)。


## 同一提交的最终复核

按用户要求，将PG扩展源码与ContextBase、SQL、设计、实现文档和脱敏证据纳入memory-benchmark分支同一commit；不是向两个独立Git仓库制造相同commit，也未修改PG core。C/Makefile/许可证与PG开发工作区逐字一致，来源及当前SHA见提交源码清单。

提交前重新运行30项定向测试、两份C源码临时目录构建、变更Python文件Ruff/格式和新模块ty，均通过；没有重新跑模型或替换既有81题实测结果。执行版本的既有类方法AST与当前文件一致，唯一新增方法是已单测的原始fallback覆盖。设计、实现及链接报告重新导出，5份HTML共15组视口检查通过。全仓lint已有F841限制保持如实记录，未扩大为全仓通过。

提交范围扫描排除凭据、二进制、真实记忆正文/向量、模型、IDE交换文件及无关目录。当前未发现新增must-fix；固定运行环境与请求范围的实验限制继续保留，未执行生产切换或推送。
