# Agent 开发工作流：并发、状态、接续与独立质量

本文件是 [DEVELOPMENT-PLAN](DEVELOPMENT-PLAN.md) 的执行约定。基于本会话已提供的 collaboration 工具执行，不依赖另建 Agents SDK 服务、递归 Codex CLI 或自动调度守护进程。

## 1. 主控与短期 agent

主控持续负责目标、依赖、任务包、状态、资源、候选集成与对用户汇报。子 agent 只接一个有界任务，提交候选和证据后退出或接受下一个明确任务；不依靠永久角色积累全部项目记忆。默认沿用当前模型，不自行切换型号或增加付费执行器。

本会话总槽位 4（包含主控）；新会话必须重新核对工具上限。通常主控 + 两名开发 + 一名独立测试/reviewer。所有后代也计入容量，子 agent 不自行再派发。若后续会话没有协作工具，则先继续能独立执行的工作并如实记录独立 review 待完成，不把作者自查写成独立审查。

派发前查状态与资源，调用 spawn_agent，取得真实 agent 标识并登记；随后要求 START_ACK（任务/attempt、工作区、base SHA、合同版本、写入范围）。没有 ACK 不能宣称已经开展编码。send_message 用于在途纠偏，followup_task 用于已有空闲 agent 的新任务；实际工具可用性以当前会话为准。

## 2. 文件与权威

| 文件/目录 | 用途与写入者 |
| --- | --- |
| README/EXECUTION-PLAN/DEVELOPMENT-PLAN | 已接受范围与执行计划；主控维护 |
| development-state.json | 唯一结构化开发台账；主控单写，revision递增，先写临时文件再原子替换 |
| START-HERE.md | 短接续入口；指向台账，不另维护一份冲突任务表 |
| templates/TASK-PACKET.md | 派发/交付/review模板；每 attempt 实例化到正式小型交接记录 |
| evidence/ | 小型候选、测试、review与决策记录，脱敏后进Git；主控收录子agent提交结果 |
| 主仓库 `.local/hosted-single-tenant/development/` | worktrees、运行目录、大日志和截图；不纳入Git，不复制完整聊天 |

状态中的 task 与 attempt 分开：同一任务可有多次尝试；失败历史不能重写为成功。candidate、evidence、review 都绑定 task/attempt 和确定版本。会话只是执行通道，聊天摘要、心跳或工具调用数量不是任务完成证据。

## 3. 单任务协议与状态机

任务状态：`PLANNED → READY → RUNNING → IN_REVIEW → VERIFIED → DONE`；另有 `REWORK / BLOCKED / CANCELLED`。进入 READY 须前置任务 DONE 或已有被显式批准、版本固定的接口先行条件；本项目初始无此例外。VERIFIED 表示作者测试及独立 review 对该候选通过；DONE 还要求集成及受影响验证通过。不能从 READY 跳 DONE。

Attempt 状态：`DISPATCHING / ACTIVE / SUBMITTED / INTERRUPTED / SUPERSEDED / ACCEPTED / FAILED`。失联时标记需要核对，保留容量与资源占用，不能直接当停止。RUNNING 任务最多一个当前 active_attempt；每条迟到结果校验完整执行身份，不匹配则保留为 NOT_ADOPTED，不能覆盖新结果。

每个任务同时记录 author_tests、independent_review、integration_check、local_acceptance、cloud_acceptance 状态。结果取 `NOT_RUN/PASS/FAIL/BLOCKED/STALE/NOT_APPLICABLE`；只有真正不适用的门可带理由记 NOT_APPLICABLE，云未测必须为 NOT_RUN/BLOCKED。

循环：读取合同与任务 → 最小实现 → 对应测试 → 修复 → lint/type/必要生成 → 提交固定候选 → 独立review → 修复及新候选 → 集成 → 受影响测试 → 台账及交接。自动测试失败先区分代码、环境和基线问题；记录具体证据，不通过削弱断言、换mock、删除案例或无理由xfail把失败刷绿。

## 4. 并发写入与运行资源

