# 交付、代码路径与复现

> 2026-11-20 归档说明：本文件保留当时的阶段记录（含“未提交/未推送”状态）。当前维护、发布与验收状态以[统一入口](../README.md)、当前进展和远程分支 HEAD 为准；代码发布不表示剩余验收通过。

## 1. 先看哪些文件

主报告：[BEAM1M-Recall下推性能验证报告.md](BEAM1M-Recall下推性能验证报告.md)。SQL 证据：[SQL交互证据.md](SQL交互证据.md)。所有计时明细位于本目录 `evidence/`。

开发工作区：`/Users/zhuqingping/Work/Database/Context/hindsight/.worktrees/beam1m-recall-perf-20261120`。本节代码路径均相对此工作区。历史测量基线 `05d2894c5`。分支 `codex/beam1m-recall-perf-20261120` 已 rebase 到 `18be05bde`，首版重放为 `b682cd693`；本轮设计、实现和证据已纳入特性提交，未推送。

| 文件 | 用途 |
| --- | --- |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_pushdown.py` | 将原 guard 和请求序列化抽成可覆盖方法；默认条件与短查询输出不变；候选一次调用，连接在模型前归还 |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_beam.py` | BEAM opt-in 适配，传原有全文选词参数；继承其余请求 guard |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_beam.sql` | 最小兼容版；world/experience、原选词逻辑及时间候选 |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_arrays.sql` | 选定 P3；类型化候选、图分数批量合并、C RRF、完整候选包 |
| `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_optimized.py` | P3 `ArrayPostgresRecallMemories`，以及明确命名的未选中实验类 |
| `hindsight-api-slim/tests/test_recall_beam_candidate.py` | 长查询、其余 guard 和无准备 I/O 的回归测试 |
| `benchmarks/memory/recall-pushdown/beam1m/verify_beam.py` | 冻结输入的逐题 HTTP 核对；支持原始源路径、实际模型输入和诊断测量 |
| `benchmarks/memory/recall-pushdown/beam1m/model_observer.py` | 明确的独立实验控制和哈希审计；不从产品源码自动加载 |

第一版 C 代码复用 `benchmarks/memory/recall-pushdown/native/contextbase_recall.c` 与 `contextbase_legacy_order.c`；本轮没有修改这些 C 文件，也没有修改 PG 主干。实际加载的是原独立版本共享库，没有替换 LoCoMo 已加载的文件。

`recall_projection.sql`、`recall_packed.sql`、`recall_parallel.sql`、`recall_streamed.py/.sql` 是保留的实验对照，正常开启服务只选 P3。`recall_equivalent.sql` 与第一版保护工作区均未修改。

## 2. 环境与保留状态

| 项目 | 地址 / 位置 |
| --- | --- |
| PG | `127.0.0.1:55440`，database `beam1m` |
| Bank / schema | `beam1m_1_20261120` / `ctxdb_ws_beam1m_1_20261120` |
| 常规关闭 / 开启服务 | `http://127.0.0.1:8898` / `http://127.0.0.1:8899` |
| 常规配置 | 私有目录 `runtime-normal-off/api.env`、`runtime-normal-on/api.env` |
| 服务收据 | 私有目录 `results/normal-services.json`、`logs/restore-normal.log` |
| 测量配置归档 | 私有目录 `runtime-benchmark-off/`、`runtime-benchmark-on/` |
| dump | 私有目录 `snapshots/beam1m-complete-frozen.dump` |

私有目录为 `/Users/zhuqingping/Work/Database/Context/hindsight/benchmarks/memory/.local/beam1m-recall-20261120`，Git 忽略，目录受限。凭据不写入本报告。Worker 保持关闭，停止本任务单独的 caffeinate，保留数据库与常规 API。正常 API 使用实际实时 embedding，不含固定问题测试钩子。

原 LoCoMo PG 5432、API 8891/8892 以及其 Bank 没有参与本轮导入、压测、恢复或重启。81 题回归在新 PG 的 `beam_regression109` 中进行，来源为已有归档快照。

## 3. 如何复核，避免覆盖证据

先检查报告中的统计口径，再查看 `evidence/` 中逐题哈希与时延。原始响应、模型输入、候选参数、完整 PG 计划均保留私有目录，不进入公开证据。原始失败实时 embedding 试验、部分导入时的开发测量也保留，但不进入最终统计。

精确执行脚本归档到私有 `runtime/tools/executed/`；`runtime/tools/replay/` 仅替换脚本之间的临时路径，哈希见 [工具清单](evidence/tool-archive-manifest.json)。**不要直接重跑环境启动/恢复脚本覆盖现有端口或结果**；测量驱动也会拒绝覆盖已有标签。

下面命令只读取冻结库，启动临时 loopback 验证 API，输出到新的标签。先按源码路径检查参数；`--mode rrf` 是排除模型的诊断，不是实际 BGE 对照。

```bash
R=/Users/zhuqingping/Work/Database/Context/hindsight
D="$R/benchmarks/memory/.local/beam1m-recall-20261120"
"$R/.venv/bin/python" "$D/runtime/tools/replay/beam_run_verify.py" \
  --database beam1m --path arrays --mode rrf \
  --label manual-arrays-new-run --take 20
```

原始源码验证加 `--path legacy --original`，修改后关闭用 `--path legacy`，兼容下推用 `--path beam`，P3 用 `--path arrays`。标签每次不同。实际本地 BGE 用 `--mode bge`；20 题可能需要约 20 分钟。默认读取冻结向量，不计真实 embedding 时间。

正式真实 BGE 120 次对照使用 `beam_native_trials.py`，配置与控制方式见报告第 2、4 节。该驱动依赖专用测试服务，不能直接对当前移除钩子的常规服务宣称逐字等价，也不要在仍做计时的机器上运行并发测试。

## 4. 已执行检查

- 完整导入、原文一致、七表哈希、dump SHA、选定源码 SHA 及第一版干净工作区验证通过。
- 33 项相关单元测试、2 项独立 PG 时间契约测试通过；完整原路径及下推的真实 HTTP 已做逐题、多轮核对。
- 500 个全文选词组合、2 个额外时间窗口、恢复库 81 题回归通过。
- 改动文件的 Ruff 与目标 ty 通过。ty 从 `hindsight-api-slim` 目录运行并显式指向原 3.11 venv；没有更新共享依赖。
- 已运行要求的 `scripts/hooks/lint.sh`，仅基线已有 `api/http.py` F841 阻塞（历史基线第 5846 行，rebase 后第 5886 行）。无关 formatter 改动已从专用工作区排除。

发布前仍需补齐通用多租户/异常/并发覆盖、SDK 黑盒 CI 和打包部署。本版是受控等价性能原型，不能按一般用途生产功能发布。

## 5. 历史补丁

源码补丁：`benchmarks/memory/.local/beam1m-recall-20261120/results/beam1m-source.patch`。

源码与文档、证据完整补丁：`benchmarks/memory/.local/beam1m-recall-20261120/results/beam1m-source-and-evidence.patch`。

这两份补丁记录 rebase 前的测量版本，不能直接当作整合后的补丁。二者均以 `05d2894c5` 为基线，通过 `git apply --check`，没有应用到保护工作区，也没有写入主工作区 Git index。完整补丁哈希与交付检查保留在私有 `results/final-package-qa.json`。
