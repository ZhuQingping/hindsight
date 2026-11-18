# ContextBase Agent Memory 打榜

本目录统一维护打榜脚本、配置、测试、执行计划和友商报告。工作分支为 `memory-benchmark`，基于个人远端 `zhuqingping/contextbase_v1` 的 `4cdec7b54a2c818bd17e3addf36f9de9bd95372a` 创建。

| 文件 | 用途 |
| --- | --- |
| [plan.md](plan.md) | LoCoMo 通俗流程、模型和评分口径、公平对比、待办、历史结果及错题分析 |
| [report.md](report.md) | 友商 benchmark、模型、分数、Token、时延与原始来源 |
| [runner.py](runner.py) | 唯一执行入口：init、preview、ingest、verify、run、report |
| [support.py](support.py) | 配置类型、完整条目打包、HTTP 导入核验、原始 LoCoMo F1；没有独立执行入口 |
| [config.example.json](config.example.json) | 当前本机配置模板；只引用凭据，不保存密钥 |
| [requirements.txt](requirements.txt) | 仓库 Python 环境之外的评测/测试补充依赖 |
| [tests/test_runner.py](tests/test_runner.py) | 固定 AMB 代码＋合成会话＋模拟服务/模型的离线检查 |

**当前状态：**固定 AMB `28b644bd4dd653c0207c7507280439390c829155`，类别 1–4，默认 conv-30 的 81 题。目录整理后已在个人分支基线上通过 27 项离线检查，Ruff 和类型检查通过；现已复用旧 Bank 完成 81 题 8K 实测，结果见 [复测对照](plan.md#conv-30-8k-复测对照)。

旧版 conv-30 记录为准确率 91.36%、答案 F1 25.15%，存在已确认的上下文打包缺陷和评分尺度差异。新 AMB 协议实测为 **70/81、准确率 86.42%、F1 21.98%**；两版 prompt/裁判不同，不作为单独打包改动的因果对比。旧结果不覆盖，Bank 和运行环境保留，完整 1540 题未运行。

## 离线验证

在代码仓根目录执行。已有仓库 `.venv` 时，只需按需补充评测依赖；安装命令不启动服务或模型：

```bash
uv pip install --python .venv/bin/python -r benchmarks/memory/requirements.txt
```

测试只需要固定版本 AMB 的源码，不需要真实 LoCoMo 数据、业务密钥或模型账户。当前机器已准备源码；其他机器先准备同一 commit 的 checkout，再设置路径：

```bash
export CONTEXTBASE_AMB_CHECKOUT="/path/to/agent-memory-benchmark"
.venv/bin/python -m pytest benchmarks/memory/tests -q --override-ini addopts=''
.venv/bin/python benchmarks/memory/runner.py --help
```

测试使用合成会话和临时本地模拟 HTTP 服务，不会访问 8891/8892 或调用真实模型。缺少 AMB checkout 时相关测试会显示跳过，不能将这种结果当作完整验证通过。

## 后续实测

先阅读 [执行计划中的命令与指标说明](plan.md#固化脚本与复测方法)。`init`、`preview`、`report` 为离线操作；`verify` 只读取产品服务核验，不调用模型；`ingest` / `run` 为实测阶段。

复用已有记忆时，在配置中设置 `reuse_banks`，例如 `{"conv-30": "locomo_conv30_20261118_200523"}`。新运行依次执行 init → verify → run；不能执行 ingest。脚本会核对原文、导入任务、公开配置和服务版本，并在 HTTP 层只允许指定 Bank 的 GET 与 recall，禁止创建、写入、删除和 reflect。留空则仍是新建 Bank 的导入模式。

连接中断后，可在新运行中通过 `checkpoint_source` 引用原 manifest 的路径与 SHA-256。脚本要求题目、Bank、模型、预算、prompt 协议和依赖一致，复制并校验全部已有检查点；已完成的对错判定不重新生成。仅在显式声明 `resume_connection_failures=true` 且每次增加一次尝试上限（总上限 4）时，允许没有任何响应的连接失败再尝试一次，并可降低恢复并发；未收到回包的中断检索可重新读取；原失败记录和未知用量全部保留。逐题操作失败会计入失败并继续余题，不再中断整组。

当前模板指向本机 API `127.0.0.1:8892`。部署基础为 `dd5521cb…`，并有后续 UI/网关更新；它与本分支不完全一致。脚本经 HTTP 测试部署实例，模型连接及辅助代码来自本分支，两部分版本分别归档。本次目录整理不升级或重启部署。

## 证据与维护

今后正文只在本目录的 README、plan、report 维护。旧的 `scripts/benchmarks/amb-contextbase*`、`contextbase-locomo*` 和独立旧驱动不再作为维护入口，也不进入本次提交。

原始数据、官方逐题文件、旧结果与验证证据继续保留在现有研究目录 `/Users/zhuqingping/Work/Database/Context/ContextDB-Research/.local-archive/benchmarks/`，本次不移动、不提交。新运行可放在本目录已忽略的 `.local/runs/<run_id>/`。任何凭据、运行数据、第三方源码 checkout、环境和缓存都不进入 Git。
