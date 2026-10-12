# 单任务派发、交付与审查模板

本模板须实例化；占位未填不能派发。正式小型记录收录在 `evidence/<task>/<attempt>/`，大产物在主仓库 `.local/hosted-single-tenant/development/runs/<task>/<attempt>/`。

## 派发

- task_id / attempt_id / controller_epoch / agent_id：
- 用户可观察的目标与明确不包含内容：
- baseline SHA / branch / worktree绝对路径：
- 合同revision与依赖candidate、消费方ACK：
- 独占write_scope（实际路径）；禁止写入范围：
- resources（namespace、端口、DB/bucket引用、heavy-runtime持有人）：
- required_cases、实际测试名与命令/cwd、通过结果：
- 允许的操作、资源限制、何时报告阻塞：
- 第一次START_ACK内容：已读规范、目标理解、base/合同/路径/资源确认。
- DISPATCHING已落盘的位置；ACK前仅只读核对，主控持久化ACTIVE并明确许可后才实施。
- executor_kind（SUBAGENT/CONTROLLER）、reconciliation_required、最后实际执行身份及中断核对方法：

## 作者交付

- base_sha / candidate_sha / tree_sha / diff文件列表：
- 合同/依赖、配置/迁移revision、锁文件hash、制品digest（不适用说明）：
- 已实现行为、关键取舍、变化范围：
- 测试receipt：case、环境种类、命令、退出码、结果、日志路径/hash：
- 未决缺陷、失败/未运行项、内部条件：
- 运行进程/资源状态与安全停止方法：
- 下一步可执行动作与复现步骤：

## 独立review

- reviewer及非作者资格；审查base/candidate/tree：
- 必须检查的安全、状态、失败窗口、兼容与缺失测试：
- findings：严重度、文件/行、反例、影响、回归要求、处置：
- 实际执行的命令及结果；是否lint产生diff：
- PASS / CHANGES_REQUESTED / BLOCKED，不宣称未运行检查通过：

## 主控收录

- 结果执行身份与当前attempt是否一致；迟到结果处置：
- 集成SHA、冲突处理及其review、受影响验证：
- 任务状态、各质量轴结果、资源释放证据：
- 若换人/新会话：旧执行者停止或隔离证据、新attempt起点：
