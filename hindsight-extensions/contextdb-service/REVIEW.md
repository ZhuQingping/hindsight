# ContextDB V2：实现范围与检视记录

日期：2026-10-15。上游基线 `a77c1f3412a7b82f36588dffce1a8d7480e99cc7`；分支 `contextdb/service-management-v2`。

完整 V2 与 V1 采用同一上游基线，各自一个功能提交，V1 `cdfc199e5` 保持不变。此前 V2 开发树基于 V1，整理时完整复制已验证的源码和测试；运行时文件与体验版本逐文件校验一致。文档、版本入口和随版管理合同在代码仓维护，合同测试读取本仓 YAML，不再依赖兄弟研究目录。

## 本版本行为

- 用户与空间同属实例，唯一不可变管理员；普通用户有 all/selected 空间上限。
- 每个普通 Key 使用逐空间 grants/scopes；不自动扩展到未来空间，原 secret 可修改授权。管理员 all Key 覆盖全部及未来空间。
- 同空间内容共享，空间保持独立 schema 和唯一 Bank；客户端不指定 schema。
- Console 管空间生命周期，管理员 all 管用户/Key；普通用户无子 Key 或自助管理。
- UI 独立共享口令和固定服务端 admin/all Key，ContextDB 模式中英文展示 Workspace/工作空间；API/SDK 字段保持原生名称。
- metadata 版本 2，新库开通；拒绝 v1/未标版本表结构，不做隐式迁移。

## 哪些代码是原生侵入？

以下路径相对 `hindsight-api-slim/hindsight_api/`。共 **9 个运行时文件，211 行新增、20 行删除**；不把测试或锁文件行数计入原生侵入量。

| 文件 | 增/删 | 修改及主要检视点 |
|---|---:|---|
| [api/__init__.py](../../hindsight-api-slim/hindsight_api/api/__init__.py) | +6/-1 | 将可选扩展中间件放在 MCP 分发层外，覆盖 REST/MCP；检查挂载顺序与双重安装 |
| [api/http.py](../../hindsight-api-slim/hindsight_api/api/http.py) | +5/-0 | 安装或暂缓安装扩展中间件；原生接口路径和字段不变 |
| [api/mcp.py](../../hindsight-api-slim/hindsight_api/api/mcp.py) | +104/-0 | 每条 HTTP 消息恢复真实认证身份和准入上下文，避免沿用会话首把 Key；SDK/会话兼容性是重点 |
| [engine/memory_engine.py](../../hindsight-api-slim/hindsight_api/engine/memory_engine.py) | +24/-4 | 传递知识读取来源、支持内部多状态任务查询、入队前进入准入保护；检查授权与删除/入队竞态 |
| [extensions/http.py](../../hindsight-api-slim/hindsight_api/extensions/http.py) | +11/-0 | 增加可选纯 ASGI 中间件 hook，默认空列表 |
| [extensions/tenant.py](../../hindsight-api-slim/hindsight_api/extensions/tenant.py) | +14/-0 | 增加入队作用域 hook，默认 no-op；避免拿着原生连接等待空间锁 |
| [extensions/operation_validator.py](../../hindsight-api-slim/hindsight_api/extensions/operation_validator.py) | +4/-0 | mental model 读取上下文增加服务端来源，区分知识页面和原始模型；不是客户自报授权字段 |
| [mcp_tools.py](../../hindsight-api-slim/hindsight_api/mcp_tools.py) | +41/-15 | 区分预期权限拒绝与未知异常；错误被包装成成功协议响应时仍报告清理屏障，不转交异常/正文 |
| [worker/main.py](../../hindsight-api-slim/hindsight_api/worker/main.py) | +2/-0 | 关闭引擎前执行租户扩展关闭 hook；需要关注其他自定义扩展的关闭行为 |

**不是所有补丁都默认 no-op。** 空中间件和入队 hook 是可选默认行为；MCP 身份恢复和 Worker 关闭流程修改了共享执行路径，须依靠兼容回归。部署必须使用带补丁的宿主，不能只复制插件到任意社区版本。

未修改向量检索、事实提取或反思算法，也未修改原生记忆表/Alembic 迁移。新增 `ctxdb_meta` 的 8 张表及实例用户/Key 管理是我们实现的逻辑，不是上游现成的用户管理能力。

## 验证依据

整理前的完整 V2 已通过：扩展 242 项、ContextDB 系统故事 100–110 共 49 项、原生定向回归 41 项、真实 UI/隔离 PG 两种 Worker 模式 2 项。UI 术语更新后 UTC 全套 343 项、生产 Next 构建和根 lint 通过；本机真实 UI 登录、中英文页面、用户页、MySQL/PG 列表及静态资源通过。

上述结果来自此前同一运行时快照，整理分支不重复累加次数。此次整理在新分支独立复核：扩展 242 项通过，无跳过；包含随版 OpenAPI 合同及 PG 角色边界测试。UI UTC 343 项、根 lint、扩展 Ruff/format/ty 均通过。提交前检查运行时代码与体验快照一致、文档语法/链接、凭据及 diff whitespace。远程 CI、真实云管控/RDS、容量和恢复不据本地结果宣称通过。

## 提交范围与生产边界

包括自研扩展、PG 元信息和角色边界模板、100–110 系统故事、管理员 UI/文案、9 个宿主 hook、CI 接入、测试锁文件和部署文档。扩展 uv.lock 仍按既有策略忽略；CI 首次 uv sync 生成，后续 frozen；ty 固定为宿主使用的 0.0.84。

不包含真实凭据、运行配置、日志、数据库目录、verification/ 或构建产物。当前本机服务使用原体验目录，整理不重启 API/UI/PG。

需另验：云管控身份/来源/TLS、RDS 特权角色、并发迁移 fencing、未知执行者人工恢复、备份恢复、HA 和容量。共享 UI 口令不能审计到不同个人；已受理 Worker 作业不会因 Key 撤销而回滚。真正 PG SUPERUSER/OS root 不能靠同库 ACL/RLS 隔离。

当前本机 SQL_ASCII 与空 preload 只适合基本体验；UTF8、SQL 统计和 PGroonga 恢复配置及故障测试见 [PG 插件手册](docs/postgresql-extensions.md)。

对比命令见 [版本说明](docs/version-comparison.md)，操作步骤见 [部署手册](docs/contextdb-v2-deployment-usage-guide.md)。
