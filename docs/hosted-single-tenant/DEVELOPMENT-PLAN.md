# 开发计划：分阶段实现、并发交付与质量出口

2026-10-12。产品范围见 [README](README.md)，本地优先的决策见 [EXECUTION-PLAN](EXECUTION-PLAN.md)。本文件将 E0—E6 拆成可分配给 agent 的任务；[development-state.json](development-state.json) 记录实际进度；[AGENT-WORKFLOW](AGENT-WORKFLOW.md) 规定如何派发、验收和续接。

## 1. 交付目标与工作原则

本地最终交付：从干净隔离资源，使用固定制品部署 Hindsight；管理服务经 agent 执行真实启停、配置、升级与释放；页面能操作和查询；多 key/有效期/bank 授权覆盖 REST/MCP/间接资源；原生主要能力与数据生命周期通过回归；异常可恢复或明确失败；结果可复现、可审查、可接续。

云端最终交付：相同制品与接入适配在专属 VM、云 PG、OBS、内部模型、平台身份/agent 通道和 HTTPS 下通过原 V01—V18，再按 V19 分批邀请。LOCAL、STUB、CONTRACT_FIXTURE 不能自动转换成 CLOUD PASS。

不先建设开发协作平台。使用当前主控、原生子 agent 工具、Git worktree、一个状态文件和测试 receipt 即可。产品管控 agent 是本次要实现的组件；开发 agent 是写代码和验证的执行者，两者身份、状态、协议和权限完全分开。

## 2. 工作包与依赖

每个工作包都要交付代码、适当测试、运行方法和已知限制。下列目录为拟新增的写入范围；现有代码补点由主控逐文件授权。任务进入 RUNNING 前，把候选基础提交、准确文件范围、命令和案例写进任务包，不能仅抄本表泛泛派发。

