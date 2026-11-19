# 早期原型代码快照

这里保存C融合/预算函数、参数化SQL及PG扩展目录补丁，供阅读核验；是历史证据，不是已经完成的Recall后端。本次没有编译、安装或执行它们。

| 文件 | 作用 |
| --- | --- |
| [contextbase_recall.c](contextbase_recall.c) | 通用RRF Top-K与成本预算选择函数 |
| [Makefile](Makefile)、[install.sql](install.sql) | 原实验的PGXS编译/私有实例注册方式；不能直接用于现有服务 |
| [pg-extension.patch](pg-extension.patch) | 基于PG18.4 `f5cc81719e6`的独立contrib目录补丁，不修改core |
| [baseline-candidate.sql](baseline-candidate.sql) | 受控应用融合路径的候选SQL |
| [pushed-candidate.sql](pushed-candidate.sql) | 受控PG C融合路径的SQL |

原Python实验驱动、测试和当时的复现说明留在本机：

`/Users/zhuqingping/Work/Database/Context/ContextDB-Research/reports/recall-pushdown-20261119/prototype/`

独立PG worktree和冻结运行记录留在：

`/Users/zhuqingping/Work/Database/Context/ContextDB-Research/.local-archive/recall-pushdown-20261119/`

C函数先接收完整数组再融合，并未实现CustomScan、查询内并行或提前停止；预算函数在早期只做差分测试，完整路径仍由Python完成评分/预算。受限适配器不具备完整扩展加载生命周期，不能安装到8892。

下一阶段的设计和未启动状态以[当前设计](../../design.md)、[进展](../../progress.md)、[计划](../../plan.md)为准；不在这份历史快照上另建维护分支。
