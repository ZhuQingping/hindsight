# 新实施 session 入口

> 实施接收后的最新状态（2026-10-18）：必需本地验收和 code-review 已闭合，最终源码 `9ba259fa3`，原生完整 c08、SDK 两品牌系统故事及 knip 均已通过。按用户明确授权正常停止原 READY 体验服务，数据/配置/容器保留，恢复交由原会话。当前保持 [Draft PR #5](https://github.com/RSIXDB/hindsight/pull/5) 供用户审查，不合主干；以 [RESULT.md](RESULT.md)、[VALIDATION.json](VALIDATION.json)、[PROGRESS.md](PROGRESS.md) 为当前状态。以下保留设计 session 的历史交接记录。

状态：`DESIGN_READY / DRAFT_UNVALIDATED / IMPLEMENTATION_AUTHORIZED`。2026-10-17。

## 用户意图与最新指令

用户此前做了两部分工作：① AgentStratum 品牌、Web UI 布局、API/MCP/Hook 接入适配；② 多 API Key、多 user 方案。用户现在选择同事的身份方案，我们的第二部分可以继续开发但不合主干。需要完整提交第一部分，不能漏掉第二条开发线里的通用产品成果。

本会话已核实：第一部分未合 origin/main；后续访问管理线继承早期 UI 且又增加统一品牌、定位与术语改动，其中很多尚未提交。用户先授权“请把你的方案写到文件中，然后实施你的方案吧”，后续明确：“方案设计你继续做，做完了请直接在新session开始方案实施”。

你是新的独立实施 session。直接承接已授权任务，不要再询问是否可以开始。先核对本交接和已有草稿，再修复、验证、提交独立产品分支。原会话在你启动后停止本任务写入。

## 唯一写入工作区

- worktree：`/home/cimon/code/hindsight/.local/product-brand-ui/worktree`
- branch：`product/agentstratum-brand-ui-20261016`
- 当前 HEAD / 基线：`f51b165a5165b1042ba0b6408fcffb5bc1a80fdb`
- 当前没有本任务提交、推送或 PR；所有产品改动仍为未提交草稿。
- 主仓 `/home/cimon/code/hindsight` 当前 main 有用户原有修改；其他 hosted/follow-up worktree 仍是独立开发线。全部保留，不 reset/stash/清理/代提交。
- 运行日志、快照、临时制品：主仓 `/home/cimon/code/hindsight/.local/product-brand-ui/`。
- 正式文件写入本 worktree `docs/agentstratum-brand-ui/`；主仓同目录是本次设计交接入口副本。

启动先执行 `pwd`、`git status --short --branch`、`git rev-parse HEAD`，确认自己的默认工作目录与以上一致；核对 manifest 后写 `docs/agentstratum-brand-ui/SESSION-ACK.md`，记录实际 session ID（可获取时）、cwd、branch、HEAD、接收时间与首项实施工作。

## 读序

1. 仓库 `AGENTS.md` → `CLAUDE.md` → `.claude/skills/code-review/SKILL.md`。
2. `hindsight-control-plane/AGENTS.md` 及安装版本的 Next 文档。已有主仓 `node_modules/next/dist/docs` 可只读；不能把训练时的 Next 行为当当前版本。
3. 本目录 `PLAN.md`、`DESIGN.md`、`ACCEPTANCE.md`、`DESIGN-REVIEW.md`。
4. `SOURCE-MAP.json` 和已有草稿完整 diff（包括未跟踪新文件）。

不要重新展开全部历史 hosted 设计，也不要重做本次已完成的分支调查。来源是证据；设计和当前用户范围是实施边界。

## 已完成的准备及其边界

1. 实时查询并 fetch 了 origin/main，创建上述独立 worktree。
2. 冻结后续源文件 856 个：`.local/product-brand-ui/source-snapshot/`；清单 `source-manifest.json` 的 SHA-256 为 `a9539a73c8ea810305067aefa0afc25198f714c736a6dfc9abb06d6044c1aef5`。快照包含排除项，不可整体复制。
3. 按路径提取早期 M2 的 control-plane、模板和 lockfile，排除其 hosted manager/runtime 祖先及旧报告。
4. 草稿已移植品牌配置、API/MCP 名称、语言和术语；初步移除了 hosted/access 依赖与管理入口。保留早期 bank-selector 和独立接入页，并合成通用 productFetch。
5. 初步测试、独立使用说明和配置文档已写入草稿。新增系统测试引用尚待生成的 ProductApi。**没有运行任何本候选 unit/build/runtime/browser 检查。**
6. `npm ci --ignore-scripts --offline` 的重型 wrapper 两次在执行前因其他任务持锁拒绝，npm 实际没有开始。不存在本任务的后台 API/PG/UI 进程。
7. 草稿源码共 95 个变更路径，冻结在 `draft-at-handoff/`；`draft-at-handoff.json` 的 SHA-256 为 `5c0cc0e7c4806a49d7187887e67e0061924c5f32f9f9f7899687a6384aff158e`，还保存了 tracked diff patch。`SOURCE-MAP.json` 是同一草稿清单副本。

这些准备降低重复劳动，但不代表实现已完成或源文件整体可直接采用。保留源快照及草稿快照不可变；新 session 在 worktree 中修改并产生新的候选哈希。

## 第一批实施事项

1. 对草稿做完整源码检查，特别是品牌插值、provider 顺序、登录/退出、Next proxy、普通 API 与文件 fetch 的旧页签语义、UI basePath、语言回落与失效管理链接。
2. 核对新增测试与真实 SDK 类型，例如 `test_98_product_naming.py`；缺生成物时先生成，不通过 skip 掩盖问题。
3. 完成 `scripts/hooks/lint.sh` 通用串行支持（当前草稿尚未提取），仅移植 LINT_SERIAL，不带 hosted 检查项。按限额准备独立依赖。
4. 仅从本分支 API 重生成 OpenAPI/SDK。现有原仓脚本依赖 Docker/Rust；当时 cargo/go 未发现，Java 可用。固定 7.10.0 generator jar 已存在于 `/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/follow-up-integration-20261016/tooling/openapi-generator-cli-7.10.0.jar`，若复用要先验证原 `api-generation/result.json` 中记录的哈希。可以参考 sibling `follow-up-simplified-20261016/generate-api-clients.py` 的执行方式，但不能运行它（它会写其他 worktree）。新适配器必须属于本任务、不修改共享脚本、不把生成当编译。
5. 执行验收矩阵，逐项保存真实证据与限制；修复失败。无新代码变更或未决问题时不要反复无差别重跑。
6. 最后完成仓库 code-review，更新 `RESULT.md`、审查报告和来源清单，提交并推送独立分支，准备 draft PR；不合主干。

## 资源和运行约束

重型命令唯一入口：

```bash
python3 /home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/run-bounded.py \
  --log /home/cimon/code/hindsight/.local/product-brand-ui/runs/<step>.log \
  --cwd /home/cimon/code/hindsight/.local/product-brand-ui/worktree \
  -- <command>
```

它复用共享锁、限制 CPU/内存/pids，并给出资源 JSON。锁占用时继续轻量工作或有界等待，不结束任务声称完成，也不停止未知持锁任务。不要复制 wrapper 去绕过共享锁。

当前内存约 7.6 GiB；重型验证限定现有 wrapper 的 3 GiB、2 CPU affinity 等边界。`npm ci` 使用 ignore-scripts 避免擅改共享 Git hook；需要的具体构建生命周期再显式执行。新依赖环境属于本任务，不修改其他 session 的 venv/node_modules。

PostgreSQL 镜像 `pgvector/pgvector:pg17` 当时已缓存。原系统测试 fixture 使用固定 `hindsight-systest:15499`，不可直接对未知共享库执行 sweep。使用独立本任务 PG/端口/数据库与明确记录的启动器；如复用 CI fixture，先证明其资源完全归本任务。无真实模型调用、无云部署、无生产写入。

不要启动额外子代理；一个持久实施 session 足以承接本任务。如需后续会话恢复，维护本目录状态和运行日志。

## 结束条件

完成独立分支、相关代码与配置、当前候选验证、code-review、提交/推送/draft PR（有远端权限时），报告真实未运行项。最终主干合并留给用户。

如遇外部环境阻塞，先完成其他授权工作，记录阻塞、已尝试动作、当前 candidate 和精确恢复命令；不能把未验证草稿称为“可合并”。
