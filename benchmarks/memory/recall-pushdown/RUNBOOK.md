# 使用与复测手册

2026-11-20。适用当前实验版，先读 [进展与边界](README.md)。本手册不初始化数据库，不导入数据，不替换原服务。ContextBase 正常 API / Worker / UI 启动方式以[统一启动指南](../../../hindsight-extensions/contextdb-service/docs/deployment-local.md)为准；下面的 verifier 只启动独立 Recall 测试进程。

## 1. 取得同一套代码

```bash
git clone --branch memory-benchmark --single-branch   https://github.com/ZhuQingping/hindsight.git hindsight-pg-recall
cd hindsight-pg-recall
git rev-parse HEAD
```

已有工作区请使用独立 worktree，避免覆盖其他未提交内容。仓库根目录以下记为 `REPO`。需要 CPython 3.11、仓库依赖、目标 PG 的开发头文件/PGXS、原有 pgvector 和既有 ContextBase 表。换机器需要另行准备相同数据库快照、查询/向量快照及本地模型；这些不在 Git 中。

## 2. 编译 PG C 模块

```bash
REPO="$PWD"
PG_CONFIG=/absolute/path/to/target-pg/bin/pg_config
make -C "$REPO/benchmarks/memory/recall-pushdown/native" PG_CONFIG="$PG_CONFIG"
```

会构建 `contextbase_recall`、`contextbase_legacy_order`、`contextbase_rank_cd_or`。本机目标为 PG 18.4；Linux/macOS 必须在目标平台重新编译，不复制本机 dylib 到其他机器。

DBA 将三个共享库复制到**数据库主机可读的全新版本目录**，例如 `/srv/contextbase/recall/BUILD_ID/`，由 DBA 持有、应用角色不可写。`BUILD_ID` 使用真实提交 ID 加构建标识。不要覆盖任何后端已经加载的库；本轮没有 PG core 补丁，也不需要重建或重新初始化原库。

## 3. 在独立实验数据库显式安装

先用 DBA 连接核对 `current_database()`、`SHOW data_directory`，确认是专用实验库；本机专用端口 55440，**不是 LoCoMo 的 5432**。通过 `PGSERVICE` 或受限 `.pgpass` 提供连接，不在命令行写明密码。

```bash
export PGSERVICE=recall-experiment-admin
psql -X -c 'SELECT current_database(); SHOW data_directory;'
psql -X -v ON_ERROR_STOP=1   -v rrf_library=/srv/contextbase/recall/BUILD_ID/contextbase_recall   -v legacy_library=/srv/contextbase/recall/BUILD_ID/contextbase_legacy_order   -v rank_library=/srv/contextbase/recall/BUILD_ID/contextbase_rank_cd_or   -v memory_role=experiment_reader   -f "$REPO/benchmarks/memory/recall-pushdown/native/install.sql"
psql -X -v ON_ERROR_STOP=1   -f "$REPO/benchmarks/memory/recall-pushdown/native/test_rank_cd.sql"
```

共享库路径不带 `.so` / `.dylib` 后缀。安装脚本仅创建/更新本专项函数和 schema，引用 ContextBase 中唯一的五份运行时 SQL，不复制、不建业务表、不建索引。它使用事务、调用者权限，收回 PUBLIC 访问，再授权指定服务角色；同库第二个测试角色需要 DBA 同样显式授权。

这些函数接收**服务端生成的 SQL 模板**，不能直接向不可信 SQL 客户端开放。角色只授予目标租户表的 SELECT、必要 schema USAGE。校验器附着现有实例时要求非 superuser、`default_transaction_read_only=on`，并需要 `pg_read_all_settings` 读取 `data_directory`；数据库权限及读取配置必须由 DBA 预先准备。安装不是生产多租户安全认证的替代。

## 4. 如何开启与关闭

在两个独立测试 API 进程中，数据库、模型、配置相同，仅改变服务端存储扩展。按统一启动指南设置端口和认证；**不要直接覆盖现有 8898/8899 或 LoCoMo 进程**。

开启当前性能版：

```bash
export PYTHONHASHSEED=0
export HINDSIGHT_API_MEMORIES_EXTENSION=hindsight_api.engine.memories.pg.recall_rank:RankJsonPostgresRecallMemories
export HINDSIGHT_API_MEMORIES_BANK_ID=YOUR_EXPERIMENT_BANK
```

关闭下推：在另一个进程启动前 `unset HINDSIGHT_API_MEMORIES_EXTENSION`，使用默认 `PostgresMemories`。不是 HTTP/LoCoMo 客户端传参。比较时还要核对响应、各路顺序、RRF 与模型输入，不凭配置名认定接管成功。仅满足 `supports()` 的请求接管；详见 [设计](DESIGN-CURRENT.md)。模型、评分与预算在两边都照常执行。

## 5. 先验证等价性（公开工具）

