# 快速开始

本节帮助你连上已有服务，完成“写入 → 确认处理完成 → 查询”的第一次验证。

## 准备连接信息

向服务管理员取得以下信息：

| 信息 | 用途 |
| --- | --- |
| API Endpoint | 应用调用服务的完整地址，包括服务方提供的路径前缀 |
| 业务 API Key | 调用业务接口的凭据；首次写入需要目标 Bank 的读写权限 |
| Bank ID | 本次访问的工作空间标识 |
| Python SDK 安装包 | 使用 Python 时需要的 wheel 文件 |
| MCP Endpoint | 直接连接远端 MCP 时单独取得的完整地址和相应凭据 |

API Endpoint 与 MCP Endpoint 分别配置。不要通过替换 REST 路径推导 MCP 地址。

使用 SDK 时，将 API Endpoint 原样传入客户端，不要自行追加 `/v1/default/banks/...`。

## 权限与控制台

| 凭据或权限 | 用途 |
| --- | --- |
| 控制台登录凭据 | 管理员登录管理界面 |
| 只读业务 Key | Recall、Reflect，以及允许的记忆、文档和知识内容读取 |
| 读写业务 Key | 只读能力，加写入及允许的内容修改、删除 |
| 管理员 Key | 工作空间、用户、Key 等受控管理操作 |

业务应用使用业务 Key，不使用管理员 Key。业务 Key 不能作为控制台登录密码。

Reflect 可以由只读 Key 调用，但仍会调用模型，并可能产生用量和日志记录。“只读”描述的是业务内容权限。

## 配置示例环境变量

本指南的 Python 和 Node.js 示例从环境变量中读取地址、凭据和 Bank。也可以在自己的应用配置中保存这些值，再传给 SDK。

Linux 或 macOS：

```bash
export CONTEXTBASE_API_URL='https://你的服务地址'
export CONTEXTBASE_API_TOKEN='你的业务API-Key'
export CONTEXTBASE_BANK_ID='project_alpha'
```

Windows PowerShell：

```powershell
$env:CONTEXTBASE_API_URL = 'https://你的服务地址'
$env:CONTEXTBASE_API_TOKEN = '你的业务API-Key'
$env:CONTEXTBASE_BANK_ID = 'project_alpha'
```

示例中的 `project_alpha` 需要替换为已经创建并授权的 Bank。

## 运行第一份示例

选择对应语言：

- [Python SDK](python.md)：安装 wheel，运行完整的写入、检索和回答示例。
- [Node.js SDK](nodejs.md)：安装 npm 包，运行同一场景的 JavaScript 示例。

两份示例都写入一段项目说明，并固定使用 `alpha_project_overview` 作为文档 ID。重复执行会按替换方式更新这份来源。

验证时重点看三个结果：

1. 写入成功。同步调用等待主要处理完成；异步调用需要继续查询任务。
2. Recall 能返回与项目数据库及变更要求相关的记忆。
3. Reflect 能围绕这些记忆组织回答，并按请求提供依据。

记忆数量和生成文字受内容、模型及服务配置影响，不必与示例文字逐字一致。

## 继续接入

自己的应用可以在任务或会话的合适节点写入内容，并在需要背景时调用 Recall 或 Reflect。已有编程工具可以使用[Agent 与工具接入](agents.md)。

首次验证通过后，可以沿两条路径继续：

- [项目助手完整案例](project-assistant.md)：保存多份来源，组织检索上下文，使用回答依据，并完成资料更新和清理。
- [控制台使用](console.md)：查看同一 Bank 中的原文、分块和记忆，建立第一张知识页。

实际接入前，先确定文档 ID 的分配、当前版本的更新方式和 Bank 授权范围。示例中的固定名称只用于演示，不应直接套用到所有项目或用户。

遇到问题先检查服务地址、目标 Bank、Key 权限和任务状态，再参考[常见问题](faq.md)。
