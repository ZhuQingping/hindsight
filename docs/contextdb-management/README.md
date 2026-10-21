# ContextDB 工作空间、用户与 API Key

**先查[已落地优化索引（CODE-REVIEW第15章）](CODE-REVIEW.md#implemented-optimization-index)**：逐项列出SEC-01、S16～S26、质量修复N-P001～006、独立检视BR-01、已有等效修复、有意撤回及未完成项。后续先核对索引，避免把已实现问题重新分析或重复移植。

- [完整设计](DESIGN.md)：统一业务/技术规格，保留原始设计，不按专家、committer或AI拆分版本。
- [检视与优化索引](CODE-REVIEW.md#implemented-optimization-index)：第15章看当前状态，第13～14章看适配过程、团队差异及独立检视闭环。
- [最新验证（第16章四项整改；第13章完整回归）](VALIDATION.md)：目标实际命令、结果、失败历史、跳过及未验边界；旧章节保留对应日期/版本。

当前分支`feature/contextdb-management`；历史功能基线`57bbfd2d39685091ce65a4742e43c6efbcb4c78e`。原HEAD eb055aff3是适配起点，送审已快进对齐团队main `1dc0ad37e9d814826199a3bf7e07dc24fb68adbe`。本次修复整理为单个提交，提交身份以Git/PR为准；变更文件数以PR实际差异为准。SEC-01、配置别名、团队安全错误提示及管理日志在基线已有，保留不回退；不代表已合入或生产部署。

当前[U4/U5/U9/U10明确整改（第19章）](CODE-REVIEW.md#u4-u5-u9-u10-final-decision)：**四项都改，实现及列举场景已通过**，包括统一危险菜单、收敛Key详情、390×600主要动作可达和辅助图标统一；日期逻辑/公共Dialog实测正确，保留不重复改。本轮已授权amend至单一送审提交，最终提交身份以Git/PR为准；第19章与验收第16章保留提交前冻结快照及交付复核。最终UI665、双Worker生产UI2及门禁通过，Chrome有前后截图、动作坐标及短屏键盘证据。最新验收见VALIDATION第16章；此前完整回归见第13章，旧“部分/可选”判断保留为历史。

来源与阶段：

| 阶段 | 当前状态与追溯 |
| --- | --- |
| 原始管理功能与SEC-01 | 历史功能归并至当前HEAD；设计依据见DESIGN §1.4，SEC-01见§5.1.1，验收见VALIDATION第8～10章 |
| S16～S26及必要配置别名 | a05b808基准加冻结未提交补丁650ab6ac…；第13章记录适配，VALIDATION第11章记录当时验收 |
| 撤回等价重构 | eb阶段撤回等价重构；送审沿用main已有helper，两文件无PR改动，bank-selector必要接入保留；第13.4节、VALIDATION第11.5节的34文件/403项为该阶段历史 |
| 质量选择性适配 | c56c7ac17基准加独立worktree冻结补丁e2c14176…；第14章记录N-P修复和BR-01；该阶段验收见VALIDATION第12章；送审基线见第13章 |

完整SHA、实现/测试位置和有意差异集中在[第15章](CODE-REVIEW.md#implemented-optimization-index)。PLAN.md已移除，不新增平行设计或第二份优化台账；Issue #14等无关原生问题单独跟踪。两张设计图及drawio源文件继续保留。
