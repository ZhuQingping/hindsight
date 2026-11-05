# 文档与知识

文档接口管理来源内容，知识接口读取已经组织好的主题页面。本页路径均相对于 `/v1/default/banks/{bank_id}`，认证规则见 [API 参考](README.md)。

## 文档列表

**GET `/documents?limit=20&offset=0`**

| 参数 | 说明 |
| --- | --- |
| `limit` | 本次返回数量，默认 `100` |
| `offset` | 分页偏移量，默认 `0` |
| `q` | 按文档 ID 进行不区分大小写的子串匹配 |
| `time_field` | 使用 `created_at` 或 `updated_at` 进行时间筛选和排序 |
| `start_date` | ISO 时间，包含起始时间 |
| `end_date` | ISO 时间，不包含结束时间 |

响应包含 `items`、`total`、`limit` 和 `offset`。列表主要返回文档属性；需要原文时读取详情。

时间筛选按所选时间字段生效。部分历史记录如果缺少该字段，不会进入相应的筛选结果，因此列表数量不能总是作为整个 Bank 的文档总量。

## 文档详情与分块

**GET `/documents/{document_id}`**

详情包含文档 ID、创建与更新时间、标签、关联记忆数量和可用的原文。原文保存受服务配置控制，`original_text` 可能为空。

**GET `/documents/{document_id}/chunks?limit=100&offset=0`**

分页读取来源分块。`limit` 默认 `100`，范围为 `1～1000`；`offset` 从 `0` 开始。

Recall 也可以通过 `include.chunks` 请求命中记忆的相关分块，不必总是读取整份文档。

## 更新文档标签

**PATCH `/documents/{document_id}`**

```json
{
  "tags": ["project:alpha", "status:approved"]
}
```

`tags` 是完整的新标签集合，会替换已有标签；空数组清除全部标签。变化还可能触发相关观察的后续重新整理。

此接口不修改正文。更新正文应使用 [Retain](memories.md#更新已有文档)，并指定相同的 `document_id`。

## 删除文档

**DELETE `/documents/{document_id}`**

删除来源文档、从该文档提取的记忆及相关链接。此操作不可撤销，调用前应核对 Bank 和文档 ID。

## 文件写入

**POST `/files/retain`**

请求使用 `multipart/form-data`。`files` 为上传文件，`request` 为 JSON 字符串，可包含与文件对应的 `files_metadata`。

请求中的元数据部分示例：

```json
{
  "files_metadata": [
    {
      "document_id": "alpha_handbook",
      "context": "Alpha 项目手册",
      "tags": ["project:alpha"]
    }
  ]
}
```

按上传文件顺序提供对应的元数据。不要把这个 JSON 作为 `application/json` 请求直接发送到文件接口。

文件处理始终异步执行。响应示例：

```json
{
  "operation_ids": [
    "550e8400-e29b-41d4-a716-446655440000"
  ]
}
```

按[异步任务](operations.md)跟踪相关处理。支持的格式、大小上限、OCR 及其他解析能力取决于实例配置，使用服务方已开放的范围。

## 知识目录与页面

| 操作 | 接口 |
| --- | --- |
| 浏览目录 | `GET /knowledge-base/tree` |
| 搜索页面 | `GET /knowledge-base/search?q=查询内容&limit=10` |
| 读取页面 | `GET /knowledge-base/pages/{page_id}` |

知识页搜索的 `q` 必填且不能为空，`limit` 默认 `10`，范围为 `1～50`。知识接口还支持按标签限定页面范围。

知识页搜索面向已经建立的知识页，与 Recall 的记忆检索范围不同。页面的 `page_id` 与心智模型 ID 是不同标识，应使用接口返回的对应 ID。

页面内容是否更新，应结合页面的刷新配置和任务状态判断，不能仅以最近一次 Retain 成功为依据。

返回 [API 参考](README.md)。
