# 单次 PG 候选下推：实现任务

授权：用户于本会话明确要求先实现一版给领导验证可行性，并允许索引/执行计划调优。此前暂不实现的限制已被本次启动指令替代。

场景：feature-development + performance-optimization。Code-edit permission: GRANTED。当前任务自主推进，不发布、不推送、不修改现有服务或源 Bank。

范围：PG 一次四路检索/RRF/完整候选包，ContextBase 复用 BGE/评分/预算，不再补查；现有旧 Bank 81 题，包含时间题。查询内并行、剪枝、通用模型平台不在首版。索引只在实验克隆中按计划证据试验。

允许文件：hindsight_api/engine/memories/{base.py,pg/recall_pushdown.py,pg/recall_pushdown.sql}，memory_engine.py，search/retrieval.py，相关定向测试；benchmarks/memory/recall-pushdown 的复现代码、报告和脱敏证据。可按依赖新增内部类型/测试模块，保持 HTTP 协议与客户端不变。

禁止：现有8892/其他评测实例、源Bank、运行中的模型配置、历史 evidence 快照、无关代码与凭据。隔离 PG 快照允许启动、函数/索引实验。原始数据、模型分数、向量与完整 prompt 放私有目录。

实现与验证在独立工作区 codex/recall-pushdown-single-call-20261119 进行。默认 PG / 其他 store 的回退不受影响。先单题贯通与不支持形状检查，再 81 题差分与真实模型/HTTP；结果不等价则如实修复/标注，不用旧准确率代替。

验证：定向pytest、真实PG函数/SQL差分、真实本地BGE、HTTP路径与调用数审计、代码Ruff/type检查、仓库lint、code-review。性能报告完整Recall平均/P50/P95，固定输入与资源；一次调用不等于提速。

工作流参考：mysql_ai_workflow 的通用 intake/feature/performance/verification/review；无适用 PG 专属 profile，不套用 MySQL 内核规则。无独立Agent授权，本任务串行完成。

## 后续原库验证授权

用户随后要求复用本机数据库、不要重新初始化，并使用不同接口验证。允许在已有PG新增独立下推函数及只读测试账号，A/B临时端口8895/8896连接原81题Bank。禁止重启既有PG/API、迁移原表、重新导入或写入原Bank。只读启动所需的system_config存在性检查及相关测试纳入本轮范围；结果单列于[原库验证](local-existing-pg-validation.md)。


## 原始等价适配阶段

用户要求先等价、后优化分数，明确要求RRF继续保留PG。本阶段未重新向用户申请移回RRF；复用原始SQL构造器、保留单路名次，增加窄范围集合顺序适配。旧失败记录保留，原始源码基线不额外排序。当前严格契约仅覆盖CPython 3.11.15、哈希种子0及固定81题。临时扩展namespace和版本化动态库加入原PG，无服务重启、数据重导入或源表写入。未支持请求走原store，查询中错误不静默重试。
