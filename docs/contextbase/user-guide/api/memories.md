# 记忆接口

本页路径均相对于 `/v1/default/banks/{bank_id}`。地址和认证规则见 [API 参考](README.md)。

## Retain：写入记忆

**POST `/memories`**

```json
{
  "items": [
    {
      "content": "Alpha 项目使用 PostgreSQL 16。",
      "document_id": "alpha_project_overview",
      "context": "项目技术说明",
      "metadata": {
        "source": "project_handbook"
      },
      "tags": ["project:alpha"],
      "update_mode": "replace"
    }
  ],
  "async": false
}
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `items` | 是 | 待处理的内容条目数组 |
| `items[].content` | 是 | 来源内容；基本用法为文本 |
| `items[].document_id` | 否 | 来源文档 ID，建议显式指定 |
| `items[].context` | 否 | 帮助理解内容的背景说明 |
| `items[].timestamp` | 否 | 内容发生时间，支持 ISO 8601 时间字符串 |
| `items[].metadata` | 否 | 自定义元数据，键和值均为字符串 |
| `items[].tags` | 否 | 用于后续检索筛选的标签 |
| `items[].update_mode` | 否 | `replace` 或 `append`，默认 `replace` |
| `async` | 否 | 是否后台处理，默认 `false` |
| `operation_id` | 否 | 异步写入的客户端 UUID，用于重试时复用任务身份 |

`timestamp` 省略或为 `null` 时默认使用当前时间；无明确时间的资料可使用 `"unset"`。

同一请求中，相同 `document_id` 的条目归入同一文档。不同来源应使用不同 ID。省略时由服务生成，不能假定每个条目都会成为独立文档。

同步响应的主要字段：

```json
{
  "success": true,
  "bank_id": "project_alpha",
  "items_count": 1,
  "async": false
}
```

`items_count` 是提交处理的条目数，不是最终记忆数。

同步调用等待主要写入处理完成。观察整理和知识页刷新等后续任务可能更晚完成。异步调用的返回与完成条件见[异步任务](operations.md)。

### 更新已有文档

继续使用原 `document_id`：

| `update_mode` | 行为 | 提交内容 |
| --- | --- | --- |
| `replace` | 替换旧内容并重新处理 | 希望保留的完整新正文 |
| `append` | 将新内容拼接到旧正文后重新处理 | 本次需要追加的正文 |

`replace` 不会保留本次未提交的旧正文。`append` 也不意味着只处理新增部分，两种方式都可能改变提取的记忆。

## Recall：检索记忆

**POST `/memories/recall`**

```json
{
  "query": "Alpha 项目使用什么数据库？",
  "budget": "mid",
  "max_tokens": 2048,
  "tags": ["project:alpha"],
  "tags_match": "all_strict",
  "include": {
    "chunks": {
      "max_tokens": 4096
    }
  }
}
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `query` | 是 | 自然语言查询 |
| `types` | 否 | `world`、`experience`、`observation`；省略时检索全部类型 |
| `budget` | 否 | `low`、`mid`、`high`，默认 `mid` |
| `max_tokens` | 否 | 返回记忆的内容预算，默认 `4096`，不是结果条数 |
| `tags` | 否 | 标签筛选条件 |
| `tags_match` | 否 | 标签匹配方式，默认 `any` |
| `include.chunks` | 否 | 请求相关来源分块，可指定独立的 `max_tokens` |
| `include.source_facts` | 否 | 请求观察所依据的来源事实，可指定独立的 `max_tokens` |

响应示例：

```json
{
  "results": [
    {
      "id": "memory_example",
      "text": "Alpha 项目使用 PostgreSQL 16。",
      "type": "world",
      "document_id": "alpha_project_overview",
      "tags": ["project:alpha"]
    }
  ]
}
```

`results` 返回相关记忆，不一定是原文。请求分块后，来源内容通过 `chunks` 返回，以分块 ID 关联。实际返回范围受保存配置和内容预算影响。

请求观察的来源事实后，`source_facts` 按事实 ID 返回。如果 `source_facts_truncated=true`，表示内容预算不足，部分引用未附带完整正文。

### 标签筛选

下表描述 Recall 对记忆标签的匹配：

| `tags_match` | 规则 | 无标签记忆 |
| --- | --- | --- |
| `any` | 匹配任意指定标签 | 包含 |
| `all` | 匹配全部指定标签 | 包含 |
| `any_strict` | 匹配任意指定标签 | 排除 |
| `all_strict` | 匹配全部指定标签 | 排除 |
| `exact` | 标签集合完全相同 | 仅查询标签集合为空时匹配 |

需要排除无标签内容时，使用相应的严格匹配方式。标签筛选不替代 Bank 授权。

## Reflect：基于记忆回答

**POST `/reflect`**

```json
{
  "query": "请整理 Alpha 项目的数据库变更要求。",
  "budget": "low",
  "tags": ["project:alpha"],
  "tags_match": "all_strict",
  "include": {
    "facts": {}
  }
}
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `query` | 是 | 问题及必要背景 |
| `budget` | 否 | `low`、`mid`、`high`，默认 `low` |
| `max_tokens` | 否 | 回答内容预算，默认 `4096` |
| `tags` / `tags_match` | 否 | 限定检索标签范围 |
| `fact_types` | 否 | 限定参与检索的记忆类型 |
| `include.facts` | 否 | 设置为 `{}`，请求回答依据 |
| `response_schema` | 否 | 用 JSON Schema 描述期望的结构化输出 |

基本响应示例：

```json
{
  "text": "Alpha 项目的数据库结构变更需要经过代码评审，并在预发布环境验证后发布。"
}
```

只有请求 `include.facts` 时，才会提供相应的 `based_on` 依据字段。展示来源时应使用实际返回的依据，不能把回答中的每句话都视为已经保存的事实。

Reflect 的标签会限定相关内容的检索范围，但 Bank 的全局指令仍可能参与回答行为，不应把标签当作完整的安全隔离边界。

### 结构化输出

传入 `response_schema` 后，应用应检查响应中的 `structured_output`。如有 `structured_output_error`，表示结构化输出处理失败；如果两者都没有，可能是本次回答没有与结构匹配的内容。

HTTP 请求成功不等于取得了可用的结构化结果。

继续阅读：[异步任务](operations.md) · [文档与知识](documents.md)。
