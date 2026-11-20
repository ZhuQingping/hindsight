# 归档发布检视记录

2026-11-20。范围：把首版、BEAM P3 以及当前性能阶段的 PG C、ContextBase 适配、文档和脱敏证据集中到 `memory-benchmark`。依用户当前指令发布实验结果；不表示生产发布或剩余测试通过。

## Findings

**Critical：** 本次检查未发现新增阻止实验归档的缺陷。核对了 `recall_arrays.sql` 与当前 `recall_rank_json.sql` 差异：评分函数替换、最终 JSON 构造与 chunk 键排序；原检索 SQL、候选、RRF、Top-K 和预算保持原契约。无 PG core 改动，无新增 HTTP/SDK 参数。

**Important：** 当前真实 BGE 只完成 3/20；最终 v2 未重跑整轮性能/BGE；完整业务鉴权、多租户、并发写入、附件和 SDK 黑盒发布覆盖未完成。新函数需要受信服务端模板和最小权限角色，不能作为公开 SQL API。仅可归档为实验版，不能据此切换正式服务。

**Minor：** 全仓 lint 仍被既有 `hindsight_api/api/http.py:5886` 的 F841 阻塞。无关格式化被排除；相关文件 Ruff/格式通过，运行时适配和新客户端 ty 通过；verifier 扩大 ty 检查时有既有动态父类 `unsupported-base` 警告。当前阶段 20 题里 3 题平均退化，且平均/P50 的 20% 阶段目标未达成，首页和后续计划已明确。

## Verification

- 阅读并按 `.claude/skills/code-review/SKILL.md` 检查调用边界、租户/Bank、错误/取消、字段类型、未使用代码和文档；当前显式选择器继承同一组守卫，原查询回退不规范化同分顺序。
- 三个 PG C 模块用目标 PG 18.4 的 PGXS 编译成功；不提交 `.o` / 动态库。
- 新 `native/install.sql` 在专用 PG 55440 中新建的空数据库执行成功，随后 72 个评分字节比较通过，临时数据库已删除。没有在 LoCoMo 或源 Bank 执行安装。
- 相关测试组 39 项通过；另一次误纳入需要 embedded PG 的时间窗口测试在环境启动时中断，未将其写成通过。时间请求仍有独立冻结库两题差分证据。
- 新公开 `measure_http.py`：三个临时独立 API、六次响应与历史原始回包哈希一致；仅功能冒烟，不用于新增性能结论。只关闭了本次创建的进程。
- 重新执行全仓 `scripts/hooks/lint.sh`，失败为上述既有 F841；相关文件的 Ruff / format 通过，运行时适配和新外部客户端 ty 通过；verifier 的动态 `RecordingStore(parent)` 有既有 ty `unsupported-base` 警告，未说成全目标 ty 绿色。
- 当前首页、设计、手册、交接及计划的相对链接检查通过；扫描全部待发布文件，未发现已知凭据、带密码 DSN、模型/快照或编译产物。
- 原始阶段证据保留时间、分支和未提交字段；没有用归档状态改写旧测量。实际源码与新增工具清单见 [publication-validation.json](publication-validation.json)。

## Recommendation

**ACCEPT WITH RISKS：允许按用户指令归档源码、报告和证据；等待人工与剩余测试，不自动启用生产。**

代码基线：远程 `18be05bde`，首版整合 `b682cd693`，BEAM P3 `4016fed9b`；首版原始 `05d2894c5` 保护分支未动。提交推送正常 fast-forward，不强推，不覆盖主工作区其他改动。后续工作以 [plan.md](plan.md) 为准。
