# agentstratum 客户端发行合同

2026-10-15：按 Issue #2 的 D1–D9 及“只发行客户端”补充确认实施。候选构建不等于公开发布或生产验收。

## 发行清单

| 组件 | 对外标识 | 候选产物 | 连接配置 |
| --- | --- | --- | --- |
| Rust CLI | 命令 `agentstratum` | `agentstratum-linux-amd64`、`agentstratum-linux-arm64`、`agentstratum-darwin-amd64`、`agentstratum-darwin-arm64` | API Endpoint；保留 Profile |
| Coding Agents | npm 包/命令 `agentstratum-coding-agents` | `agentstratum-coding-agents/<版本>/agentstratum-coding-agents-<版本>.tgz` | `~/.agentstratum/coding-agent.json`；单默认连接 |
| 标准 Agent Plugin | manifest 名 `agentstratum` | `agentstratum-agent-plugin/<版本>/agentstratum-agent-plugin-<版本>.zip` | 完整 MCP Endpoint + 凭证；单默认连接 |
| Claude Code | manifest 名 `agentstratum-memory` | `agentstratum-claude-code/<版本>/agentstratum-claude-code-<版本>.zip` | `~/.agentstratum/claude-code.json`；单默认连接 |

品牌统一为 `agentstratum`，组件后缀区分产物。当前各组件使用自己的 manifest/Cargo 版本；尚未占用公共 npm scope，也不声称这些版本已经公开发行。

API/worker 包及镜像、本地引擎、Web 控制台安装包、SDK、Helm Chart 不进入本轮客户发行。保留服务端和内部开发源码；托管服务的构建部署另行管理。

## 当前代码行为

- CLI 无默认 localhost；未配置地址时提示 API Endpoint、`configure`、Profile 或环境变量。删除自动下载安装本地 Web 的 `ui` 命令。
- CLI `configure` 更换地址时不沿用旧地址的已存凭证；具名 Profile 保留各自的连接。
- Coding Agents 安装在缺少地址时停止注册，拒绝 `daemon`。Hook、原生工具、本地 MCP 适配器共享顶层连接；`harnesses`、`paths`、`banks` 不能覆盖地址和凭证，记忆行为设置仍可覆盖。
- Claude Code Hook 和本地 MCP 适配器只连接显式 API Endpoint；SessionEnd 只做写回。客户运行路径不再输出旧的弃用/自动迁移提示。手动 Hook 安装幂等，卸载保留其他插件的 Hook。
- 标准 Agent Plugin 直接使用完整 MCP Endpoint。它提供 Skills + MCP，不包含生命周期 Hook；其 README 记录的宿主限制仍需真实宿主复核。
- 安装包不内置租户地址和凭证。API Endpoint 与 MCP Endpoint 分开配置，不从其中一个猜测另一个。

## 构建与安装

`.github/workflows/release.yml` 改为手动构建四类客户端候选，不执行公开上传。旧 `v*` / `integrations/**` 标签不再触发原来的 PyPI、npm、服务端镜像或本地引擎发布。

插件归档通过 `scripts/package-client-plugins.py --output <目录>` 生成；先构建 Coding Agents。Claude Code 归档排除本地引擎管理模块、测试和缓存。npm 包不含 `daemon-start.js`。各插件版本目录生成 `SHA256SUMS`，归档包含许可证。CLI 构建另附许可证及第三方许可证清单。

实际域名未定前，安装说明使用文件路径，不提供虚构的生产下载地址：

1. 从已批准渠道取得对应平台 CLI 文件并核对校验和，将其以 `agentstratum` 文件名安装到 PATH；再配置自己的 API Endpoint 和 Profile。
2. Coding Agents：`npm install -g ./agentstratum-coding-agents-<版本>.tgz`，配置地址和凭证后运行 `agentstratum-coding-agents install <宿主>`。
3. 标准 Agent Plugin：解压并通过支持 Agent Plugin 的宿主加载，填写控制台给出的 MCP Endpoint 和凭证。
4. Claude Code：解压后通过宿主加载插件目录，配置 API Endpoint 和凭证；避免与 Coding Agents 重复安装同一宿主的 Hook。

以上不构成一键安装脚本或公开下载的全新机器验收。Claude Code 的 Python MCP 依赖仍需包索引访问；Coding Agents 的候选包依赖已打入运行时，自动更新渠道未配置时不查询 registry。

## 控制台交接合同（待实现）

由每个客户的服务部署配置提供明确的 API Endpoint 与完整 MCP Endpoint；不要使用控制台代理的内部 API 地址，也不要拼接猜测 `/mcp`。控制台按当前登录客户展示这两个地址、凭证获取/轮换说明，以及 CLI Profile、Coding Agents、Agent Plugin、Claude Code 配置示例。

服务端内部凭证不能返回浏览器；客户凭证应通过既定发放流程提供。此文档定义交接要求，当前提交尚未增加控制台配置接口或页面。页面由专业 Web 团队负责，接口仍在 Issue #2 范围内。

## 验证与剩余门槛

本次本地验证：Rust CLI 116 项单元测试及 3 项进程测试；Coding Agents 1,326 项通过、6 项跳过，ESM/DTS 构建通过；Claude Code 222 项通过。两套插件连接测试使用两个独立 HTTP 端口检查请求目标、Bearer 凭证及 401；这些是隔离协议测试，不代替真实服务/宿主验收。另已从实际归档验证：Claude Code MCP initialize/tools/list/tools/call；Coding Agents tarball 经 npm 安装后执行 Codex 注册、重复注册和卸载；标准 Agent Plugin 清单、地址占位符及许可证。最终配置改动后的 Coding Agents 定向复跑为 298 项通过、2 项跳过。

仓库总 lint 脚本在 `uv sync --frozen` 阶段受当前局部检出缺少根 `pyproject.toml` 阻塞；改动文件的格式和 Python lint 单独检查。GitHub 多平台候选构建尚未执行，不能把 Linux 本地通过当作全平台通过。

未完成：

- 华为云公开下载渠道、区域、桶/仓库、域名、对象路径、访问策略和发布身份配置。
- npm tarball 公开下载方案是否作为正式安装方式；若要求按包名 `npx`，需另行确定 registry、版本发现和更新方式。
- 独立 CLI 一键安装脚本、校验机制接入公开渠道及全新机器首次安装验收。
- 控制台接入信息接口与页面交接实现。
- 三类插件真实宿主全新安装、认证、工具调用、Hook、卸载验收及兼容限制复核。
- 数据库环境下原 Issue 的 API/MCP/原 SDK、异步任务/Webhook、监控/tracing 系统回归，以及完整仓库 lint、CI 和独立 review。

上述未完成项继续保留在 Issue #2；未合并、未公开发布。
