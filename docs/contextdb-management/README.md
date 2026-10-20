# ContextDB 工作空间、用户与 API Key

[DESIGN.md](DESIGN.md)是统一的完整设计：以原始设计为底稿保留完整业务和技术叙述，直接补充团队分支适配、实现限制及待解决问题。专家、committer、开发者和AI均使用这份设计，不维护按读者拆分的版本。

- [完整设计](DESIGN.md)：总体架构、部署、UI、业务接入、认证、生命周期、PG、API和Q&A。
- [代码走读与检视记录](CODE-REVIEW.md)：实现位置、团队适配、已修复/开放发现及代码测试映射。
- [验证记录](VALIDATION.md)：实际命令与结果、失败/跳过、已知门禁及未验收范围。

团队基线 `57bbfd2d39685091ce65a4742e43c6efbcb4c78e`，最新来源功能 `a05b80885883b36f879abdb2ce8a9c8f63b0922c`；集成分支为 `feature/contextdb-management`，以amend整理为一个功能提交，最新实现及资料随同提交。原始设计来源及证据适用范围见DESIGN第1.4节；两张图及drawio源文件随文档保留。

本分支尚待独立检视；SEC-01已在自研transport内统一过滤，原生运行代码保持不变，见DESIGN第5.1.1节，Issue #14文档生成失败独立跟踪。第5.5节说明最新实现与测试组织，a05验收见VALIDATION第8章，首次amend检查见第9章，最新插件修复验证见第10章。PLAN.md已移除，设计不按读者角色拆分。
