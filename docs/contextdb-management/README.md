# ContextDB 工作空间、用户与 API Key

首次使用从[插件 README](../../hindsight-extensions/contextdb-service/README.md)选择业务接入或管理员操作；运营者直接阅读[同版本部署指南](../../hindsight-extensions/contextdb-service/docs/deployment.md)。开发者阅读[唯一 DESIGN](DESIGN.md#overview)，接口以[同版 OpenAPI](../../hindsight-extensions/contextdb-service/schemas/contextdb-control-plane.openapi.yaml)为准。

[文档任务导航](../../hindsight-extensions/contextdb-service/docs/README.md) · [完整检视记录](CODE-REVIEW.md) · [完整验收证据](VALIDATION.md)

[ContextDB Service Extension CI](../../hindsight-extensions/contextdb-service/README.md#contextdb-service-extension-ci)：插件Python、UI、合同、系统及浏览器回归；原有工作流保持不变。验收见[第35章](VALIDATION.md#contextdb-ci-validation)。

下面保留交付与检视记录的原始日期、版本和进展，不要求使用者辨认这些提交后才能开始操作。

<details>
<summary>交付、检视与历史版本记录</summary>

PR #65的CI测试依赖及100条授权用例稳定性修复已在本地验证，见[检视第30.5节](CODE-REVIEW.md#bank-rest-ci-test-review)、[验收第34章](VALIDATION.md#bank-rest-ci-test-validation)；修复随功能提交一并交付，远程结果以PR检查为准。

> Issue #53 当前实现：[完整设计第8章](DESIGN.md#bank-api-reuse-design) · [检视第30章](CODE-REVIEW.md#bank-rest-completion-review) · [最新main组合验收第33章](VALIDATION.md#bank-rest-rebase-validation)。已rebase至团队main `9a58a706e`，UI源码使用 `contextbase-control-plane`；当前交付提交以Git/PR记录为准；第33章保留amend前基准`8a394a246`及冻结验收。两个UI创建入口和描述继续保留；旧workspace写接口退役，只读视图保留，MCP管理仅在插件模式下关闭。第31～32章及PR #57记录保留各自版本，不代表当前组合验收。

召回统计提供记忆和知识页的次数及最后召回时间。默认关闭，通过 `CONTEXTDB_RECALL_USAGE_ENABLED=true` 启用；usage读取沿用空间及内容读取权限，已授权只读/读写业务Key可读，UI仍为管理员登录。召回统计已由[PR #54](https://github.com/RSIXDB/hindsight/pull/54)合入；Bank REST复用范围见上述专项章节。

- [配置、旧实例升级与最小使用示例](../../hindsight-extensions/contextdb-service/README.md#召回使用统计issue-38)。
- [完整设计第7章](DESIGN.md#7-记忆与知识召回统计)：口径、采集、权限、异步写入、生命周期和性能边界。
- [记忆/知识页截图](VALIDATION.md#202-chrome实际验证)、[开关截图](VALIDATION.md#222-关键合同与chrome)。
- [完整检视](CODE-REVIEW.md#26-pr-54-完整独立检视与文档修正2026-10-29)、[验收](VALIDATION.md)：第26章为完整候选回归，第27章为内部检索排除补证；旧章节仅代表各自日期/版本。

以下为此前管理功能和维护修复的历史资料；其中“最新”仅指该历史阶段，当前结果以上方第33章及其版本边界为准。

当前维护修复（2026-10-27）基于main `fe96754356f4ee46d6413852d76b9562f7dc890c`，修复分支`codex/fix-contextdb-31-32-integration`；提交身份以同版Git/PR为准。Issue #31的MCP配置作用域、Issue #32的共享维护函数初始化均在插件内修复。走读[设计第5.5.4节](DESIGN.md)、[检视第20章](CODE-REVIEW.md)、[验证记录（第17章独立目录、第18章本地集成目录）](VALIDATION.md)。下列送审信息为原管理功能历史。

**先查[已落地优化索引（CODE-REVIEW第15章）](CODE-REVIEW.md#implemented-optimization-index)**：逐项列出SEC-01、S16～S26、质量修复N-P001～006、独立检视BR-01、已有等效修复、有意撤回及未完成项。后续先核对索引，避免把已实现问题重新分析或重复移植。

- [完整设计](DESIGN.md)：统一业务/技术规格，保留原始设计，不按专家、committer或AI拆分版本。
- [检视与优化索引](CODE-REVIEW.md#implemented-optimization-index)：第15章看当前状态，第13～14章看适配过程、团队差异及独立检视闭环。
- [管理功能历史验证（第16章四项整改；第13章完整回归）](VALIDATION.md)：目标实际命令、结果、失败历史、跳过及未验边界；旧章节保留对应日期/版本。

历史管理功能分支`feature/contextdb-management`；历史功能基线`57bbfd2d39685091ce65a4742e43c6efbcb4c78e`。原HEAD eb055aff3是适配起点，送审已快进对齐团队main `1dc0ad37e9d814826199a3bf7e07dc24fb68adbe`。本次修复整理为单个提交，提交身份以Git/PR为准；变更文件数以PR实际差异为准。SEC-01、配置别名、团队安全错误提示及管理日志在基线已有，保留不回退；不代表已合入或生产部署。

当前[U4/U5/U9/U10明确整改（第19章）](CODE-REVIEW.md#u4-u5-u9-u10-final-decision)：**四项都改，实现及列举场景已通过**，包括统一危险菜单、收敛Key详情、390×600主要动作可达和辅助图标统一；日期逻辑/公共Dialog实测正确，保留不重复改。本轮已授权amend至单一送审提交，最终提交身份以Git/PR为准；第19章与验收第16章保留提交前冻结快照及交付复核。最终UI665、双Worker生产UI2及门禁通过，Chrome有前后截图、动作坐标及短屏键盘证据。该阶段验收见VALIDATION第16章；此前完整回归见第13章，旧“部分/可选”判断保留为历史。

来源与阶段：

| 阶段 | 当前状态与追溯 |
| --- | --- |
| 原始管理功能与SEC-01 | 历史功能归并至当前HEAD；设计依据见DESIGN §1.4，SEC-01见§5.1.1，验收见VALIDATION第8～10章 |
| S16～S26及必要配置别名 | a05b808基准加冻结未提交补丁650ab6ac…；第13章记录适配，VALIDATION第11章记录当时验收 |
| 撤回等价重构 | eb阶段撤回等价重构；送审沿用main已有helper，两文件无PR改动，bank-selector必要接入保留；第13.4节、VALIDATION第11.5节的34文件/403项为该阶段历史 |
| 质量选择性适配 | c56c7ac17基准加独立worktree冻结补丁e2c14176…；第14章记录N-P修复和BR-01；该阶段验收见VALIDATION第12章；送审基线见第13章 |

完整SHA、实现/测试位置和有意差异集中在[第15章](CODE-REVIEW.md#implemented-optimization-index)。PLAN.md已移除，不新增平行设计或第二份优化台账；Issue #14等无关原生问题单独跟踪。两张设计图及drawio源文件继续保留。

</details>
