# ContextDB 单提交：原生侵入点与安全检视

日期：2026-10-13。基线：`a77c1f3412a7b82f36588dffce1a8d7480e99cc7`。

本次将已有 ContextDB 实现、测试和 CI 整合为一个功能提交；按用户确认修正 ContextDB job 的首次安装及 ty 工具版本，以 git amend 保持一个提交。验证通过后推送至 ZhuQingping/hindsight 的 contextdb/service-management 分支供人工检视，不推送上游或部署服务。不修补运行时代码、不改变已确认架构。无关 `verification/`、环境文件、测试日志、数据库目录和被忽略的扩展锁文件不入提交。

## 结论与发现

**本地验证已通过，可推送功能分支供人工检视，不代表生产上线批准。** 实现以插件为主，但不是零侵入。首次安装缺锁文件与 ty 工具版本漂移两个问题均已按用户确认修复；本地复验通过，远程完整 GitHub CI 仍需独立观察，不能用本地结果宣称全部 CI 全绿。

- Critical：本轮未确认新的严重缺陷；这不是完整安全审计或无漏洞保证。
- Important / 安装问题已修复：原 ContextDB CI 首次执行 `uv sync --frozen`，但扩展 `uv.lock` 被忽略且不在提交中，干净环境返回 2。按用户确认，仅将这个 job 的首次安装改为 `uv sync`，现场生成锁文件；后续测试/质量检查仍使用 `--frozen`。未提交插件锁文件，也未改其他 job。干净本地安装与测试已通过，见下方复验记录。
- Important / 工具版本问题已修复：原 CI 使用未固定版本的 `--with ty`，下载 0.0.86 后报告 8 条 contextmanager/asynccontextmanager 注解弃用警告并返回 1。宿主 hindsight-api-slim/pyproject.toml 已明确固定 ty==0.0.84；ContextDB job 现使用 `--with ty==0.0.84`，与社区基线对齐。检查通过，未修改 Python 注解或关闭任何检查规则。旧失败日志仍保留在 `/tmp/contextdb-ci-fix-WRuAmu/ty.log`、`ty-py311.log`，用于解释修复依据。
- Minor / 维护关注：扩展使用 `_get_pool`、`_current_schema` 等宿主内部接口。接口适配有集中位置，但后续升级上游必须复验，不能视为稳定公共插件 ABI。

## 哪些代码是原生侵入？

以下路径相对 `hindsight-api-slim/hindsight_api/`。共 **9 个运行时文件，211 行新增、20 行删除**；不把测试或锁文件行数计入原生侵入量。

| 文件 | 增/删 | 修改及主要检视点 |
|---|---:|---|
| [api/__init__.py](../../hindsight-api-slim/hindsight_api/api/__init__.py) | +6/-1 | 将可选扩展中间件放在 MCP 分发层外，覆盖 REST/MCP；检查挂载顺序与双重安装 |
| [api/http.py](../../hindsight-api-slim/hindsight_api/api/http.py) | +5/-0 | 安装或暂缓安装扩展中间件；原生接口路径和字段不变 |
| [api/mcp.py](../../hindsight-api-slim/hindsight_api/api/mcp.py) | +104/-0 | 每条 HTTP 消息恢复真实认证身份和准入上下文，避免沿用会话首把 Key；SDK/会话兼容性是重点 |
| [engine/memory_engine.py](../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) | +24/-4 | 传递知识读取来源、支持内部多状态任务查询、入队前进入准入保护；检查授权与删除/入队竞态 |
| [extensions/http.py](../../hindsight-api-slim/hindsight_api/extensions/http.py) | +11/-0 | 增加可选纯 ASGI 中间件 hook，默认空列表 |
| [extensions/tenant.py](../../hindsight-api-slim/hindsight_api/extensions/tenant.py) | +14/-0 | 增加入队作用域 hook，默认 no-op；避免拿着原生连接等待空间锁 |
| [extensions/operation_validator.py](../../hindsight-api-slim/hindsight_api/extensions/operation_validator.py) | +4/-0 | mental model 读取上下文增加服务端来源，区分知识页面和原始模型；不是客户自报授权字段 |
| [mcp_tools.py](../../hindsight-api-slim/hindsight_api/mcp_tools.py) | +41/-15 | 区分预期权限拒绝与未知异常；错误被包装成成功协议响应时仍报告清理屏障，不转交异常/正文 |
| [worker/main.py](../../hindsight-api-slim/hindsight_api/worker/main.py) | +2/-0 | 关闭引擎前执行租户扩展关闭 hook；需要关注其他自定义扩展的关闭行为 |

**不是所有补丁都默认 no-op。** 空中间件和入队 hook 是可选默认行为；MCP 身份恢复和 Worker 关闭流程修改了共享执行路径，须依靠兼容回归。部署必须使用带补丁的宿主，不能只复制插件到任意社区版本。

