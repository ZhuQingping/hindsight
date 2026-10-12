# 从这里接续单租托管开发

目标：最小改造原生 Hindsight，先在当前环境完成真实部署、授权、管控agent、管理API/页面与功能UI及测试，再接入内部专属云资源进行邀请公测。已授权按既定范围连续进行本地实现、修复、验证和有界agent协作，不再每个工作包重新请求批准。

读取顺序：[README](README.md)（产品边界）→ [development-state.json](development-state.json)（真实状态）→ [DEVELOPMENT-PLAN](DEVELOPMENT-PLAN.md)（任务）→ [AGENT-WORKFLOW](AGENT-WORKFLOW.md)（并发/恢复/质量）→ 活跃任务包及证据。

本次交付时：开发工作流已编制并进入独立审查；产品 D00—D14 尚未开始，不把规划agent的运行算成产品开发。当前源码基线为 `99f7750bfaa7dbbbc28cc644cdbd6b0c542bdb58`；integration worktree/branch/SHA 尚未创建，读state获取后续值。原生API体验进程会使用主工作区源码，产品开发必须在隔离checkout进行。

下一动作：核对旧agent与后台进程是否仍有写入，确认本地主控所有权；按D00建立专用integration和attempt工作区、精确登记资源；然后D01合同、D02启动底座/D04管理API逐步推进。当前全部真实云与产品运行验收仍NOT_RUN；旧本地health观察不改变这个状态。

主控每次交接只更新本页的简短下一动作，详细task/attempt/资源/候选/测试/review唯一记在state。缺失字段不能凭聊天记忆填PASS。大产物放主仓库 `.local/hosted-single-tenant/development/`；既有未跟踪体验/架构文档及其他项目资源不属于清理范围。

在新会话可直接使用：

> 在 /home/cimon/code/hindsight 继续单租托管开发。先读 docs/hosted-single-tenant/START-HERE.md 并核对实际状态，按 DEVELOPMENT-PLAN 和 AGENT-WORKFLOW 连续执行 READY 工作。允许有界子agent并发、常规实现/修复/测试/review及本地集成。保护现有体验环境，不将fixture算云验收，不自动远端合并或发布。先报告已恢复的状态，再继续，不重复规划整个项目。
