# 快速开始

本节帮助你连上已有服务，完成“写入 → 确认处理完成 → 查询”的第一次验证。

## 准备连接信息

首次接入需要取得 **API 地址、业务 API Key 和 Bank ID**。没有控制台管理权限时，请向服务管理员领取；管理员可以按下方流程准备。

### 获取 API 地址

向服务管理员或服务方取得供应用访问的 API Endpoint，包括协议、域名或 IP、端口（如有）及服务路径前缀。管理员应提供当前实例对外开放、且应用运行环境能够访问的地址。

控制台与 API 可能分开部署，不要直接把浏览器中的控制台地址作为 API 地址。使用 SDK 时，将取得的 API Endpoint 原样传入客户端，不要自行追加 `/v1/default/banks/...`。

### 获取 API Key 和 Bank ID

**应用开发者或 Agent 使用者：**

1. 告知管理员需要访问的工作空间，以及用途是查询还是写入。
2. 取得该空间的 Bank ID 和已授权的业务 API Key。首次运行本指南的写入示例，需要读写权限。
3. 按下文配置连接信息，再运行首次调用示例。业务 Key 不能用于登录控制台。

**具备控制台管理权限的管理员：**

1. 登录控制台，选择或创建工作空间，记下用于 API 调用的 Bank ID。
2. 打开“成员”，创建或选择业务成员，展开其“API Key”列表。
3. 点击“创建 API Key”，选择目标工作空间，配置只读或读写权限。
4. 创建成功后立即复制并保存完整 Key；明文只展示一次，关闭后不能从列表重新取回。
5. 将 API Endpoint、Bank ID 和业务 Key 交给使用方，并使用这把业务 Key 验证实际调用。

详细操作见[准备工作空间](console.md#1-准备工作空间与业务-key)和[查看与签发 API Key](administration.md#查看与签发-api-key)。成员归属不代替空间授权，访问范围由每把 Key 的配置决定。

### 接入信息清单

| 信息 | 用途 |
| --- | --- |
| API Endpoint | 应用调用服务的完整地址，包括服务方提供的路径前缀 |
| 业务 API Key | 调用业务接口的凭据；首次写入需要目标 Bank 的读写权限 |
| Bank ID | 本次访问的工作空间标识 |
| Python SDK 安装包 | 使用 Python 时需要的 wheel 文件 |
| MCP Endpoint | 直接连接远端 MCP 时单独取得的完整地址和相应凭据 |

API Endpoint 与 MCP Endpoint 分别配置。连接远端 MCP 时，另向服务方取得完整 MCP 地址及对应认证信息，不要通过替换 REST 路径推导。

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
