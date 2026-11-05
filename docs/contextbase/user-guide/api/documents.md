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

### 怎样选择维护方式

| 需求 | 方式 |
| --- | --- |
| 修改当前规范、偏好等完整来源 | 相同 ID 的 Retain，`update_mode=replace` |
| 为已有来源追加内容 | 明确使用 `append`，接受拼接后重新处理 |
| 新增一次独立事件或决策 | 新文档 ID，保留时间和背景 |
| 只调整文档标签 | PATCH 文档标签 |
| 纠正一条提取错误或作废事实 | 在控制台操作相应的世界事实或经历 |
| 按当前配置重新提取来源 | 在控制台重新处理文档，并跟踪任务 |

如果原文有误，应先维护原文。单独修改提取结果不代表来源已被改正，之后重新处理仍可能提取出旧内容。

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

## 创建知识页

### 创建文件夹

**POST `/knowledge-base/folders`**

```json
{
  "name": "项目手册"
}
```

成功创建返回 `201`，例如：

```json
{
  "id": "knowledge_folder_example",
  "kind": "folder",
  "name": "项目手册",
  "parent_id": null
}
```

保存实际返回的节点 `id`。需要创建子文件夹时，传入 `parent_id`。本页 ID 仅用于示意，请使用实际响应中的标识。

### 创建主题页面

**POST `/knowledge-base/pages`**

```json
{
  "name": "数据库变更规范",
  "source_query": "整理 Alpha 项目的数据库版本、变更评审与发布验证要求。",
  "parent_id": "knowledge_folder_example",
  "tags": ["project:alpha"]
}
```

`name` 和 `source_query` 必填。`parent_id` 可省略，表示放在根目录。示例中的父级 ID 需要替换为实际创建的文件夹 ID。

成功创建返回 `201`，例如：

```json
{
  "page_id": "knowledge_page_example",
  "mental_model_id": "topic_model_example",
  "operation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

保存 `page_id` 用于读取页面，保存 `mental_model_id` 用于对应的心智模型操作。若返回 `operation_id`，按任务接口跟踪生成；该字段也可能为空。

创建成功表示页面对象已建立，不能据此认定正文已经生成。继续读取页面并确认相应生成状态。

`source_query` 是生成时回答的主题问题。`tags` 限定生成资料范围，默认要求记忆包含全部指定标签，并排除无标签内容。省略标签时从整个 Bank 读取。

例如，已有记忆只有 `project:alpha`，页面再添加未在来源中使用的 `type:handbook`，默认会导致范围没有匹配资料。目录分类使用文件夹，标签范围使用实际存在的来源标签。

### 更新页面选项

**PATCH `/knowledge-base/nodes/{node_id}`**

可以按需提交名称、父级目录、源查询、标签或刷新配置。只提交需要改变的字段；标签字段用于替换页面范围，空数组清除标签限制。

知识页的 `page_id` 同时也是该页面的目录节点 ID，更新页面节点时将它传入 `node_id`；更新文件夹时使用文件夹返回的 `id`。`mental_model_id` 则用于对应的心智模型操作，不传给要求页面或目录节点 ID 的接口。

### 来源变化之后

知识页保存的是一次综合形成的结果。源资料更新或删除后，需要确认页面已完成相应刷新。

目录中的“待更新”提示可以反映范围内新增或改写的记忆，但来源删除不一定触发这个提示。因此，不应以“没有待更新标记”判断页面已经不含删除前的内容。清理资料时，也应检查和维护相关知识页。

控制台创建、查看依据、手动刷新和错误排查见[控制台使用](../console.md#7-创建并维护知识页)。

返回 [API 参考](README.md)。
