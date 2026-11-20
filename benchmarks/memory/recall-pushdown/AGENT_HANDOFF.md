# Agent / 工程师交接说明

更新：2026-11-20。先读 [README](README.md)、[当前进展](progress.md)、[使用手册](RUNBOOK.md)，再开始工作。唯一维护分支为 `ZhuQingping/hindsight` 的 `memory-benchmark`；不要向 `origin` 的上游仓或团队其他仓误推。

## 当前任务状态

当前代码和阶段证据已按用户要求集中归档；**实验原型，待人工和剩余真实 BGE 验收**。当前无授权中的新性能研发、生产切换或后台长测。本轮未实现多路并行。实际收益为排除模型的核心路径平均 53.48→44.75 ms，详见报告的测量边界。

## 两份代码的位置

- PG C 插件：本目录 `native/`，采用匹配目标 PG 的 PGXS 编译；没有 PG core 补丁。
- SQL / PLpgSQL、服务端 Python：仓库根目录 `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_*.{sql,py}`。业务表名和查询留在存储层；不要移动到 API handler 或再维护 SQL 副本。
- 正式启用、关闭为服务端 Memories 扩展配置，不是 LoCoMo 客户端字段。推荐类 `hindsight_api.engine.memories.pg.recall_rank:RankJsonPostgresRecallMemories`，仅允许配置中的单个实验 Bank。

## 本机状态（仅供本机交接）

| 项目 | 位置 / 状态 |
| --- | --- |
| 完整实现工作区 | `/Users/zhuqingping/Work/Database/Context/hindsight/.worktrees/beam1m-recall-perf-20261120` |
| 主工作区 | `/Users/zhuqingping/Work/Database/Context/hindsight`；有其他任务改动，不 reset、不覆盖其暂存区 |
| 首版保护 | `codex/recall-baseline-v1-05d2894c5` 及 `.worktrees/recall-pushdown-v1-05d2894c5` |
| PG 主仓 | `/Users/zhuqingping/Work/Database/PG/postgres`，本轮未改 core，用户 IDE 文件不能处理 |
| 专用实验库 | PG 18.4，55440，database `beam1m`，Bank `beam1m_1_20261120`，schema `ctxdb_ws_beam1m_1_20261120` |
| 专用常规 API | 8898/8899，仍为上一版服务，不能用 8899 直接验收当前 `rank_json` |
| 活动 LoCoMo | PG 5432、API 8891/8892；禁止为本专项重建、切换或重启 |
| 私有实验根目录 | `/Users/zhuqingping/Work/Database/Context/hindsight/benchmarks/memory/.local/beam1m-recall-20261120` |

**本机主工作区的分支暂未移动到新提交，目录资料可同步阅读；执行新版测试请把 `PYTHONPATH` 指向上述完整实现工作区，或使用新 clone。不要在旧代码上仅复制一份 SQL 就启动。**

私有根目录中 `dataset/verification/` 为查询/向量快照，`snapshots/` 为数据库快照，`input/` 为凭据文件，`phase3/` 为完整实验记录。不能提交这些内容。历史 `phase3/handoff` 的 bundle/patch 是发布前交接快照，已由远程分支中的提交代替，**从当前分支接手不要再应用一次**。

## 接手时的检查

1. 在独立工作区取得远程 `memory-benchmark`，记录 HEAD；确认工作区干净，不 reset 主工作区。按照根 AGENTS / CLAUDE 执行 review 和检查。
2. 看 [当前设计](DESIGN-CURRENT.md) 与 `supports()`；顺序兼容只适用 CPython 3.11、64 位 SipHash13、哈希种子 0。BEAM 当前 world/experience 覆盖不代表 observation 等一般请求已覆盖。
3. 在专用库检查 data_directory、Bank、表摘要；只读角色跑验证。C 模块用新版本绝对路径，不能覆盖任何被后端加载的共享库。
4. 不得给原始基线补排序、减候选、换 embedding/reranker、改变预算或放宽比较。JSON 对象键顺序可忽略，数组顺序、值和正文必须一致。
5. 先完成剩余验证，再按 [计划](plan.md) 提议性能工作。结果以平均、P50/P95、逐题退化和完整时延分段一起报告。

证据清单保留测量时的 commit / 未提交状态，是历史快照，不能当成当前 git 状态；当前发布状态以远程 HEAD、提交说明和本入口为准。最终 v2 评分位比较与 v1 性能/BGE 需要分开引用。全仓 lint 既有 F841 与未完成黑盒、并发覆盖必须保留披露。
