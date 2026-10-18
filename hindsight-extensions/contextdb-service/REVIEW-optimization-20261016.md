# ContextDB 用户、API 与 PG 优化验收

日期：2026-10-16。按 contextdb-optimization-backlog.md 第 2、4、6 节实施。

## 交付

工作树：`/Users/zhuqingping/Work/Database/Context/.local/worktrees/contextdb-opt-main-20261016-131006`。

独立分支：`contextdb/optimization-20261016-131006`。基于 `d5e851b60315b79696e995874e7edc1e9a7bae23` 加原首发简化工作树已有未提交实现；本次改动也尚未提交。原工作树完整保留，不能只凭 HEAD 认为包含新代码。

| 模块 | 结果 |
| --- | --- |
| 用户管理 | 成员行展开 Key、更多菜单、新成员定位；脱敏和时间；吊销移除；停用提示；一次明文展示与复制 |
| Key 授权 | 一个 authorization 对象；selected 逐空间权限，all 统一权限且含未来空间；创建默认读写、编辑不隐式增权 |
| API | 14 路由保留；仅改名、明确授权替换、If-Match、统一Header/错误、可恢复的空间操作 |
| 敏感读取 | 业务原始任务载荷拒绝；Webhook 任务回显/错误诊断在 REST/MCP 同步投影；含运维凭据的审计归管理员 |
| PG | 合并单行部署信息、移除重复列、关联授权、约束及完整 COMMENT；保留租约、准入、管理锁和历史职责 |
| 升级 | 首发结构1→2离线事务迁移；严格catalog预检、原子拒绝漂移、保留OID/ACL/数据；API仍v1 |
| 原生侵入 | 相对本轮输入工作树没有新增原生内核修改；复用既有扩展和原生内容接口 |

入口：[部署与使用](docs/contextdb-optimized-guide.md)、[14 接口 curl 手册](docs/contextdb-optimized-curl-guide.md)、[生成的 OpenAPI](docs/contextdb-control-plane.openapi.yaml)。原始首发/V2文档保留，不用旧三字段请求调用优化版。

## 验证结果

使用 Python 3.11.15、Node 22.23.3、隔离临时 PG、模型 stub。测试不读取原体验实例凭据，不连接其 5432 库。表中的套件数不累计重复定向批次。

| 检查 | 执行结果 | 证据 |
| --- | --- | --- |
| 扩展完整套件 | PASS：352 passed | extension-tests-final.log |
| 元数据升级/约束/COMMENT最终定向 | PASS：28 passed；属于上项覆盖，不额外累计 | metadata-upgrade-final.log |
| UI 完整套件 | PASS：383 passed，49 files | ui-tests-final.log；TZ=UTC |
| 原生扩展/Worker定向回归 | PASS：41 passed | native-regressions.log |
| REST/MCP/Worker/生产UI完整黑盒 | PASS：59 passed，内嵌与独立Worker；包含生产UI代理 | system-tests-final.log |
| 新混合权限与敏感诊断黑盒 | PASS：4 passed；内嵌/独立Worker，属于完整黑盒覆盖 | new-system-tests.log |
| 根 lint | PASS | root-lint.log |
| 扩展 Ruff、格式、Ty及OpenAPI一致性 | PASS | 定向执行记录；生成器 --check |
| TypeScript client与生产UI构建 | PASS | typescript-client-build.log、ui-build.log |
| 新手册命令语法、JSON和本地链接 | PASS：20个Bash块、3个JSON示例、12个链接 | docs-check.json；未执行手册写入用例 |
| 原工作树保护、额外原生改动检查 | PASS | state.json、task-changed-files.json；最终范围检查 |

完整运行日志位于：`/Users/zhuqingping/Work/Database/Context/.local/night-runs/contextdb-optimization-20261016-131006`。日志和工作树不等于已经提交或推送。

## 四专家检视

| 专家 | 最终意见 | 审核重点 |
| --- | --- | --- |
| Hindsight | ACCEPT | 原生扩展接缝、目标权限、任务/删除、诊断投影、文档合同；无新增must-fix |
| PG | ACCEPT | 关闭catalog漂移阻断；单行绑定、约束、迁移、锁/租约及数据保留 |
| Agent | ACCEPT | 当前MCP消息身份、发现与执行、双通道投影、Worker已接受任务语义 |
| Web Server | ACCEPT | 关闭明确失败意图残留；固定代理、会话/Origin、Header/错误、压缩和响应边界 |

