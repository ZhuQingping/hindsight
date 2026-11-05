# API 参考

本参考介绍应用常用的业务接口。可以直接使用 REST，也可以通过 [Python SDK](../python.md) 或 [Node.js SDK](../nodejs.md) 调用。

| 主题 | 内容 |
| --- | --- |
| [记忆接口](memories.md) | Retain、Recall、Reflect，以及更新与标签规则 |
| [异步任务](operations.md) | 任务提交、完成条件和重复提交 |
| [文档与知识](documents.md) | 来源文档、文件写入、知识目录与页面读取 |

## 地址与认证

业务接口前缀为：

```text
/v1/default/banks/{bank_id}
```

实际地址为服务方提供的 API Endpoint 加业务路径。保留 Endpoint 中已有的服务路径前缀。

- `bank_id` 是已创建并授权的 Bank ID。
- `default` 是当前接口路径的固定部分，不替换为项目名或空间名。
- 路径参数需要 URL 编码。
- SDK 会拼接业务路径，传入 SDK 的地址不应自行追加这些路径。

请求使用业务 API Key：

```http
Authorization: Bearer <API_KEY>
```

JSON 请求还需设置 `Content-Type: application/json`。文件上传使用 `multipart/form-data`。

工作空间、用户和 Key 由管理员管理。获得全部 Bank 权限的业务 Key 仍然不是管理员，不能管理空间、用户和 Key。

## 接口一览

下列路径均相对于 Bank 前缀：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/memories` | 写入内容并提取记忆 |
| POST | `/memories/recall` | 检索相关记忆 |
| POST | `/reflect` | 基于记忆生成回答 |
| POST | `/files/retain` | 上传文件并异步处理 |
| GET | `/documents` | 分页查询文档 |
| GET | `/documents/{document_id}` | 读取文档详情 |
| GET | `/documents/{document_id}/chunks` | 分页读取分块 |
| PATCH | `/documents/{document_id}` | 更新文档标签 |
| DELETE | `/documents/{document_id}` | 删除文档及其提取的记忆和相关链接 |
| GET | `/operations/{operation_id}` | 查询异步任务 |
| GET | `/knowledge-base/tree` | 读取知识目录 |
| GET | `/knowledge-base/search` | 搜索知识页 |
| GET | `/knowledge-base/pages/{page_id}` | 读取知识页 |

示例只展示理解接口所需的字段。响应还可能包含用量、时间或来源等信息，应用应按实际字段读取，不依赖示例中的虚构 ID、文字或数量。

## SDK 参数对照

| 用途 | Python SDK | Node.js 单条调用选项 | REST JSON |
| --- | --- | --- | --- |
| 文档 ID | `document_id` | `documentId` | `items[].document_id` |
| 服务端异步写入 | `retain_async` | `async` | `async` |
| 异步请求标识 | `operation_id` | `operationId` | `operation_id` |
| 更新方式 | `update_mode` | `updateMode` | `items[].update_mode` |
| 检索内容量 | `max_tokens` | `maxTokens` | `max_tokens` |
| 标签匹配 | `tags_match` | `tagsMatch` | `tags_match` |
| 回答依据 | `include_facts` | `includeFacts` | `include.facts` |

Node.js `retainBatch` 的条目使用 `document_id`、`update_mode` 等字段，区别于单条调用选项。

## 错误处理

应用应区分三类结果：HTTP 或 SDK 调用失败、请求已提交但后台任务未完成，以及后台任务最终失败。

| 情况 | 建议处理 |
| --- | --- |
| `401` | 核对认证凭据是否缺失、无效或已失效 |
| `403` | 核对目标 Bank 及操作权限 |
| `404` 或任务 `not_found` | 核对服务地址、资源 ID 和目标 Bank |
| `409` | 按错误详情检查任务身份或资源状态冲突 |
| `422` | 按错误详情修正字段、类型或参数值 |
| `429` | 降低请求频率；如有 `Retry-After`，按提示等待 |
| `5xx` | 保留错误信息，结合操作性质决定是否重试 |
| 网络超时或连接中断 | 先判断结果是否未知，不无条件重复写入 |
| 任务 `failed` | 读取 `error_message`，处理后台执行失败 |

异步写入应提前保存任务身份，超时后先查询或复用同一 ID 重试同一请求，详见[异步任务](operations.md)。

排查时记录请求时间、SDK 版本、目标 Bank、文档或任务 ID，以及错误信息。凭据和敏感内容应先脱敏。

返回[用户指南](../../CUSTOMER-GUIDE.md)。
