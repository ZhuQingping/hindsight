# 冲突与语义处理

固定输入见 PLAN.md；对象预演得到 20 个冲突路径。以下记录包含预演冲突及
自动合并后测试发现的交点，不能把清除标记等同于通过验收。

| 路径/组 | 两方意图与合成结果 |
|---|---|
| `hindsight-api-slim/hindsight_api/api/http.py` | 上游存储拒绝须返回 503/Retry-After；我方错误分类与内部 traceback 保留。Reflect 的 tool failure 先检查存储拒绝，再走我方公开错误边界。 |
| `hindsight-cli/src/errors.rs` | 保留客户 ID 不按品牌过滤的回归，同时接收上游无效响应体诊断。 |
| `hindsight-clients/rust/src/lib.rs` | 接收上游 UA 增加 SDK 版本的行为；SDK 保持原生身份，不与显示名绑定。保留 ContextdbName 校验测试和上游同名 enum 解码回归。 |
| `hindsight-clients/go/api/openapi.yaml`、`go/client.go` | 合成后 OpenAPI/生成器重新生成，包含本方 product-config 接口和 1.0.0 版本。 |
| `hindsight-all-npm/package.json`、`hindsight-embed/pyproject.toml` | 升级版本至 1.0.0，保留本方名称/描述与用途。 |
| Coding Agents `package.json`、`plugin.json` | 升级集成版本至 0.8.1，保留固定包/插件身份、private 与远程模式；不恢复上游本地引擎运行依赖。 |
| 根及 Coding Agents `package-lock.json` | 以合成 manifests 经 npm lock-only 生成，再用 npm ci 安装验证。 |
| Coding Agents `core/auto-update.ts` | Windows 安全 spawnNpm + 我方显式发行包配置；无包配置时仍不自动切回上游发行。 |
| Coding Agents `core/hindsight.ts` | 保留必填 API URL，接收带明确 signal 时放开 undici 默认超时的上游修复。 |
| Coding Agents `core/host-client.ts` | 新增 project 上下文，保留 RemoteConnectionError 时 disabled/告警退出，避免阻断宿主启动。 |
| Coding Agents `core/retain-hook.ts` | 使用上游可选 client 分支，使关闭 retain 时仍记录本地 usage；写回前只校验远程连接，不启动 daemon。 |
| Coding Agents `core/runtime.ts` | 保留 AGENTSTRATUM 反递归变量；usage 不被 retain 开关抑制；远程写回 Promise 加入 inFlight，供上游 flush 在退出前等待。 |
| Coding Agents `core/session-start.ts` | 保留显示名和现有 readFileSync 导入，接收上游 survey/reflect gating。 |
| Coding Agents `README.md`、`skill/SKILL.md`、docs `coding-agents.md` | 将 Grok PostToolUse、pageRefreshEveryTurns、autoInject、本地 usage 的上游变化写入品牌模板，再生成 README、skill、docs。 |

## 自动合并后回归发现

首轮 Coding Agents：8 fail、1406 pass、6 skipped。新增上游测试使用原始
HINDSIGHT 环境变量、注入标记或默认连接，未与我方兼容合同衔接。
仅对实际测试夹具中的诊断/usage/Opencode 环境变量、Grok 标记和远程 endpoint
做定点适配；不改客户内容、不全局替换协议。flush 测试显式提供远程 URL，
以真正验证在途写回的等待与超时，而不是先被远程配置门拒绝。

上游 bundled daemon 的依赖包文本校验不适用于本方不发行 daemon 的包：
改为验证运行依赖/命令中不恢复本地引擎；Windows spawn 的行为测试由已有
`hindsight-all-npm/src/server.test.ts` 执行。原代码正则会在 `this.buildEnv()`
提前截断，不能作为 spawn 参数的可靠证明。

## 非冲突审查重点

- SDK 自动生成文件保留 prepare-client-spec 的 non-null array 修正；Rust
  build.rs 同时保留原 nullable/string 处理并加入上游 enum title 去重。
- 检查 API `_internal_error`、retain/recall/reflect 的状态码/公开错误边界。
- 检查 remote-only 的入口、发行身份和上游新增后台/退出行为的组合。
- Alembic 无增量；不修改现有数据库、不将既有运行证据当成本轮结果。

测试和最终证据见 RESULT.md；此处是决策记录，不是通过声明。

## 验证期间补充

- API 新增测试的 Claude MCP 工具前缀和 Cursor 临时目录前缀适配我方现有身份，
  保留 trace 内容和 cwd/config 隔离断言；两个受影响文件的 26 项定向测试通过。
- CI lockfile 检查此前拒绝私有 Coding Agents 的本地开发 helper。本轮将例外
  精确限定到该 private 包、既有 devDependency、固定路径、lock 的 dev 标记且
  不在运行/可选依赖中；公开包、运行依赖和非 dev 目标仍拒绝，使用临时仓库夹具验证。
- docs-skill 按实际 CI 生成链重新生成，消除本方源文档与派生参考的旧差异。
  品牌模板恢复明确标注为 Upstream changelog 的历史来源链接；不变更产品运行身份。
- 首次扩大 Python/Go SDK 测试选择误包含默认 localhost:8888 的服务测试；该次
  环境失败保留。修正 package asyncio 配置、单元测试选择后通过；真实 API 链路
  另由 owned fixture 的 SDK stories 和 CLI 验收提供，不把缺少服务算成功。
- 语义审查发现上游 Windows npm shell 路径原本假设固定包名，而我方包名来自
  配置。增加 registry package name 校验，拒绝 URL、命令选项、shell 表达式，
  并覆盖拒绝前不 lookup/spawn 的回归。保留 OBS/CDN 分发默认不启用自动更新。
- 上游新增 Coding Agents User-Agent 由我方实际 package name/version 派生，
  用本地真实 HTTP 请求验证，避免把 fork 流量误标为官方同名客户端。
