# 从这里接续单租托管开发

目标：最小改造原生 Hindsight，先在当前环境完成真实部署、授权、管控agent、管理API/页面与功能UI及测试，再接入内部专属云资源进行邀请公测。已授权按既定范围连续进行本地实现、修复、验证和有界agent协作，不再每个工作包重新请求批准。

读取顺序：[README](README.md)（产品边界）→ [development-state.json](development-state.json)（真实状态）→ [DEVELOPMENT-PLAN](DEVELOPMENT-PLAN.md)（任务）→ [AGENT-WORKFLOW](AGENT-WORKFLOW.md)（并发/恢复/质量）→ 活跃任务包及证据。

当前计划已按[外部审查和Cloud研究](REVIEW-ADOPTION-AND-CLOUD-IMPACT-20261012.md)修订，最新候选及审查状态以state为准。历史planning-v3通过记录保留在[旧审查记录](evidence/planning/REVIEW.md)，不覆盖本次新内容。产品D00—D14尚未开始，不把规划agent的运行算成产品开发。源码基线仍为 `99f7750bfaa7dbbbc28cc644cdbd6b0c542bdb58`；integration worktree/branch/SHA尚未创建。原生API体验进程使用主工作区源码，产品开发必须在隔离checkout进行。

最新静态复核：[planning-v5审查记录](evidence/planning/REVIEW-v5.md)，最终候选 `e5d97ccf85cd4c5f9f33d668157e9424d7b4fdbb`。R01—R14有明确采纳落点，Cloud反例进入N06—N11；强派生撤回与全批取消未自行新增为产品保证。

用户本轮要求先分析两份其他会话材料，本轮不启动产品实现。后续开发下一动作仍为：核对旧agent/进程写入和主控所有权，D00隔离与资源登记→D01合同→D02/D04并行；D07先审计、D06后落授权；C02按模块接口和平台样例就绪逐项适配，不等整个D14/C01。全部真实云与产品运行验收仍NOT_RUN；旧health或Cloud归档观察不能改写本地状态。

主控每次交接只更新本页的简短下一动作，详细task/attempt/资源/候选/测试/review唯一记在state。缺失字段不能凭聊天记忆填PASS。大产物放主仓库 `.local/hosted-single-tenant/development/`；既有未跟踪体验/架构文档及其他项目资源不属于清理范围。

在新会话可直接使用：

> 在 /home/cimon/code/hindsight 继续单租托管开发。先读 docs/hosted-single-tenant/START-HERE.md 并核对实际状态，按 DEVELOPMENT-PLAN 和 AGENT-WORKFLOW 连续执行 READY 工作。允许有界子agent并发、常规实现/修复/测试/review及本地集成。保护现有体验环境，不将fixture算云验收，不自动远端合并或发布。先报告已恢复的状态，再继续，不重复规划整个项目。