未修改向量检索、事实提取或反思算法，也未修改原生记忆表/Alembic 迁移。新增 `ctxdb_meta` 的 9 张表及动态成员/Key 管理是我们实现的逻辑，不是上游现成的用户管理能力。

## 其他提交内容

- `hindsight-extensions/contextdb-service/`：Tenant/Validator/HTTP 扩展、元信息 DDL、生命周期、请求准入、配置、安全凭据和测试。
- `hindsight-system-tests/`：100–109 测试、隔离启动/失败清理辅助、测试依赖及锁文件；锁文件大部分差异源于系统测试新增宿主运行环境，不代表同等规模的运行时修改。
- `.github/workflows/test.yml`：扩展与系统测试 CI 接入；ContextDB job 首次安装生成本地锁文件，类型检查沿用宿主 ty==0.0.84。
- `hindsight-extensions/README.md`：扩展索引。设计依据为 [ContextDB 首期服务化设计固定版本](https://github.com/ZhuQingping/ContextDB-Research/blob/a600d8f34fcab1eb485a48b0916f2a2c6ca49484/hindsight/member-apikey-bank-service-design.md)。

## 首次整合时执行的验证

| 检查 | 状态与结果 |
|---|---|
| 扩展测试 `pytest tests -q`（扩展目录；源码根 `.venv`，扩展在 PYTHONPATH） | RUN，退出 0，175 passed；合成凭据、独立临时 PG |
| 系统测试 100–109（系统包目录；`/tmp/contextdb-fresh-venv-xUtcz9/bin/python`） | RUN，退出 0，47 passed，包含 41 个真实进程场景及 6 个辅助回归；内置/独立 Worker、REST/MCP、stub 模型 |
| 原生 `test_extension_context`、`test_mcp_extension`、`test_mcp_routing`、`test_mcp_tool_filtering`、`test_worker_main` | RUN，退出 0，41 passed；源码根 `.venv` |
| `./scripts/hooks/lint.sh` | RUN，退出 0；在 `/tmp/contextdb-lint-6xQ64s` 隔离 worktree，9 个原生文件与当前源码逐文件比较一致，不在主仓自动修复 |
| 新增扩展/系统用例 Ruff；扩展 format 与 ty | RUN，退出 0；仅检查，不自动修补源码 |
| `git diff --check` | RUN，退出 0 |
| 不含扩展锁文件时的原 CI 安装前置 dry-run | RUN，退出 2，复现修复前的安装问题；临时目录 `/tmp/contextdb-single-commit-review-vViJ1Y/ci-check` |
| 全套上游测试、完整 GitHub CI、3.11–3.14 全版本矩阵 | NOT RUN；本轮仅定向回归，不能外推全量兼容 |
| 真实云管控/HTTPS/来源限制、容量、故障恢复及生产模型 | NOT RUN；生产验收另行开展 |

既有第三方/导出弃用告警未作为通过依据；重复测试批次不累加。测试只启动 fixture 自己的进程和临时数据库，不重启已有部署。

## CI 首次安装修复复验（2026-10-13）

隔离 worktree：`/tmp/contextdb-ci-fix-WRuAmu/worktree`，从修改前提交干净检出；首次运行确认插件没有 uv.lock 或 .venv。实际安装使用本机 Python 3.12.13，不代表 Linux GitHub runner 全流程验收。

| 检查/命令 | 状态与结果 |
|---|---|
| 无锁文件执行原命令 `uv sync --frozen --dry-run` | RUN，退出 2，复现缺锁文件；没有先复用本机锁文件 |
| 插件目录执行 `uv sync` | RUN，退出 0，生成本地锁文件并安装；`install.log` |
| `uv run --frozen pytest tests -q -ra` | RUN，退出 0，174 passed、1 skipped；兄弟研究仓不存在，跨仓文档合同测试按既有约定跳过，独立管理 OpenAPI 测试仍执行；`tests.log`、`tests.xml` |
| CI 的 Ruff check、format --check（均保留 --frozen） | RUN，退出 0；`ruff.log`、`format.log` |
| 当时 CI 的 `uv run --frozen --with ty ty check hindsight_ext_contextdb` | RUN，退出 1，8 条弃用警告；同一检查指定 --python-version 3.11 亦失败；后续工具版本修复见下一节，不改写这次失败事实 |
| YAML 解析与修改前结构比较 | RUN，PASS；仅 ContextDB job 首次安装 run 值变化，其他步骤/job 均不变 |
| 原生运行时代码、插件 Python/DDL 改动检查 | RUN；相对修改前提交无改动，原生侵入仍为 9 文件 +211/-20；本次不复跑完整系统/原生回归 |
| 插件 uv.lock 忽略规则、diff 检查 | RUN，PASS；生成文件仍被忽略、不入提交 |

新日志均在 `/tmp/contextdb-ci-fix-WRuAmu/`，不入功能提交。没有在主仓同步环境、重启现有服务或改全局配置；未执行完整远程 GitHub CI。

## ty 版本修复与推送前验证（2026-10-13）

新的隔离 worktree：`/tmp/contextdb-ci-ty-pin-Ko7bay/worktree`，从 2bbbf0314 干净检出，仅应用 ContextDB job 的工具版本修正；首次确认没有插件 uv.lock 或 .venv。日志在 `/tmp/contextdb-ci-ty-pin-Ko7bay/`，不入提交。

| 检查/命令 | 状态与结果 |
|---|---|
| `UV_PYTHON=3.11 uv sync` | RUN，退出 0，Python 3.11.15，现场生成锁文件与独立环境；install.log |
| `uv run --frozen pytest tests -q -ra` | RUN，退出 0，174 passed、1 skipped；只有可选兄弟研究仓合同测试跳过；extension.log、extension.xml |
| 主仓单独执行 test_openapi_research_contract.py | RUN，退出 0，1 passed；与研究仓当前 OpenAPI 比较通过；research-contract.log；不与前序重复用例累加 |
| CI 的 Ruff check、format --check（保留 --frozen） | RUN，退出 0；ruff.log、format.log |
| CI 的 `uv run --frozen --with ty==0.0.84 ty check hindsight_ext_contextdb` | RUN，退出 0，All checks passed；ty.log；没有屏蔽弃用规则 |
| 系统测试 100–109，真实 API/两种 Worker 与 stub 模型 | RUN，退出 0，47 passed；system.log、system.xml；使用既有隔离 Python 3.12 环境，临时 PG 由 fixture 管理 |
| 41 项原生定向回归 | RUN，退出 0，41 passed；native.log、native.xml |
| 完整 scripts/hooks/lint.sh | RUN，退出 0；在此前隔离 lint worktree，9 个原生运行时文件与当前源码比较一致；root-lint.log |
| YAML 结构与 ty 版本比较 | RUN，PASS；相对 2bbbf0314 仅 ContextDB job 的 ty 调用变化，固定版本等于宿主 dev 依赖，其他 job 不变 |
| 运行时代码/DDL、暂存范围和 diff 检查 | RUN，PASS；本次仅 CI 配置及本说明变更，原生侵入仍为 9 文件 +211/-20；生成插件锁文件仍不提交 |
| 完整远程 GitHub CI、生产联调/容量/恢复 | NOT RUN；推送仅供源码检视，不等于发布或 GA 验收 |

新的通过结果不删除旧失败证据；重复批次不累加。此次按项目代码审核要求复核，两个已确认本地交付阻塞项已解决，维护及生产边界仍保留。

## 安全边界与尚需验证的风险

1. 管理 Key 与用户 Key 分开；节点复核来源、可信操作人、成员角色、schema/Bank 和 scope。认证不确定时拒绝。不能仅凭“用户不知道管理 Key”承诺安全，真实管理面身份替换、来源限制、HTTPS 与轮换仍待联调。
2. 同 Bank 的用户记忆仍共享；Key 归属不提供个人内容隔离。memory.write 允许修改共享内容，这是首期约定，不是已实现的个人 ACL。
3. 删除通过持久准入记录阻止误清理，但未知执行者/崩溃可能让删除一直等待；本期无自动恢复，需维护窗口确认旧 API/Worker 和 PG 工作会话停止，不能按超时清空记录。
4. 原生迁移 DDL 无强租约 fencing；当前禁止隔离迁移子进程模式。整库备份恢复、并发升级和多副本故障仍需专项验证。
5. 准入与管控另开同库连接池，并逐请求查询 PG；连接预算与延迟尚未压测。MCP 自定义重放和 session-owner 硬化未覆盖，不承诺所有自定义 MCP 配置安全。

## 检视建议

Recommendation：**ACCEPT WITH RISKS（功能分支推送/人工检视范围）**；本地复验通过，允许按用户要求推送，不代表自动合入上游或生产上线。后续观察远程完整 CI，重点人审 api/mcp.py 的逐消息上下文及 memory_engine.py 的入队保护，并完成上述生产门槛；不得省略既有风险。需要人审。

从源码仓查看原生侵入：

```bash
git diff a77c1f3412a7b82f36588dffce1a8d7480e99cc7 HEAD --stat -- hindsight-api-slim/hindsight_api
git diff a77c1f3412a7b82f36588dffce1a8d7480e99cc7 HEAD -- hindsight-api-slim/hindsight_api
```
