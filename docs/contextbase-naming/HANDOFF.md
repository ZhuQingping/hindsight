# 新session接手：ContextBase 命名解耦与改名

先读[目标和验收合同](GOALS-AND-ACCEPTANCE.md)，再按本文接手。[START-PROMPT.md](START-PROMPT.md)可直接复制启动新session。[STATUS.json](STATUS.json)是本次只读核验的输入快照。

## 本轮交接状态

本session只持久化目标、验收及启动材料，不实施改名、不修改产品源码、不创建下一阶段worktree、不安装依赖、不运行重型任务，也不替用户创建新session。ContextBase实施与新验收均为`NOT_STARTED / NOT_RUN`。先前笼统工期估计已撤回，新session必须先建立真实改动清单。

## 固定输入及工作区

- 先前完整整合交付基点：`530a630641c7fe5ab274e510e5551eb24e99378b`，源码检查点`5d350568ae3d7537e452999cb6d0fae86b64563b`。
- 当前材料所在worktree：`/home/cimon/code/hindsight/.local/product-brand-ui/integration-worktree`，分支`integration/agentstratum-brand-ui-clients-20261019`。[Draft PR #8](https://github.com/RSIXDB/hindsight/pull/8)，不自动合并/关闭/重定向。
- 本材料的docs-only提交会位于该分支的530a63064之后；其产品源码输入不变。新session先验证HEAD、dirty状态和祖先关系，若分支后来有变动，明确实际基点及额外diff，不能直接套用旧状态。
- 推荐在下一阶段另建`/home/cimon/code/hindsight/.local/product-brand-ui/contextbase-naming-worktree`和`product/contextbase-naming-20261019`，从包含本材料的整合分支提交起步。只有新session开始任务才创建；名称已占用时先核验归属，不覆盖。
- 不从旧原始brand worktree或main单独开工而漏掉同事修复。原worktree`/home/cimon/code/hindsight/.local/product-brand-ui/worktree`、分支`product/agentstratum-brand-ui-20261016`在交接核验时clean、HEAD b799f721；不修改它或其他工作区。

## 读序与可信来源

1. 新工作区的AGENTS.md与CLAUDE.md，写代码前完整读取`.claude/skills/code-review/SKILL.md`；按当前用户及developer指令决定工具/审查方式，不主动派生额外实施agent。
2. 本目录`GOALS-AND-ACCEPTANCE.md`、`HANDOFF.md`、`STATUS.json`。
3. `docs/agentstratum-integration/{RESULT.md,CONFLICT-RESOLUTION.md,INDEPENDENT-REVIEW.md,VALIDATION.json,SOURCE-MAP.json,OPERATIONS.md}`，用作已整合能力/来源及历史验证基线。
4. `docs/hosted-single-tenant/module-delivery/M2/CLIENT-DISTRIBUTION.md`，注意其历史验证与当前证据的区别。
5. 下述真实源入口，再输出当前命名盘点；勿将812等文本搜索命中数误作手工改动清单。

旧整合PLAN的IN_PROGRESS和D1文字是该候选的阶段记录，实际交付以整合RESULT及固定源码为准。本目录是后续命名任务目标，不能倒改旧PASS的产品名或把旧PASS当成ContextBase通过。

## 已核验的命名入口与缺口

| 入口 | 当前事实/接手动作 |
| --- | --- |
| `hindsight-api-slim/hindsight_api/product_config.py` | v1模型extra=forbid，contextdb_name只收小写slug；注释仍要求显示/协议同值。需要按N03解除混用并处理版本兼容，不直接填ContextBase。 |
| `hindsight-api-slim/hindsight_api/brand.py` | 部分固定协议常量已集中；API/service/MCP名字函数仍直接取contextdb_name。可复用适配入口，不能把“已有brand.py”当成全部组件已集中。 |
| `hindsight-control-plane/src/lib/product-config{,-server}.ts` | TS严格检查v1键集与小写regex；server对比API配置，跨端合同必须同步处理。 |
| `hindsight-control-plane/src/components/brand.tsx`、产品context/provider、页面metadata及i18n | 动态展示能力已有，盘点真正默认值/标识来源；复用现有布局和品牌保护，不逐页重写。 |
| `hindsight-cli/{Cargo.toml,src/main.rs,src/config.rs,src/api.rs}` | binary/参数/配置命名与远程连接已有；保留Profiles、凭证隔离与nullable trigger PATCH，不因改名回退。 |
| `hindsight-integrations/coding-agents/{package.json,src/installer.ts,src/core}` | package/bin/env/目录/工具/MCP所有权分散。新旧canonical/alias要明确，11家JSON＋Codex保护回归不能丢。 |
| Claude/Agent Plugin manifests、scripts、打包安装和CI | 区分源manifest、生成物、固定身份、运行展示与历史字串；四类候选按同一映射出包。 |
| `scripts/generate-clients.sh`、`prepare-client-spec.py`及各SDK | 保留非空数组元素与旧公共签名guard；从当前API重生成，不复制旧权限SDK，不手改生成物冒充权威。 |

上述是入口清单，不是最终穷尽设计。首次解耦允许集中修复适配层，完成后必须实际执行“二次改名演练”，证明下一次不再人工扫全仓。

## 既有验证可复用，结果不可继承

整合源码5d350568的基线：frontend379；Coding Agents1362通过/6skip＋最新focused267/2skip；API scoped303/71skip/1deselected；Claude226；CLI153普通用例＋独立原生25；SDK432签名/485路径生成零漂移/Go3；原生19组＋SDK黑盒5；HTTPS安装8＋11subtests；release9与Linux候选工件独立复审均有证据。原生UI制品hash `7bb60c91851cc4d621a55293f66a18bc9e9a2c568ffe4717e8dffd4f65e111cb`仅属于旧名字候选。

执行脚本/冻结harness和独立工具链在主仓`.local/product-brand-ui/runs/integration-20261019`；下一阶段日志统一建议`.local/product-brand-ui/runs/contextbase-naming-20261019`，新建独立输出，禁止覆盖旧日志、PG数据或候选工件。借用已有工具/缓存前核验版本和所有权，不在系统profile中改PATH/工具。namespace/TMPDIR隔离经验见旧PROGRESS，不能通过改产品Git探测或跳过断言规避环境问题。

## 重型资源与运行服务

唯一runner：`/home/cimon/code/hindsight/.local/hosted-single-tenant/development/runs/m2-access-ui-delivery/run-bounded.py`；唯一锁是其同目录`resource-heavy.lock`。新session核验原脚本，不复制第二套锁/配额逻辑，不删除锁，不抢停其他任务，不把排队/未运行算PASS。现有enqueue-bounded.py仅排队到同一runner，原版本固定cwd为integration-worktree，不能直接拿它在新worktree跑而测错源码；需明确改cwd参数、日志路径，且仍调用同一runner。

内核资源证据：父进程3GiB/256pids、CPU affinity0–1；1.5核quota在该WSL未落实，实际记录false/上界2核。owned PG有独立512MiB/96pids及同CPU affinity。适配harness时核验真实W/venv/生成器/工具链/产物/数据源，禁止在新源上挂旧artifact冒充新验收。

交接核验时preview-01结果文件为READY，服务API28920/UI28921/PG28922，source5d350568，两小时lease到2026-10-19 13:22:29（Asia/Shanghai）。结果、STOP路径及owner信息在`.local/product-brand-ui/runs/integration-20261019/preview-01/result.json`。这只是交接快照，后续必须重查进程、锁和到期状态。本轮不停止预览；新session可先进行不需锁的盘点/设计。重型前按当前归属、移交及用户已有授权正常协调释放或等待到期，不能把早先针对28910/28911的停止授权泛化为任意服务授权。不得kill其他任务、删数据、配置或容器。

## 新session第一步与持续交付

1. 核对cwd/HEAD/dirty状态/输入源及资源归属，写本目录或下一工作区的`SESSION-ACK.md`，明确接收范围、实际基点及首个盘点动作；不要止步ACK。
2. 写`INVENTORY.md`、`NAMING-MAP.md`，分清已定/建议/需要兼容决策的项，给出真实手改入口与自动生成清单、原功能复用清单。
3. 在明确范围内补齐最小解耦与ContextBase改名；如需越界外部不兼容变更，先准备具体差异再澄清。执行N05演练及其余验收，不将回归等待计为功能重写。
4. 持续维护`PROGRESS.md`，最终写`RESULT.md`/`VALIDATION.json`/来源与兼容说明，绑定新源和新制品；完成必要独立review、可复核提交/适当draft PR。历史失败和NOT_RUN保持可见，不合并main、不公开发布。
