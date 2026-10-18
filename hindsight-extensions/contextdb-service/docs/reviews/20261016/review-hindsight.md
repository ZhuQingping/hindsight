# Hindsight 架构、扩展与原生兼容性最终独立审查

Code-edit permission: DENIED。仅本报告可写。对象：独立 worktree `contextdb-release-hardening-20261016-182619`，base `d5e851b60315b79696e995874e7edc1e9a7bae23` 加既有 dirty baseline。未部署、提交、推送、停止服务、接触现有8890/9998/5432或启动子代理。

最终结论：**ACCEPT**。两条初审阻断H-01/H-02均已关闭，未发现剩余必修项。Hindsight架构/扩展/原生兼容性领域同意当前源码与交付边界；同意与主控制器形成领域一致结论。此结论不替代真实MaaS质量或云HA验收。

## 阻断关闭证据

### H-01 / P1：独立 Worker 启动日志泄露数据库凭据——CLOSED

- 原触发：`launch.py`进入原生Worker，`hindsight-api-slim/hindsight_api/worker/main.py:295`曾直接输出config.database_url，常见userinfo密码与合法URI query password可进入Supervisor日志。
- 最终修复：Worker复用`hindsight-api-slim/hindsight_api/utils.py:56`的mask_network_location。该logging-only工具隐藏userinfo，同时移除query/fragment，保留协议、主机、端口、库名；实际连接配置不变。公共日志工具同时覆盖其他调用者。
- 初轮仅隐藏userinfo仍漏query password，审查者以asyncpg离线解析确认该变体是有效连接密码；最终修复已覆盖。
- RUN（审查者）：纯函数以三类合成哨兵复核userinfo/query/fragment均不出现在结果中，无网络/真实秘密接触。
- RUN（实现方，读取日志）：native-configuration-redaction.log，11passed；test_database_log_redaction.py包含四类合法URI回归。

### H-02 / P2：UI构建来源未校验，旧产物可随新源码启动——CLOSED

- 原触发：preflight只验证Python导入路径；UI launch只检查server.js存在；常规API/Worker启动不强制preflight。
- 最终修复：`hindsight-extensions/contextdb-service/hindsight_ext_contextdb/artifacts.py`在build-ui成功且前后源码未变化时stamp。SHA256覆盖API/扩展/UI/TS SDK源码、锁文件及配置，并独立校验standalone服务端与静态产物；排除node_modules/cache。UI launch在注入秘密和exec前强制verify_ui_build。service.sh API/Worker启动强制只读preflight。
- RUN（审查者）：实际执行`verify_ui_build(Path.cwd())`，通过；结合合成秘密检查输出`Final source/UI fingerprints match; userinfo/query/fragment credentials are redacted`。没有修改源码或产物。
- RUN（实现方，读取日志）：ui-final-stamped-build.log，正式build-ui入口重新真实构建成功并stamp；test_build_artifacts覆盖源码变化、编译块变化及构建期间源变化拒绝。
- 同版指纹用于受控交付一致性检查；不将它描述为对任意恶意修改的签名或供应链信任系统。

## 已核对的兼容与生命周期边界

- 原生算法、提示词、REST/MCP endpoint和客户端SDK未修改。原生代码最小变更为显式ENV_FILE控制及日志脱敏；unset保持原生dotenv发现，空值禁用，显式路径加载并清缓存。不存在为管理合同重写native bank_id的实现。
- tenant / validator / HTTP三槽组合启动要求与动态MCP验证仍在。MCP按每条当前消息读凭据；实际工具Bank独立选择并由验证器复核。跨schema列表适配保持原生分页返回形状。Webhook诊断投影属于明确的业务秘密边界，正常记忆响应没有新增包装。
- Admin Key与业务Key统一PG HMAC认证，role决定管理权限；protected admin被普通CRUD排除。离线初始化/导入/轮换独立于API启动，不存在运行时SHA fallback。
- workspace_id=bank_id，schema为ctxdb_ws_<UUID>；仅GET详情按归一名称查找。DELETE/授权/native bank_id继续UUID，同名新对象不会承接旧授权或旧删除重放。
- 请求持有workspace key-share，删除FOR UPDATE关闭入口；取消、连接失联与脱离HTTP生命周期的MCP工具通过持久准入/取消排空保护。queue submission在进入原生连接前取得独立元数据准入，避免引擎池饥饿死锁。
- Frozen/deleting仍被Worker发现以完成既有任务；周期维护仅枚举active；非active只有processing父任务可以提交延续。删除先看native pending/processing单快照，再查持久准入，最终DROP前再次检查两种屏障。
- 生命周期先调用原生Bank删除，再严格delete_prefix；PG文件表已删除时按存在性处理。owned schema DROP与workspace/grant删除同事务；空selected保持deny-all并递增Key版本。终态操作结果独立于workspace，默认168h；失败/未完成/有残留空间的操作不按TTL清除。
- 旧deleted墓碑升级登记同一个生命周期执行器的回收任务。未发现新增服务/权限平台或advisory lock。

## 继续保留的运行边界

下列条件阻止物理删除属于正确的fail-closed，无需为了显示成功而绕过：

1. 未知/中断request_admissions：admission.py:111与repository.py:616。停止旧执行者并取得证据前不得清理屏障；不能仅按租约或经过时间判断安全。
2. 原生任务仍pending/processing：lifecycle.py:150及repository.py:862。取消/删除任务元数据不等于证明旧执行已停止；排空须同时看任务和执行者。
3. MIGRATION_ISOLATION=true：settings拒绝，原生隔离迁移子进程目前缺可靠终止/栅栏。非隔离迁移取消等待测试不证明SIGKILL/分区下云HA。
4. 其他owner、extension或外部schema依赖：repository.py:796及:835，拒绝DROP，需部署管理员检查所有权与依赖。
5. 真实MaaS、中文检索效果、容量、HTTPS/入口限流、PGroonga恢复、备份/PITR/云HA：NOT RUN。本地stub不作为这些环境的质量/可用性验收。外部PG不强制pg0，embedded依赖仅显式--embedded检查。

## 最终验证记录

- RUN（审查者）：只读git status/diff/stat、rg、逐段源码；读AGENTS→CLAUDE、项目code-review skill、precedence/review-gate/verification-matrix、task.md及canonical设计/部署/优化状态文档。
- RUN（审查者）：纯mock/AST初审复现；asyncpg离线query-password解析；最终指纹验证与合成凭据脱敏校验，exit0。
- RUN（实现方，审查读取日志）：extension-review-fixes.log，372passed；ui-final-sweep.log，390passed；Node22/24生产build成功；native-configuration-redaction.log，11passed；root-lint-confirmed.log全通过；native OpenAPI/docs生成成功。
- RUN（实现方，审查读取日志）：system-final-verified.log，完整ContextDB系统故事61passed，298.61s。覆盖内嵌/独立Worker、REST/MCP身份、管理授权、任务/故障排空、生产UI与同名重建。初次旧fixture参数断言失败已修正并纳入最终通过。
- RUN（实现方，审查读取日志）：最后公共脱敏工具变更后，system-final-ui-worker-confirmed.log，4passed，35.05s；覆盖生产UI、内嵌/独立Worker和同名重建；最终build-ui重新stamp后审查者再次verify成功。
- NOT RUN（审查者）：根lint会自动改文件，依只读边界未自行运行；DB/系统套件沿用并核对实现方隔离运行证据，未重复启动实例；真实模型/云部署未执行。

最终领域共识：**ACCEPT，H-01/H-02 CLOSED，无剩余必修项。** 代码未由审查者修改。