| ID / 阶段 | 具体产出与主要独占写入范围 | 前置工作包 | 通过标准 |
| --- | --- | --- | --- |
| D00 / M0 | 隔离 integration/worktree、构建依赖和资源登记；`deploy/hosted-single-tenant/README.md`、包骨架及 `bootstrap/` | 无 | 当前体验源码/服务不变；基线 SHA、工作区和运行目录可核对；依赖可用，资源与定向清理方法登记 |
| D01 / M0 | 类型化合同及示例：部署、操作、状态、结果、配置、key 管理、本地身份；`deploy/hosted-single-tenant/contracts/` | D00 | schema/revision/error/幂等/旧结果语义和最小请求响应可校验；消费方确认后发布本地合同 v1，不等内部最终协议 |
| D02 / M1 | 正式源码构建 API/UI，独立外部测试 PG，启动/停止及探针；`runtime/`、`fixtures/`（以下均相对 deploy/hosted-single-tenant） | D01 | 真实 API/UI 启动，版本/digest 可核对，PG 就绪；一次最小 SDK 请求通过；完整 S3/派生回归不阻塞下一任务 |
| D03 / M1 | 真实 Docker 执行器：deploy/start/stop/status；`executor/` 及对应测试 | D02 | 显式登记资源才可操作，执行真实容器，失败不会返回成功；命令输入不拼接任意 shell |
| D04 / M1 | 本地管理 API、实例目标状态、持久操作与领取/结果接口；`manager/` 及对应测试 | D01 | 操作持久受理、同 ID 幂等/冲突、旧 revision 拒绝、重启保留记录；本任务可用 fixture 验接口，M1 集成必须接真实 executor |
| D05 / M1 | 常驻 agent 的注册/心跳/执行/持久待上报，贯通管理 API；`agent/` 及对应测试 | D03、D04 | 管理 API 提交 deploy → 真实 agent/执行器 → API/UI 就绪 → 管理端查询实际状态；不以 fake executor 关闭本 Gate |
| D06 / M2 | Key 存储/迁移、认证、管理 API/CLI；`hindsight-extensions/hosted-single-tenant/` 的 store/auth/admin 及私有测试 | D02 | 实例 PG 存校验值、一次性明文交付、UTC 到期和停用；管理身份独立，重启保持；检查扩展表和原生数据工具兼容边界 |
| D07 / M2 | Bank validator 与逐入口授权；同扩展 validator、独占 SDK/MCP 测试文件 | D06 | 列表/分页、别名、懒创建、任务/chunk/附件、clone/transfer 源目标、MCP 会话拒绝通过；已受理任务继续原生语义 |
| D08 / M2 | 配置/restart/upgrade/release、失联与恢复；接续 D03—D05 原写入范围，禁止与原作者同时写 | D05 | 单实例操作互斥；持久化前后及副作用后的故障案例通过；释放保留数据，迁移部分成功不假报完成；实际进程重启有证据 |
| D09 / M2 | 可操作真实本地实例的管理页面；`manager-ui/` | D04 | 浏览器可查看实例/版本/资源/操作，错误和进度可见；D05/D08 到位即跑真实联调；仅 fixture 的页面不得关闭 M2 |
| D10 / M2 | 原生功能 UI 品牌/布局/导航、会话适配；`hindsight-control-plane/` 的明确文件清单 | D02 | 主要原生页面可用，本地受保护登录/退出、stream/文件；全权限 key 留后端；完整授权组合在 D12 验收 |
| D11 / M2 | 原生 SDK/MCP、S3 文件与派生回归；独占 `hindsight-system-tests/tests/` 故事及 `deploy/hosted-single-tenant/tests/native/` | D02 | 文件全生命周期、bank/document/knowledge 能力、后台派生终态、SDK/MCP 通过；明确 stub/现有模型；共享 fixture 变动由主控协调 |
| D13 / M2 | 日志/metrics/诊断、构建/CI覆盖及配置模板；`observability/`、`checks/` 和 `ci/`；根 CI 改动单独授权 | D05、D06 | 能定位实例/版本/操作；探针区分 API/UI/依赖/任务；新目录进入 lint/type/test/CI，脱敏及依赖失败可观测 |
| D12 / M3 | 全栈组合与独立验收；`tests/acceptance/`、`tests/browser/` | D07、D08、D09、D10、D11、D13 | 真实管理页→管理 API→agent→Hindsight；权限+后台/文件/MCP组合、双实例隔离、异常和干净重复部署通过 |
| D14 / M3 | 本地固定候选、交接、原生回归结果和操作说明；发布清单及 evidence | D12 | 独立 review、集成 SHA 的必要测试、制品可重复交付；内部未接入点逐项列明，任务完成不等于云发布 |
| C01 / M4 | 真实云依赖接入与兼容验证，沿用代码和场景 | D02 + 对应真实资源 | PG/OBS/内部三模型/TLS 在一套真实专属实例通过；资源分批到位分批验证，不等待全套 |
| C02 / M4 | 内部管理/身份/agent/观测适配及发布验收 | D14、C01 + 平台接口 | 真实 V01—V18、两套资源隔离、客户接入和支持交付齐备；发布/远端合并检查由用户保留 |

D 编号是稳定标识，不代表必须按数值顺序执行；D13 在 D12 之前完成。状态文件持有同一依赖图。内部等待只记录 C01/C02 对应子案例，其他 READY 工作继续。

## 3. 里程碑与并发批次

| 里程碑 | 用户能看到的结果 | 调度安排 |
| --- | --- | --- |
| M0 基线与合同 | 可接续工作区和可校验合同，仍不是产品完成 | 主控完成隔离与写入边界；builder 落合同；独立 agent 检查失败语义 |
| M1 最短真实闭环 | 管理 API 让 agent 部署 Hindsight，查询到真实结果 | 合同后 D02 与 D04 并行；D02 完成后 D03 与 D06 并行；D05 集成时安排独立测试槽 |
| M2 功能完善 | 授权、配置升级恢复、两个 UI、原生回归和观测 | D07、D08、D09/D10 按写入范围和槽位轮换；D11/D13 在依赖就绪即推进；review 优先于新开第三开发任务 |
| M3 本地可交付 | 固定制品、真实页面与 agent、重复部署和故障证据 | 冻结候选，集成/浏览器/独立审查轮换；阻断缺陷修复后只复测受影响范围及必要集成 |
| M4 云发布验收 | 专属云资源、真实身份及平台链路就绪 | C01 滚动执行；C02 由真实条件与固定候选共同关闭；准备好才分批邀请 |

