# ContextDB 首发简化验收记录

2026-10-16。本报告记录本次简化的审查与验证，不替代历史 V2 报告。基线为 d5e851b60315b79696e995874e7edc1e9a7bae23，代码分支为 contextdb/service-management-v2-simple-20261016。当前修改待用户验收，未提交或推送。原设计和部署资料保留，新入口见 [首发设计](docs/contextdb-first-release-design.md) 与 [部署验收](docs/contextdb-first-release-guide.md)。

## 用户需求与最终决策

| 要求 | 决策 |
| --- | --- |
| UI 管理工作空间 | UI 直接代理 Hindsight 扩展 API；Console 只做实例运维 |
| 用户管理页签 | 用户管理；实例级用户目录 |
| 单一后台凭据 | 一个离线运维 Admin Key；UI 密码独立，业务用户不感知 Admin Key |
| API 与字段简化 | 18 项减少至 14 项；移除 HTTP 实例注册/查询、管理员恢复、单用户详情 |
| 首发版本与未来兼容 | 首发版本 1；旧实验格式拒绝覆盖，未来版本有序增量迁移 |
| 元数据预留 | 业务实体 metadata JSONB；不预设未来权限模型，不承诺不再变更 DDL |
| 复用与少改内核 | 继续使用原生扩展点、固定 UI Key、UI 登录；保留已有必要 hook |
| 授权简单 | 用户只名称/启停；Key 全部/指定空间，只读/读写；不重复设置用户 ACL |
| 逐接口审视 | 设计有 14 接口保留原因与字段取舍表；不加入在线恢复/复杂 IAM |

## 验证状态

记录最终交付检查的真实输出。PENDING 不表示通过；系统检查以最终一次 55 条结果为准，不累加旧的 53/14/2 条分批结果。证据目录为 `.local/night-runs/contextdb-v2-simple-20261016/evidence`。

| 检查 | 状态 | 证据 |
| --- | --- | --- |
| 后端插件与公开 OpenAPI 契约 | RUN — PASS | 264 passed / 9.25s；plugin-tests-release-final.log |
| PG 元数据首发/重跑/旧格式拒绝、实例绑定 | RUN — PASS | 后端检查已包含元数据和错误实例/租户验证；插件 264 条通过。PG 专家最终审核另行记录 |
| UI 组件与代理 | RUN — PASS | 360 passed，48 files / 4.78s；ui-tests-delivery.log |
| 原生扩展回归 | RUN — PASS | 41 passed / 13.55s；native-regressions.log |
| REST/MCP、Worker 与删除排空黑盒 | RUN — PASS | 55 passed，6 warnings / 247.77s；system-tests-delivery.log；包含 production UI 与内嵌/独立 Worker 两模式。警告为旧原生文档导出接口弃用提示 |
| production UI + API（内嵌/独立 Worker 两模式） | RUN — PASS | 2 passed / 19.00s；production-ui-api-tests-delivery.log；使用临时 PG 和模型 stub |
| lint、类型、production build | RUN — PASS | root-lint-delivery.log、ui-build-delivery.log；类型检查通过 |
| 部署指南 Bash/Python 语法、相对链接 | RUN — PASS | 指南 13 个 Bash 块与本报告执行命令块通过 bash -n；配置 Python AST 通过；4 个相对链接存在；配置脚本使用虚构凭据执行，摘要/UI隔离与拒绝覆盖验证通过；操作等待函数的成功、失败、超时返回验证通过。证据：夜间 docs/docs-check.json、docs/configure-fixture-check.json、docs/wait-operation-check.json |
| 五位专家一致性 | ACCEPT | Hindsight 架构、UI、Agent Memory、PG、资料五项最终审核均已确认 ACCEPT |
| 真实 MaaS Retain→Recall→Reflect | NOT RUN | 文档提供命令，本报告尚无真实模型验收证据 |
| PG/PGroonga 崩溃、备份恢复、PITR、主备切换 | NOT RUN | 功能测试不能替代生产恢复演练 |
| 未来已发布版本升级 | NOT RUN | 目前仅有首发结构 1；有序兼容迁移是后续原则，尚无跨版本升级工具或验收 |
| Console/节点 Agent 的真实调度与 HA 升级 | NOT RUN | 本次未实现新 Agent 协议 |

