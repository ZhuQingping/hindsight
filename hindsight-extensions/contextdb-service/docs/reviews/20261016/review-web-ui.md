# Web/API 与 UI 独立复核

Code-edit permission: **DENIED**。仅写本报告；没有修改源码、运行现有 8890/9998 服务或连接 5432 PG，没有部署、提交、推送或派生代理。

评审对象：独立 worktree `contextdb-release-hardening-20261016-182619`，基线为 `d5e851b60315b79696e995874e7edc1e9a7bae23` 加原 dirty 优化补丁。已读 AGENTS.md、CLAUDE.md、项目 code-review 技能、工作流 precedence/review-gate/verification-matrix 和本次 task.md。评审采用最后确认的“GET 名称查询，DELETE/授权/native bank_id 保留 UUID”方案。

## Critical

无。

## Important

无。该领域没有发现阻断首发的实现或合同缺陷。

## Minor

无剩余项。原两项 Minor 已只读复核关闭：

1. `hindsight-extensions/contextdb-service/docs/contextdb-release-design.md:323` 已改为 `metadata_version=3`；`:325` 已明确 users.role 为 admin/member、无用户级空间授权。Research 当前首发设计副本同样修正。
2. `hindsight-extensions/contextdb-service/docs/contextdb-optimized-curl-guide.md:718` 已明确用户/Key 编辑响应含 ETag，空间只读详情不发 ETag；Research 当前 curl 手册一致。设计第251行也已明确 Key 编辑快照排除 last_used_at，列表另含该统计。

补充文档复核：托管密码来源统一为 ui-secrets.json 的 password，修改后重启 UI；原生 REST SDK 正向步骤、`/mcp/{workspace_id}/` 单空间入口和 `/mcp/` 显式 bank_id 多空间入口与 UUID 身份边界一致。本次文档范围没有剩余阻断或 Minor。

## 已核对的关键边界

- UI 密码必须独立于后台 Admin Key；浏览器请求不能选择上游 URL、替换共享凭据；管理路由自行校验会话、同源和实时管理员身份。middleware 跳过管理代理的重复身份远程探测，不跳过会话和同源检查。原生 UI 数据请求继续验证身份，生命周期写入继续封闭。
- `/admin/identity` 调用与扩展路由一致；启动仅重试网络/5xx/429，凭据错误、角色错误和畸形 JSON 立即停止。运行期间没有复用启动授权结果。
- Unicode 名称按单路径段编码并由服务端统一规范化；名称详情和不可复用 UUID 写入边界一致。授权读取的 workspace_name 不参与授权快照或写入；UI 通过名称查详情后核对 UUID，不选择同名后继对象。
- 成员、Key 和空间目录均分页；用户切换及搜索时通过 AbortController 丢弃过期返回，workspace 加载通过 generation 丢弃旧返回。Key 编辑使用旧快照 version，412 不自动覆盖；只改名不发送 authorization，空 selected 可显示且不强迫恢复权限。
- 正常空间行无常驻进度按钮；目录 pending 状态通过有界 GET 刷新。恢复只自动读取已知 operation_id；未知写必须明确点击并复用原请求/幂等标识，24小时过期后不发送写请求。失败和中止保留恢复意图，浏览器停止等待不取消后台操作。
- 单个 Key 创建/编辑响应与列表投影区分 last_used_at；列表无编辑 ETag。UI 从列表获得 version 进行编辑，没有依赖创建/编辑返回 last_used_at。
- Next 配置改为 mjs、系统字体路径不含构建时远程下载；已核对产物构建日志。扩展 OpenAPI 的路径、分页、授权输入/输出与 UI 调用一致，现有合同测试比较生成路径和字段。
- 补充只读检查了新增 artifacts.py 与 launch.py：build-ui 在成功构建且源树未变化后保存来源/产物指纹，UI launch 启动前强制核对；核对失败拒绝启动。实际加戳构建日志已成功。新的轮询测试在挂载前启用 fakeTimers，未改变实际轮询代码。

## 验证记录

- **RUN（本次评审）**：`git status --short`、`git diff --stat -- hindsight-control-plane`、对重点源码/测试/合同/文档的 `cat` / `sed` / `rg` 只读检查；结果如上，没有发现代码阻断。
- **RUN（读取已有执行证据，非本评审重复运行）**：检查 `ui-final-sweep.log`，49 个文件 / 390 个测试通过；主控制器说明该次使用 TZ=UTC。检查 `ui-build-node22.log`、`ui-build-node24.log`，均完成 Next 生产构建及 standalone 打包；检查 `root-lint.log`，All lints passed。
- **RUN（收尾复核，读取已有执行证据）**：检查 `ui-stamped-build.log`，生产构建、standalone 打包和 `Matching ContextDB UI artifact built and stamped` 均完成；检查已完成的 `ui-final-confirmed.log`，49 个文件 / 390 个测试通过。只读对照源码文档与 ContextDB-Research 当前设计/部署/curl 手册，原两项 Minor 均关闭。
- **NOT RUN（本次评审）**：不重复全量 UI 测试、生产构建或真实浏览器部署；不启动 API/PG、不访问现有体验服务。已有验证足以覆盖本次只读复核；本报告不将静态审查描述成真实浏览器端到端验收。
- **RECOMMENDED**：本领域无需追加修复或验证；发布环境真实浏览器/入口验收仍依主控制器整体交付边界执行，本报告未将其标成已运行。

**ACCEPT**。Web/API 与 UI 领域实现与已确认方案一致，Critical=0、Important=0、剩余 Minor=0；文档问题已关闭。
