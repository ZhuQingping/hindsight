# PostgreSQL 独立复核报告

- Task: ContextDB 首发优化落地后的 PostgreSQL 约束、迁移、删除与并发评审
- Role: PostgreSQL DBA / 内核评审
- Agent type: 独立只读评审；Code-edit permission: **DENIED**。仅写本报告，未修改代码或操作原体验 PG/API/UI。
- Status: **PASS — ACCEPT WITH RISKS**
- Base commit: `d5e851b60315b79696e995874e7edc1e9a7bae23`，连同 `baseline.patch` 与 `baseline-status.txt` 保留的原 dirty 基线。
- Worktree: `/Users/zhuqingping/Work/Database/Context/.local/worktrees/contextdb-release-hardening-20261016-182619`
- Scope: `schema.sql`、`migrations.py`、`legacy_schema_v*.sql`/受信任 catalog、`repository.py`、`bootstrap.py`、`lifecycle.py`、相关 PG 测试及当前设计/部署文档。

## Critical

无。

## Important

**当前无未关闭阻断。以下两项由本评审发现，主执行者修复，已独立复查。**

1. **已关闭：外部依赖检查晚于原生破坏操作。**
   - 原触发条件：外部表使用 `ON DELETE CASCADE` 外键引用空间内 Bank/记忆表。原 `lifecycle.py:173` 先执行已独立提交的 `delete_bank`，直到最终 metadata 事务才拒绝外部依赖；外部数据可能已经被级联删除，最终事务回滚无法恢复。
   - 修复：`repository.py:796` 的 `verify_workspace_schema` 同时检查所有权与外部依赖，`lifecycle.py:100` 在任何原生清理前调用；`repository.py:863` 的最终删除事务仍复查。未知所有权、扩展归属、外部依赖均拒绝。
   - 证据：`tests/test_release_hardening.py:188` 经真实 Lifecycle 执行器和真实 PG 外部 CASCADE FK 验证，Bank 原生调用及文件删除均未开始，内外两边数据保留。新增专项日志 3 passed，最终扩展集 372 passed。

2. **已关闭：迁移未识别被禁用的完整性触发器。**
   - 原触发条件：v2 上 `ALTER TABLE ... DISABLE TRIGGER keys_authorization_integrity`。`pg_get_triggerdef` 不反映 `tgenabled`，原签名比较仍通过，升级会保留禁用状态。
   - 修复：`migrations.py:93` 在 DDL 前显式拒绝非正常启用状态 `tgenabled<>'O'`，没有借升级静默修复定制 catalog。
   - 证据：`tests/test_bootstrap_deployment.py:150` 验证升级拒绝且版本仍为2、原触发器状态不变；纳入上述最终回归。

## Minor

1. **已关闭：用延迟触发器替代操作 FK 后的直接 SQL 并发缺口。** `schema.sql:243` 已在非终态操作的父存在检查中加入 `FOR KEY SHARE`，避免事务 A 校验父存在、事务 B 删除父并提交、事务 A 再提交孤儿操作。`tests/test_release_hardening.py:213` 覆盖 `SET CONSTRAINTS ALL IMMEDIATE` 后并发删除被阻塞并最终拒绝，专项通过。

2. **已关闭：Key 编辑与最终删除锁序交叉。** `repository.py:821` 的 `complete_operation` 复用部署行锁，先于 operation/workspace/Key 锁；与成员/Key 管理串行化，关闭“Key 更新验证 active 后暂停、最终删除锁 workspace 等 Key、Key 插 grant 再等 workspace”的死锁窗口。此项以代码锁序复查为证据；未另外重复构造调度测试。

3. **接受的部署边界：在线越权 SQL DDL 不受服务生命周期协议保护。** `repository.py:814` 的依赖检查和 `DROP SCHEMA ... CASCADE` 分属语句，不能宣称能够阻止有权访问服务表的其他 SQL 会话在检查后并发创建跨 schema 依赖。必要边界是客户 SQL 账号不得访问/引用 `ctxdb_meta`、`ctxdb_ws_*`，不绕服务执行在线 DDL；主执行者已明确该场景不受支持并负责同步部署说明。该边界不影响已授权服务 API 路径，本轮不要求扩建 DDL 协调平台。

4. **文案小项：** 审查时 `schema.sql:130` 的 COMMENT 仍写“当前2”，`:173` 写“永久幂等结果”，应与结构3和有界168小时历史统一。仅数据库注释，非运行阻断。

## 一致性结论