默认总并发 4：主控 1 + 开发 2 + 独立测试/review 1。无 review 积压且写入和资源完全分离时可短暂用第三开发 agent。主控的 shell 后台任务也记资源占用；Docker 大构建、完整系统测试、浏览器重验收共享一个重任务槽，避免开发机内存争用。轻量静态测试与只读 review 可并行。

每个子任务目标是一次可审查的行为增量；连续两轮出现同类失败或一次接续仍不能说清下一动作时，主控收窄任务、增加反例或换独立诊断，不盲目无限重试，也不自动全局暂停。任务耗时按实际证据更新，不承诺未经测量的人天。

## 4. 必须具备的验收案例

以下 case ID 在任务包内展开为实际测试名、命令和证据路径。没有场景结果不能仅凭勾选关闭任务。

| 类别 | 必测案例 |
| --- | --- |
| B01—B03 部署 | 干净资源构建启动；配置/PG故障拒绝就绪；API与UI分别检查、重复部署不污染其他实例 |
| K01—K05 Key | 多 key/期限临界点；停用及scope变更；普通 key 无管理权；重启持久/查询脱敏；管理变更后下一新请求生效 |
| S01—S07 Scope | bank允许/拒绝；分页/total/别名；重复文档ID/chunk/附件；任务读写控制；clone/transfer双端/manifest；MCP旧session后续请求；已受理任务及派生继续、新请求拒绝 |
| A01—A04 Agent基础 | 真实deploy与状态；指令同ID重复/冲突；身份/路径/secret/资源范围；旧目标和延迟结果不能覆盖新revision |
| F01—F08 失败窗口 | 受理前后持久化；副作用完成但记录未落；结果已落但未上报；上报ACK丢失；agent/manager真实重启及第二执行者冲突；控制面失联/恢复；迁移成功但API/UI失败；release中断重试且PG/OBS数据保留 |
| N01—N05 原生 | retain→观察/mental model/knowledge各终态；recall/reflect/stream；文件/导入导出/清理/S3签名；SDK/MCP；bank/文档/图/配置/诊断等清单回归 |
| U01—U03 浏览器 | 管理页真实操作和失败展示；功能UI等价、登录退出和stream/文件；凭证不进入浏览器且未授权实例拒绝 |
| O01—O03 交付 | 日志/诊断脱敏及关联；探针/任务/磁盘/依赖可区分；新模块lint/type/CI与制品清单覆盖 |
| I01—I03 集成 | 同候选全链路；两个实例/不同PG凭证/bucket交叉访问拒绝；重启与干净重复部署 |
| C-V01—C-V19 | 原 [INTEGRATION-AND-ACCEPTANCE](INTEGRATION-AND-ACCEPTANCE.md) 的真实云案例，逐条保持运行状态 |

原生 Hindsight 黑盒走已发布 Python client；agent/管理 API 使用自身公开 HTTP 接口与真实执行后端；MCP 使用实际 session/tool 调用；浏览器使用真实页面。不同测试入口各尽其责，不为统一形式绕过原生 SDK 或伪造控制面效果。

## 5. 质量和范围控制

工作包开发完成仅表示提交候选；独立 review 和集成后的证据通过才标 DONE。M3 必须覆盖本地所有必测案例且无未解决 must-fix；should-fix 有明确处置和理由，影响隔离/数据/恢复/主要能力的不能以延期绕过。M4 还需要真实资源证据。

原生扩展优先，必要核心补点以最小复现和独占文件任务处理。保留 PostgreSQL 扩展表与原生备份/导出/恢复工具的兼容性检查，不能把 key 凭证随 bank transfer 泄露；这不扩大为建设云备份。新 API、配置、SDK、UI代理和迁移的同步要求沿用 CLAUDE.md。

已有体验进程以 editable 方式使用当前源码，产品实现一律在独立 checkout；本轮计划文档可在主工作区维护。严禁把 `git clean/reset --hard` 当作接续手段，严禁清理未登记的现有容器、数据库、bucket 或其他项目进程。