## 已执行命令

以下为本次实际执行的主要命令。环境、日志和临时资源保存在夜间目录；系统测试使用 stub 模型与临时 PG，不读取旧体验实例凭据。

```bash
export CODE=/Users/zhuqingping/Work/Database/Context/.local/worktrees/contextdb-v2-simple-20261016
export NODE_BIN=/Users/zhuqingping/.npm/_npx/52027bd8fc0022aa/node_modules/node/bin/node
export PATH="$(dirname "$NODE_BIN"):$PATH"
cd "$CODE"
hindsight-extensions/contextdb-service/.venv/bin/python -m pytest \
  hindsight-extensions/contextdb-service/tests -q
PYTHONPATH=hindsight-extensions/contextdb-service .venv/bin/ty check \
  hindsight-extensions/contextdb-service/hindsight_ext_contextdb
.venv/bin/python -m pytest \
  hindsight-api-slim/tests/test_extension_context.py \
  hindsight-api-slim/tests/test_mcp_extension.py \
  hindsight-api-slim/tests/test_mcp_routing.py \
  hindsight-api-slim/tests/test_mcp_tool_filtering.py \
  hindsight-api-slim/tests/test_worker_main.py -q
./scripts/hooks/lint.sh
TZ=UTC npm test -w @vectorize-io/hindsight-control-plane
npm run build -w @vectorize-io/hindsight-control-plane
cd "$CODE/hindsight-system-tests"
CONTEXTDB_TEST_NODE_BIN="$NODE_BIN" .venv/bin/python -m pytest \
  tests/test_10[0-9]_contextdb*.py tests/test_11[0-2]_contextdb*.py -q --tb=short
```

Node 路径是这次验收所使用的本机 Node 22；其他机器按部署指南准备自己的 Node 22.12+/24 LTS。报告命令与执行日志属于验收证据，不作为交付机器固定路径要求。

## 审核中已修正的问题

- 归档导出/下载可能携带 Webhook 运维凭据，统一限定为 Admin；业务读取保留记忆、文档、知识与授权 trace。
- Worker 与 API 一样校验数据库的实例/租户绑定，避免配置错误后跨实例处理；已有错误实例/租户用例。
- ContextDB UI 修正 Next Intl 内部语言路径导致的登录重定向循环，真实 production UI 代理与双 Worker 测试通过。
- 工作空间异步轮询有截止时间；失败和超时停止后续步骤，重试继续查询原任务，不更换幂等标识重复提交。

## 验收边界

本次改动使用隔离 worktree 与临时测试资源，不改变已有体验库、服务、凭据。原生内容算法与请求响应结构继续复用；安全删除所需准入、租约、任务排空、墓碑和未知执行者保护不能为了减少接口而删除。

相较基线，ContextDB 运行时 Python 净减少 201 行，原生内核 hook 无新增修改；原 V2 部署、配置和验收文档内容保留。统计与文件范围见 evidence/scope.json。这是代码范围结果，不是性能提升结论。

实际上线前应固定交付版本和依赖，使用独立 UTF8 库与非超级用户服务账号，配置私网/TLS，完成真实模型、灾备和容量验收。PGroonga 是可选中文后端，没有已确认的生产默认全文插件。

## 资料专家审核

**ACCEPT（资料范围）**。已逐项对照合入后的 CLI、Settings、输入模型、HTTP 路由与 schema：离线 generate-admin-key、元数据版本 1 + format_id、14 项管理 API、用户无 ACL、Key 范围与只读/读写、UI 固定服务端 Key 的说明一致。设计保留逐 API 原因、字段取舍、关键决策与原始文档入口；同库架构图、8 张元数据表字段、共享 UI 审计身份和归档运维例外均与当前 SQL/代码事实一致。

本结论只接受设计事实与文档可读性、命令语法/配置逻辑，不宣称已经按手册部署真实 MaaS 或完成生产灾备，也不代替其余专家的最终代码审核。最新 55 条黑盒系统检查已通过；五位专家最终结论已收齐且一致。此结论覆盖本次设计、代码与隔离功能验收，不扩大到表中 NOT RUN 的生产验证。
