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
| `items[].update_mode` | 否 | `replace` 或 `append`，默认 `replace`；`append` 需要启用原文保存 |
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

`append` 依赖服务端保存的原文。关闭原文保存（`store_document_text=false`）时，服务不支持追加写入，同步 Retain 请求会返回 HTTP 400。使用前请向服务提供方确认保存配置；已有来源还需确认旧正文已经保存，之后开启原文保存不会补回历史正文。

不能使用追加时，由应用保留完整正文，合并新内容后以 `replace` 提交；需要分别管理的会话片段或事件，也可以使用不同的文档 ID 保存。

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
| `prefer_observations` | 否 | 默认 `false`；同时请求观察和原始事实时，减少观察及其来源事实重复返回 |
| `query_timestamp` | 否 | 用于理解相对日期及时间评分的查询时间基准 |
| `temporal_window` | 否 | 提供时间相关检索的起止范围，影响排序，不作严格时间过滤 |

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

### 如何使用来源

需要为应用回答保留来源时，应沿返回的标识关联，不要仅凭文字相似度重新猜测出处：

| 字段 | 关联方式 |
| --- | --- |
| `results[].id` | 本次命中的记忆 ID |
| `results[].document_id` | 定位相应来源文档 |
| `results[].chunk_id` | 在 `chunks` 中查找相应分块 |
| `results[].source_fact_ids` | 对观察结果，在 `source_facts` 中查找请求返回的来源事实 |

分块和来源事实有各自的返回预算。某条引用未附正文，可能是没有请求、预算不足或原文未保存，不应直接判断为来源不存在。

SDK 的[完整项目示例](../project-assistant.md)演示了从 `chunk_id` 读取片段，并为应用上下文保留来源编号。

### 如何判断和改善检索结果

先准备少量有明确来源的典型问题，检查是否找对内容，再调整参数。回答通顺、得分较高或结果较多，都不能单独说明命中了正确资料。

| 现象 | 先检查什么 | 接下来怎样调整 |
| --- | --- | --- |
| 没有相关结果 | Bank、写入任务、标签和类型是否正确 | 放宽不必要的筛选，并用正文中明确的对象与主题提问 |
| 找到主题但缺少原始背景 | 是否请求分块、是否保存原文 | 请求 `include.chunks`，需要时调整分块预算 |
| 观察与原始事实内容重复 | 是否同时召回多种类型 | 按用途选择类型，或使用 `prefer_observations` |
| 结果量不适合模型上下文 | `max_tokens` 和独立的来源预算 | 在应用可承受的范围内调整返回内容量 |
| 来源错误或已经过期 | 文档正文、记忆状态和页面刷新状态 | 先维护来源或纠正事实，再重新验证 |
| 时间不符合预期 | 事件时间与查询基准是否明确 | 明确问题中的时间；不要把时间窗口当作严格筛选 |

`budget` 控制处理预算，`max_tokens` 控制返回记忆的内容量。增加预算不会修正错误来源，也不会绕过已有筛选条件。

`temporal_window` 的起止范围用于优先找到时间相关的记忆，范围外的结果仍可能通过其他检索路径返回。需要精确统计某个期间的全部记录时，应结合业务数据查询。

元数据用于保留来源属性，不能假定任意元数据字段都自动成为 Recall 的筛选条件。常用范围控制使用接口明确支持的标签和类型。

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

### 在应用中处理回答

保存本次问题、目标 Bank、筛选条件和实际返回的依据，方便用户回到来源。对需要核对的结论，先检查 `based_on`，再决定如何展示。

如果回答缺少预期依据，可以用相同问题和筛选条件执行 Recall，确认资料是否可检索。没有相关资料时，应补充来源或向用户说明当前资料不足，不把没有依据的生成文字标成已核实内容。

Reflect 请求的背景可以直接写入 `query`。应用已经有自己的模型流程时，使用 Recall 补充上下文通常更便于控制提示词和后续工具调用。

继续阅读：[异步任务](operations.md) · [文档与知识](documents.md)。