四位均独立只读审核，没有操作真实环境，也没有将主控测试称作自己执行。摘要保存在日志目录的 hindsight-review.md、pg-review.md、agent-review.md、web-server-review.md。

审核和自测中关闭的问题：

1. **旧库漂移**：原先只比列名，缺失digest CHECK也可能升级。现在完整比较正版v1目录签名，任何类型、NOT NULL、默认值、约束或索引漂移在破坏性DDL前拒绝。
2. **MCP二次过滤**：原生在扩展中间件退出后再次过滤，可能得到空工具列表。使用当前HTTP scope承接发现意图，工具调用清除标记并按当前Bearer/目标空间重验，不修改原生代码。
3. **诊断旁路**：只禁止原始payload还不够，Webhook回显和审计也可能含凭据；补齐REST/MCP诊断投影和审计门禁，普通Retain状态保持。
4. **结果未知误报**：首次明确400/409拒绝不再永久保留pending intent，网络/5xx/以前未知请求仍保留；没有为了清空提示自动重试写请求。
5. **清理测试接缝**：离线初始化切换为有序迁移后，原fixture故障注入点也同步到迁移入口；PG stop、连接close和禁止启动server断言全部保留。

## 可重复的主要命令

在优化工作树执行，临时 PG 由测试fixture管理，不运行现有部署的迁移：

```bash
export CODE=$(pwd)
export PYTHONPATH="$CODE/hindsight-extensions/contextdb-service:$CODE/hindsight-api-slim:$CODE/hindsight-system-tests:$CODE/hindsight-clients/python"
export PATH='/Users/zhuqingping/.npm/_npx/52027bd8fc0022aa/node_modules/node/bin:'"$PATH"

.venv/bin/python -m pytest hindsight-extensions/contextdb-service/tests -q --tb=short
TZ=UTC npm test -w @vectorize-io/hindsight-control-plane
npm run build -w @vectorize-io/hindsight-control-plane

CONTEXTDB_UI_SERVER="$CODE/hindsight-control-plane/standalone/server.js" \
CONTEXTDB_TEST_NODE_BIN=$(command -v node) \
.venv/bin/python -m pytest hindsight-system-tests/tests/test_10[0-9]_contextdb*.py \
  hindsight-system-tests/tests/test_11[0-4]_contextdb*.py -q --tb=short

.venv/bin/python -m pytest hindsight-api-slim/tests/test_extension_context.py \
  hindsight-api-slim/tests/test_mcp_extension.py hindsight-api-slim/tests/test_mcp_routing.py \
  hindsight-api-slim/tests/test_mcp_tool_filtering.py hindsight-api-slim/tests/test_worker_main.py -q
./scripts/hooks/lint.sh
.venv/bin/python hindsight-extensions/contextdb-service/scripts/generate_openapi.py --check
```

Node绝对路径为本机验收工具位置，其他机器使用受支持的Node版本。日志中的原生导出/websockets/SWIG弃用提示不是本次用例跳过；没有用skip/xfail掩盖新缺陷。

## 边界

- 原体验服务及数据库没有升级或替换；新代码需要按部署手册另行部署。内部结构2不表示API改为v2。
- 114用fixture SQL构造合成的原生Webhook任务及凭据/回显/error，再通过真实SDK/MCP查询；没有验证真实外部Webhook投递全过程。
- 本次不验证真实MaaS质量、生产容量/公网HTTPS与限流、PG/PGroonga crash/PITR/主备、云节点Agent HA。
- P2性能候选仍待测量：重复远程Admin检查、使用时间节流、目录批量读取和候选索引；不宣称性能提升，不缓存跨请求权限。
- 管理写入使用READ COMMITTED与部署行锁，不支持客户绕过服务直接写授权元数据；同库不能阻止真实PG超级用户或OS root。
- Webhook投影按当前原生任务类型及已知字段实现；上游增加诊断字段或敏感任务类型时需同步回归，不承诺通用JSON脱敏。
- 未提交、推送、合并或外部发布。原实现及原始设计保留。