- 管理员/业务 Key 经同一 PG HMAC 认证；管理员仅离线初始化/轮换，普通成员和 Key CRUD 不暴露或修改它；没有运行时 SHA 回退。
- NFKC/trim/casefold 成员名由部分唯一索引兜底，active/disabled 共同占名；并发冲突映射409；删除后新身份不继承旧 Key。
- 元数据升级为离线单事务1→2→3/2→3；未知 catalog、绑定错误、规范化冲突先拒绝，原生 schema 不随元数据升级改写。保留业务摘要、表 OID、授权与 installed_at；重复初始化校验原凭据/pepper。
- 删除先排空原生任务及持久准入，再清理原生资源和独立 UUID schema，最后事务性删除授权及空间行；关联 Key 版本递增，空 selected 拒绝全部。UUID 不复用，旧删除重放不会命中同名新空间。
- 终态操作独立保留，默认168小时且配置限制24～8760小时；pending/running、仍有空间的可恢复失败与未知准入不按 TTL 清理。
- GET 详情仅按规范化名称精确查询；DELETE、授权、原生 bank_id/schema 仍用 UUID，未落实早期全面可读寻址候选。

## Commands / verification evidence

以下均为本评审 **RUN** 的只读操作：

- `cat AGENTS.md CLAUDE.md .claude/skills/code-review/SKILL.md`，并读取工作流 precedence/review-gate/verification-matrix/report-template 及 `task.md`；exit 0。
- `git status --short`、`git diff --stat d5e851b60315b79696e995874e7edc1e9a7bae23`、`git log --oneline -3`；exit 0；基线及未提交实现分别保留。
- `nl -ba` / `sed` / `rg` 逐段复核上述目标文件、原生 `MemoryEngine.delete_bank` 提交顺序及相关测试；exit 0。
- `cat extension-review-fixes.log pg-review-regressions.log extension-ty-final.log`；exit 0。

测试由主执行者 **RUN**，本评审独立读取日志，不冒称本评审重跑：

| 证据 | 最终结果 |
| --- | --- |
| `extension-review-fixes.log` | **372 passed**, 2 warnings, 24.51s |
| `pg-review-regressions.log` | **3 passed**, 2 warnings, 3.79s |
| `extension-ty-final.log` | All checks passed |
| `deployment-physical-cleanup-sweep.log`（修正前已有专项） | 58 passed, 2 warnings |

本评审测试命令 **NOT RUN**：没有重复启动测试或连接任何外部 PG；现有测试使用专属 pg0 临时实例及随机端口。未将早期失败日志作为最终结果。构建、UI 和系统故事的完整验收由相应评审/主执行者负责。

## 剩余风险、下一步与裁决

云 PG 版本差异、客户权限实际配置、插件灾备/恢复、容量和 HA 不能由本机 pg0 测试代替。数据库所有者或超级用户绕过生命周期写 metadata/执行 DDL，也不属于服务 API 的安全保证。

**PG 领域已达成一致：无剩余 Critical / Important，裁决 ACCEPT WITH RISKS。** 风险为上述已明确排除的直接 SQL 并发 DDL 边界；主执行者同步部署说明即可。无需回退 dirty 基线，无需新增架构。本报告不授权部署、提交或推送。

## 追加静态复核：旧 deleted 墓碑清理的恢复入口

主执行者后续提出此边界；本评审再次只读检查 `migrations.py:256`、`repository.py:673`、`:943`、`:979`，未执行测试、未操作数据库。

现代码确实存在一个兼容清理限制：升级为旧 deleted 空间安排 `schema-cleanup-v3-<UUID>` 操作；三次失败后空间保持 deleted/version不变，普通 DELETE 重试在 `_workspace` 被404拒绝，`_restart_operation` 也仅接纳 failed 空间。解除外部依赖后不会自动重新排队，重复执行v3迁移亦不会重排。失败操作及空间行仍保留，不会被终态TTL误清理，故这不是数据安全阻断。

**作为明确的离线运维边界可以接受**：只对旧 deleted 兼容清理，由原数据库所有者在停写、核对旧执行者后受控重排；文档应明确“处理故障再受控恢复”并非普通 DELETE 重试。若本轮承诺该场景也走原管理API恢复，则建议落实主执行者提出的窄重排，不新增接口。

窄重排的最小安全条件：

- 保留原 Admin/部署校验并遵循管理全局锁序；锁定原workspace和原operation，操作仍为failed。
- 限原delete操作，`target_id=workspace_id`，原幂等Key精确为 `schema-cleanup-v3-<UUID>`、request_hash为UUID的SHA256；不接受新Key新建清理任务或旧create。
- 原空间仍为deleted且schema严格绑定UUID，workspace.version **等于**原operation.workspace_version（兼容任务没有普通failed路径的+1）；同UUID无其他pending/running操作。
- 仅重置同一operation为pending，清理其attempts/lease/error，保留workspace的deleted、name/name_key、schema、version及operation.workspace_version；同名active后继不参与该路径。
- 不清理持久准入、不跳过原生任务排空、所有权或外部依赖检查。继续经同一Lifecycle执行器。

如实施，应验证“同名active后继存在、旧清理三败、解除依赖、原DELETE/原Key重排、仅旧UUID清除”，以及错Key/版本变化/旧create拒绝和并发重放不另建操作。在当前372项回归之外，此补充仅为静态分析，不声称新增实现或测试已完成。