`verify_beam.py` 使用固定 query 向量和参考时间，明确附着只读实验库；不是替换常规服务。准备 `queries.json`（`reference_date`、`queries`，每题 `id/query/window`）和 `embeddings-*.json`（`ids/vectors`），格式由脚本 Pydantic 模型校验。没有数据不会自动导入或伪造。

本机可使用现有私有快照，路径如下。其他机器改为自己的目录。`PY` 应为装好仓库依赖的 CPython 3.11。

```bash
REPO=/absolute/path/to/hindsight-pg-recall
PRIVATE=/absolute/path/to/private-experiment
PY=/absolute/path/to/python3.11
export PYTHONPATH="$REPO/hindsight-api-slim"
export PYTHONHASHSEED=0
```

本机已有完整新版代码工作区为 `/Users/zhuqingping/Work/Database/Context/hindsight/.worktrees/beam1m-recall-perf-20261120`，可将 `REPO` 设为该目录；主工作区保留了其他任务的未提交改动，不把其旧 checkout 当成新版执行环境。

`PRIVATE` 在当前机器为 `/Users/zhuqingping/Work/Database/Context/hindsight/benchmarks/memory/.local/beam1m-recall-20261120`。凭据文件应为只读专用账号 DSN、权限 0600；所有输出目录使用新标签，不覆盖旧证据。

```bash
"$PY" "$REPO/benchmarks/memory/recall-pushdown/beam1m/verify_beam.py"   --snapshot-dir "$PRIVATE/dataset/verification"   --pg-dsn-file "$PRIVATE/input/beam1m-reader-dsn"   --existing-pg-data-dir "$PRIVATE/pgdata"   --api-key-file "$PRIVATE/input/verification-api-key"   --schema ctxdb_ws_beam1m_1_20261120 --bank-id beam1m_1_20261120   --path legacy --mode rrf --take 20   --output-dir "$PRIVATE/results/manual-off-UNIQUE"
```

再以相同参数改为 `--path rank_json`、输出 `manual-on-UNIQUE`；P3 对照用 `--path arrays`。检查各目录 `verification.json`、逐题回包和模型输入哈希。对象键顺序忽略，数组、分数、正文必须相同；下推不得出现后续候选/原文补查。

完整 BGE 验证把 `--mode rrf` 改为 `--mode bge --model-path /absolute/path/to/local-bge`，使用相同本地模型和参数。当前阶段只做完 3/20，**需要完整重跑 20 题对照验收**，不能以本文发布代替。不要用实时两次 embedding 做严格等价归因，云端向量本身可能变化。

## 6. 测量数据库相关路径平均/P50/P95

先通过等价检查，再启三个独立 `verify_beam.py` 进程：分别为 `--path legacy`、`--path arrays`、`--path rank_json`，共享上节相同参数，增加 `--latency --serve-only`，输出分别设为 `PRIVATE/results/perf-UNIQUE/off`、`.../p3`、`.../new`。各终端会写 `ready.json`。全组用 `--mode rrf`，GC 默认开启，不同时运行 BGE/导入/其他负载。

另一个终端运行公开外部客户端：

```bash
"$PY" "$REPO/benchmarks/memory/recall-pushdown/beam1m/measure_http.py"   --snapshot-dir "$PRIVATE/dataset/verification"   --api-key-file "$PRIVATE/input/verification-api-key"   --off-ready "$PRIVATE/results/perf-UNIQUE/off/ready.json"   --p3-ready "$PRIVATE/results/perf-UNIQUE/p3/ready.json"   --new-ready "$PRIVATE/results/perf-UNIQUE/new/ready.json"   --rounds 20 --warmups 2 --take 20   --output-dir "$PRIVATE/results/perf-UNIQUE/client"
```

每组 400 次，排除两轮预热，问题/版本次序按种子随机交错。每次响应核对原始版；支持 `--gold-dir` 指向历史原始回包目录强化对照。默认使用本次预热前原始响应，必须如实记录基线来源。工具不保存正文、凭据或问题内容。测试后手工停止自己启动的三个临时 API，不终止现有服务。

`results.json` 记录全部样本及平均/P50/P95、哈希、字节数；另按题聚合识别退化。此公开客户端为归档时新增的可移植工具，功能冒烟与历史 1,200 次测量分别记录；不把新工具冒烟当成新性能成绩。历史驱动和完整原始记录仍在私有 `phase3/` 中。

**此口径排除 embedding 和实际 reranker、未包含完整业务鉴权层，不能标成生产完整 Recall。** 带模型完整时延应独立公平重测，保持模型资源和输入相同。PG 内部 SQL、buffers、计划的诊断也单独运行，避免重日志污染最终时延测量。

## 7. 回退与下一步

停止新的独立测试 API，取消 Memories 扩展选择并启动默认存储，即回到原路径；C/SQL 对象可留在实验库，不影响未选择它们的请求。不要为回退重建数据或删除活动共享库。卸载需先确认无依赖，再由 DBA 操作，本手册不自动 DROP。

人工验收、剩余 BGE、退化题和真实并发等工作见 [下一步计划](plan.md)。每轮固定源码和构建哈希，输出新目录，记录失败及未完成项。
