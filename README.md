# ContextBase

ContextBase 为 Agent 提供长期记忆服务，支持内容写入、记忆召回、推理及知识整理。
服务按工作空间组织内容，通过业务 API Key 授权 REST、MCP 和 SDK 访问。

## 从这里开始

| 任务 | 文档 |
| --- | --- |
| Claude Code、Codex 和其他 Agent 接入已有服务 | [客户使用指南](docs/contextbase/CUSTOMER-GUIDE.md) |
| 管理工作空间、用户和 API Key | [管理员操作](hindsight-extensions/contextdb-service/README.md#admin-quickstart) |
| 本地启动（Windows 原生 / Linux x86_64） | [本地启动指南](hindsight-extensions/contextdb-service/docs/deployment-local.md) |
| 部署、配置及维护服务 | [部署总览](hindsight-extensions/contextdb-service/docs/deployment.md) |
| 了解权限、生命周期和实现 | [管理功能设计](docs/contextdb-management/DESIGN.md#overview) |
| 构建和发布客户端 | [客户端发布与交付](docs/contextbase/CLIENT-PACKAGING.md) |

## 客户端

| 客户端 | 交付方式 | 使用说明 |
| --- | --- | --- |
| Coding Agents | npm：`@huaweicloud/contextbase-coding-agents` | [安装及项目绑定](docs/contextbase/CUSTOMER-GUIDE.md) |
| Node.js SDK | npm：`@huaweicloud/contextbase-client` | [Node.js SDK](hindsight-clients/typescript/README.md) |
| Python SDK | wheel / 源码包 | [Python SDK](hindsight-clients/python/README.md) |
| CLI | `contextbase` 可执行文件 | [CLI 安装器](scripts/install-contextbase.sh) |
| OpenClaw、Hermes | 各自的插件安装包 | [其他 Agent](docs/contextbase/CUSTOMER-GUIDE.md#7-其他-agent) |
| Agent Plugin、Claude Code 插件 | 对应宿主的插件归档 | [Agent Plugin](hindsight-integrations/agent-plugin/README.md)、[Claude Code](hindsight-integrations/claude-code/README.md) |

客户端连接需要服务方提供的 API Endpoint、业务 Key 和已授权的 Bank ID。
使用远端 MCP 时，单独取得完整 MCP Endpoint，不从 REST 地址推导。

Coding Agents 安装前需要对应宿主和 Node.js 18+。
安装命令、Bank 切换、更新和卸载统一见客户使用指南。
服务地址、下载地址和访问凭据分别配置；客户端发行包不携带客户凭据。

## 服务部署

API、ContextDB 扩展和管理 UI 使用同一源码版本。
首次部署完成初始化后，由管理员创建空间、用户及业务 Key，
再用业务身份完成“写入 → 确认处理完成 → Recall”验证。

本地运行 API、内置 Worker 和管理 UI，统一按[本地启动指南](hindsight-extensions/contextdb-service/docs/deployment-local.md)选择 Windows PowerShell 或 Linux Bash。
宿主进程与 Docker 使用各自的部署指南。
配置、秘密保存、更新与恢复规则见部署总览。
云平台外部条件及目标环境验证见[云环境交付待办](docs/contextbase/CLOUD-READINESS.md)。

## 开发与验证

开发约定见 [CLAUDE.md](CLAUDE.md)。
当前检查和验证边界见[验证入口](docs/contextdb-management/VALIDATION.md)；
浏览器品牌检查见[品牌审计指南](docs/contextbase/BROWSER-BRAND-AUDIT.md)。
构建与发布结果应绑定实际源码和产物，不能由历史记录推断。

## 来源与许可

项目派生自 Hindsight，来源归属与许可见 [LICENSE](LICENSE)。