每个开发 attempt 使用独立 branch/worktree，路径必须显式传给工具；子 agent 不写主控工作区、正式状态或他人目录。工作区在主仓库 `.local/.../worktrees/<task>/<attempt>/` 下，创建前核对未被Git纳入；如需忽略只用精确本地 exclude 条目，不隐藏其他未跟踪文件。

任务写入范围用实际目录或文件路径，主控检查祖先/子路径重叠。根依赖/锁文件、共享fixture、迁移编号、contracts、OpenAPI/SDK生成、CI、`api/http.py`、`memory_engine.py` 等共享热点每次仅一名写入者；其他任务提交变更请求，主控分配独占窗口。即使在不同 worktree，语义冲突仍需串行处理。

每个 attempt 单独的运行 namespace、端口、PG/账户、bucket/凭证和容器标签。资源台账记录 holder_attempt_id、用途、进程/容器引用和释放证据。系统黑盒默认 PG 端口 15499 等共享fixture在未改成隔离运行前必须串行。重构建/完整系统测试/浏览器验收共用 `heavy-runtime` 一个槽位；轻量单元和只读review可同时执行。主控自己启动的后台进程也占对应资源。

JSON 的 owner/epoch 是协作约定，不能物理阻止旧agent写文件，也不构成Docker或OS权限隔离。防旧写依靠独立工作区、核实停止或新的隔离资源；不宣称有未经实现的强fencing。避免在共享Docker守护进程用通用prune；产品agent的Docker权限边界另行实际验收。

## 5. 合同先行与变更

只在接口、状态转移、失败窗口等耦合处做短“提案—反例—确认”：提供方提交带revision的schema/样例；消费方指出重复、超时、部分成功、旧结果反例；主控收敛，写入consumer ACK。内部团队未反馈时可发布本地合同，不假装内部已接受。

接口认可与集成成功是两个门。前者证明双方理解一致；后者必须在固定候选和环境中实际运行。合同变化时先更新台账和影响任务，把受影响ACK、候选及证据标STALE，再通知开发者。无关任务继续；保留既有证据须记录其依赖输入未变化的依据。没有通过重评的新合同不能继续消耗旧通过结论。

## 6. 固定候选与独立 review

作者封版前运行相关测试及仓库要求的 lint，处理生成文件，提交代码并确保候选工作区无未收录变更。候选至少记录 base_sha、candidate_sha、tree_sha、合同revision、依赖候选、锁文件hash、制品digest、配置revision、迁移版本、环境类型、required_cases和结果。字段不适用写明原因，不用假值填满。

Reviewer 不得是候选代码作者；主控写过相关实现时也不能充当唯一独立reviewer。Reviewer 使用固定SHA的独立只读审阅工作区；如需跑会修改文件的工具，使用一次性验证worktree。审查时只报告问题，修复返回作者；用户已授权常规修复，无需每条must-fix重新请示。

仓库要求实现前读 [code-review规范](../../.claude/skills/code-review/SKILL.md)，实现后及push/PR前执行规定review。`scripts/hooks/lint.sh` 会 uv sync、eslint/ruff --fix、prettier --write：作者在自己worktree封版前运行；reviewer在一次性worktree运行并核对diff，产生代码改动即失败，不偷偷更新候选。新deploy/extension目录是否纳入lint/type/CI须专门检查，不能仅看旧脚本退出0。

review报告含 severity、文件/行、具体反例、影响、要求的回归测试和处置。must-fix清零；should-fix逐项说明修复或延期理由，关键授权/数据/恢复缺陷不能降级。作者修改即新candidate，旧review仍保留但标STALE；若仅无关审计元数据变化，可记录等价范围后复用代码证据，不能笼统沿用PASS。

主控串行cherry-pick/merge到专用integration分支，记录集成SHA；解决冲突本身也纳入review。重跑受影响合同/组件/黑盒与里程碑集成，证据绑定集成SHA，不能拿分支测试代替组合测试。应用发布候选必须完整独立验收；最终远端合并/对外发布由用户检查，不擅自完成。

## 7. 测试分层与质量门

