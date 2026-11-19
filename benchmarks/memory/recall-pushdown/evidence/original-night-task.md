# Recall 下推夜间原型任务

授权：用户明确要求自主实现算子下推并利用现有 LoCoMo 测试库验证。场景为 performance-optimization；允许代码编辑、只读导出测试 Bank、独立 PG 实例构建及测试、报告更新。不发布、不提交、不推送。

范围：`reports/recall-pushdown-20261119/`；两份同名 Recall 下推分析文档；`.local-archive/recall-pushdown-20261119/` 私有数据与运行输出；独立 PG worktree 的 `contrib/contextbase_recall/`。Hindsight 现有源码、benchmark、8892 配置及原 Bank 不修改。

PG 源码基线：`f5cc81719e6da4cbdb1f797c48b693e91018153a`（18.4）；原工作区已暂存的 PG 工程文件不处理。独立分支 `codex/recall-pushdown-20261119`。Hindsight 与 benchmark 的基线及原有脏文件分别归档。

实验分层：

1. 在独立 PG 实例恢复只读导出的 LoCoMo schema，固定数据和查询向量。
2. 实现通用 C 融合函数与 SQL 对照。先检查候选 ID、顺序、分数及预算结果，再计时。明确区分函数、融合 SQL、CustomScan，不以函数包装冒充查询优化器完成。
3. 通过 `full_recall` 契约提供受限原型入口。未实现的请求形状明确拒绝并回退，不能静默漏字段。
4. 用全部 81 题测执行路径；模型输出质量与执行位置分开。相同 reader 输入只能证明等价性，不能虚报新测准确率；改变输入的质量实验须记录新的 reader/judge 结果。
5. 报告实际已运行与未运行项，给出内核研发边界和公平 A/B 方案。

验证：PGXS 编译；真实 PG 上的空集、重复 ID、平分顺序、Top-K、异常参数与 Python RRF 对照；81 题差分；交错多轮时延；查询计划；文档格式和链接检查。实验脚本独立 Ruff/pytest。若修改产品代码，另须执行仓库 lint 与 code-review；本阶段不修改产品代码。

停止条件：需要修改原始 Bank 或服务；数据范围超出 LoCoMo 专用 schema；不能保持比较变量一致；受限原型未满足完整契约却试图承诺产品可用。出现这些条件改为记录边界，继续不依赖它的实验，不请求夜间交互。

晨间审查：原库哈希/行数不变；无秘密进入报告；实测阶段和计时边界清楚；原型范围、失败项、收益与无收益结论均保留。
