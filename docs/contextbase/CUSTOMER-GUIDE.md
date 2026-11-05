# ContextBase 用户指南

ContextBase 为 AI 应用和 Agent 提供长期记忆服务。你可以保存对话、资料和任务记录，在后续交互中找回相关信息，或基于已有记忆生成回答。

本指南面向使用已有 ContextBase 服务的开发者。开始前，请准备服务方提供的 API 地址、业务 API Key 和 Bank ID。

## 按需要阅读

| 你想做什么 | 阅读内容 |
| --- | --- |
| 了解产品用途与适用场景 | [产品介绍](user-guide/overview.md) |
| 理解 Bank、文档、记忆和知识页 | [核心概念](user-guide/concepts.md) |
| 完成第一次写入和查询 | [快速开始](user-guide/quickstart.md) |
| 跟着完整项目案例接入和维护资料 | [项目助手教程](user-guide/project-assistant.md) |
| 在控制台导入、检查、检索和整理知识 | [控制台使用](user-guide/console.md) |
| 设计对话助手或运维助手的记忆流程 | [更多应用场景](user-guide/use-cases.md) |
| 在 Python 应用中使用 | [Python SDK](user-guide/python.md) |
| 在 Node.js 应用中使用 | [Node.js SDK](user-guide/nodejs.md) |
| 接入 Claude Code、Codex、CodeArts 或远端 MCP | [Agent 与工具接入](user-guide/agents.md) |
| 查阅接口、参数和错误处理 | [API 参考](user-guide/api/README.md) |
| 排查使用中的常见问题 | [常见问题](user-guide/faq.md) |

## 三条阅读路径

- **先了解产品**：产品介绍 → 核心概念 → 更多应用场景，理解长期记忆在业务中承担的工作。
- **动手接入应用**：快速开始 → Python 或 Node.js → 项目助手教程，从首次调用走到资料维护和来源使用。
- **通过界面使用**：控制台使用 → 核心概念 → 常见问题，完成添加来源、检查记忆、验证查询和建立知识页。

已有应用可以直接查阅 API 参考。资料组织、召回结果和内容维护方式，建议结合项目助手教程一起阅读。

## 管理与部署

工作空间、用户和业务 Key 由管理员管理。业务应用取得连接信息后即可接入，无需自行部署服务。

管理员请参考[管理员操作](../../hindsight-extensions/contextdb-service/README.md#admin-quickstart)。需要本地安装时，统一使用[本地启动指南](../../hindsight-extensions/contextdb-service/docs/deployment-local.md)；正式部署与维护见[部署总览](../../hindsight-extensions/contextdb-service/docs/deployment.md)。