| 层级 | 要求 |
| --- | --- |
| 单元/机制 | UTC、权限、状态机、重试、配置、脱敏用直接行为断言；避免复制实现或只assert mock被调用 |
| 原生API系统故事 | `hindsight-system-tests` 经已发布Python client调用真实API，不用engine/SQL绕过；后台相关故事显式开启并等待settled，不用sleep赌时序 |
| 控制面/agent | 自身公开管理API、持久存储、实际agent和Docker执行器；fixture只能证明合同；至少实际杀进程/重启验证关键恢复窗口 |
| MCP/浏览器 | MCP session/tool真实请求；两个UI真实操作与响应；检查cookie/退出/stream/下载/浏览器secret泄露 |
| 模型 | stub标STUB；现有真实模型标EXISTING_MODEL；若改模型语义按仓库规则使用独立LLM judge；目标模型另验 |
| 云端 | 真资源/身份/网关/平台通道/模型下记录C-V案例，不能从本地结果继承PASS |

修改Python/TS执行 `./scripts/hooks/lint.sh`；按包执行pytest、类型检查、UI测试与必要build；API变化同步OpenAPI、SDK及UI代理。Python 3.11基线及支持矩阵、typed models、生产异步aiohttp、无新增BaseHTTPMiddleware/PG advisory lock等硬规则继续生效。控制面专属能力测试放其本身的suite，不强迫经Hindsight SDK调用不存在的管理接口。

每条测试receipt记录case_id、命令/cwd、开始结束、退出码、PASS/FAIL/NOT_RUN、候选/环境/config、脱敏日志路径及摘要hash。门禁无法执行就明确BLOCKED/NOT_RUN，不写“应当通过”。依赖或代码变化只使受影响结果失效，并补必要组合检查；不无理由反复跑全套。

## 8. 状态接续与失联恢复

持续主控是工作方式，不是保证聊天永不丢失或自动唤醒。工具调用中断、上下文压缩、WSL断开后，任何新会话都从 START-HERE 和状态恢复，不依赖原子agent仍存活。未启用额外常驻调度器，不能声称用户离线时工作永远自动继续。

接续步骤：

1. 读取 START-HERE → state → 当前工作包/合同/候选，核对git status、HEAD、worktree、未提交文件和运行进程。
2. 确认旧主控没有继续写同一台账；若仍在运行先协调，不启动第二主控。确认交接后递增controller_epoch，保留历史attempt和证据。
3. 调用现有agent状态工具，核对实际PID/容器、候选SHA与资源归属；失联或心跳老化不等于停止。
4. 需要替换执行者时先持久标记旧attempt为待核对/失效、禁止复用其写入与运行资源，再发送停止。取得停止及实际资源核对结果后才回收。
5. 无法证明停止时保留原worktree与资源，以新隔离位置继续无关工作；不让新agent接管旧目录或控制同一实例。
6. 保全未提交代码和日志。已有固定候选进review，未完成部分新attempt从明确base接续；迟到旧结果保留但不采纳覆盖。
7. 核对合同、候选、环境变化使哪些检查失效，重做缺失/失效部分；更新台账与下一动作后再派发。

每次派发/ACK、提交候选、review、集成、阻塞、合同变化、资源转移和结束会话都更新状态。长任务阶段切换保存增量；主控每次对用户报告前先核对台账与真实结果。进度用已集成任务数、通过案例、可演示行为、未决缺陷和剩余条件，不报没有依据的总体完成百分比。

## 9. 用户介入与参考依据

常规开发、测试、修复、独立review和本地集成连续推进。仅超出既定范围的产品取舍、未授权付费资源、凭证/宿主网络变更及最终对外发布等需要用户决定；等待只阻塞相关任务。内部协作材料由用户安排同步，不自动发送消息给其他人。

方法参考经本轮实际打开的官方文档：[独立有界任务适合多agent、共享可变状态应谨慎并行](https://developers.openai.com/api/docs/guides/responses-multi-agent)、[长期任务的外部状态与验证循环](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex)、[可接续的执行计划](https://developers.openai.com/cookbook/articles/codex_exec_plans)。上述是方法依据；本项目的槽位、工具和实际执行证据以当前会话/台账为准，不将其他API或CLI的文档当作本机已验证能力。
