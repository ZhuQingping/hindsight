# ContextBase 用户指南

ContextBase 为 AI 应用和 Agent 提供长期记忆服务。你可以保存对话、资料和任务记录，在后续交互中找回相关信息，或基于已有记忆生成回答。

本指南面向使用已有 ContextBase 服务的开发者。开始前，请准备服务方提供的 API 地址、业务 API Key 和 Bank ID。

## 按需要阅读

| 你想做什么 | 阅读内容 |
| --- | --- |
| 了解产品用途与适用场景 | [产品介绍](user-guide/overview.md) |
| 理解 Bank、文档、记忆和知识页 | [核心概念](user-guide/concepts.md) |
| 完成第一次写入和查询 | [快速开始](user-guide/quickstart.md) |
| 在 Python 应用中使用 | [Python SDK](user-guide/python.md) |
| 在 Node.js 应用中使用 | [Node.js SDK](user-guide/nodejs.md) |
| 接入 Claude Code、Codex、CodeArts 或远端 MCP | [Agent 与工具接入](user-guide/agents.md) |
| 查阅接口、参数和错误处理 | [API 参考](user-guide/api/README.md) |
| 排查使用中的常见问题 | [常见问题](user-guide/faq.md) |

第一次使用，建议从产品介绍和快速开始读起，再选择对应的接入方式。已有应用可以直接阅读 SDK 指南或 API 参考。

## 管理与部署

工作空间、用户和业务 Key 由管理员管理。业务应用取得连接信息后即可接入，无需自行部署服务。

管理员请参考[管理员操作](../../hindsight-extensions/contextdb-service/README.md#admin-quickstart)。需要本地安装时，统一使用[本地启动指南](../../hindsight-extensions/contextdb-service/docs/deployment-local.md)；正式部署与维护见[部署总览](../../hindsight-extensions/contextdb-service/docs/deployment.md)。
