# Node.js SDK

Node.js SDK 连接已经部署的 ContextBase 服务，支持 JavaScript、TypeScript 和 CommonJS。运行环境要求为 Node.js 18 或以上版本。

开始前，按[快速开始](quickstart.md)准备连接信息并设置环境变量。

## 安装

在应用目录执行：

```bash
npm install @huaweicloud/contextbase-client
```

## 写入、检索和回答

保存为 `quickstart.mjs`：

```javascript
import {
  ContextBaseClient,
  ContextBaseError,
} from "@huaweicloud/contextbase-client";

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error("缺少环境变量：" + name);
  }
  return value;
}

const bankId = requiredEnv("CONTEXTBASE_BANK_ID");
const client = new ContextBaseClient({
  baseUrl: requiredEnv("CONTEXTBASE_API_URL"),
  apiKey: requiredEnv("CONTEXTBASE_API_TOKEN"),
});

try {
  const retained = await client.retain(
    bankId,
    "Alpha 项目使用 PostgreSQL 16。" +
      "数据库结构变更需要经过代码评审，" +
      "并在预发布环境验证后再发布。",
    {
      documentId: "alpha_project_overview",
      tags: ["project:alpha"],
      async: false,
    }
  );
  if (!retained.success) {
    throw new Error("写入未成功");
  }

  const recalled = await client.recall(
    bankId,
    "Alpha 项目的数据库结构变更有什么要求？",
    {
      tags: ["project:alpha"],
      tagsMatch: "all_strict",
      budget: "mid",
      maxTokens: 2048,
    }
  );
  console.log("相关记忆：");
  for (const item of recalled.results) {
    console.log("- " + item.text);
  }

  const reflected = await client.reflect(
    bankId,
    "请整理 Alpha 项目的数据库变更要求。",
    {
      tags: ["project:alpha"],
      tagsMatch: "all_strict",
      includeFacts: true,
    }
  );
  console.log("\n回答：");
  console.log(reflected.text);
  console.log("\n回答依据：");
  console.log(reflected.based_on);
} catch (error) {
  if (error instanceof ContextBaseError) {
    console.error("接口调用失败：", error.statusCode, error.message);
  } else {
    console.error(error);
  }
  process.exitCode = 1;
}
```

执行：

```bash
node quickstart.mjs
```

`async: false` 等待主要写入处理完成，再进行查询。`await` 本身只表示等待 SDK 调用返回；如果使用 `async: true`，返回时服务端仍可能在后台处理。

Recall 返回记忆条目；Reflect 返回回答。请求 `includeFacts: true` 后，才会提供相应的 `based_on` 依据字段。

## CommonJS

CommonJS 应用使用：

```javascript
const {
  ContextBaseClient,
  ContextBaseError,
} = require("@huaweicloud/contextbase-client");
```

将异步调用放入 `async` 函数中执行。

## 更新已有来源

以下代码使用已经初始化的 `client` 和 `bankId`：

```javascript
await client.retain(
  bankId,
  "Alpha 项目使用 PostgreSQL 17。" +
    "数据库结构变更需要经过代码评审，" +
    "并在预发布环境验证后再发布。",
  {
    documentId: "alpha_project_overview",
    tags: ["project:alpha"],
    updateMode: "replace",
  }
);
```

`replace` 提交完整的新内容；`append` 将新内容拼接到旧正文后重新处理。

## 参数命名

单条 `retain` 调用选项使用 `documentId`、`updateMode` 等驼峰名称。`retainBatch` 接收的条目使用 `document_id`、`update_mode` 等字段，不能直接照搬单条调用选项的命名。

Python、Node.js 和 REST 的常用参数对照见[API 参考](api/README.md#sdk-参数对照)。后台处理和重复提交规则见[异步任务](api/operations.md)。

## 完整案例：项目助手

下面的程序对应[项目助手教程](project-assistant.md)，与 Python 示例使用同一批演示内容和文档 ID。两种语言可以分别运行；使用同一 Bank 时，它们会更新同一批演示来源。

程序保存规范、决策和故障记录，读取来源分块并组织上下文，调用 Reflect，然后更新规范并再次查询。默认保留资料，便于在控制台查看。

保存为 `project-assistant.mjs`，使用专用测试 Bank：

```javascript
import {
  ContextBaseClient,
  ContextBaseError,
} from "@huaweicloud/contextbase-client";

function requiredEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error("缺少环境变量：" + name);
  }
  return value;
}

const sources = [
  {
    documentId: "contextbase_demo_alpha_rules",
    content:
      "Alpha 项目使用 PostgreSQL 16。数据库结构变更需要经过代码评审，" +
      "并在预发布环境验证后再发布。",
    category: "rules",
  },
  {
    documentId: "contextbase_demo_alpha_decision_001",
    content:
      "2026 年 11 月 2 日，Alpha 项目评审决定将应用连接池上限设置为 80。" +
      "原因是需要为管理和后台任务预留连接。调整前需要核对实例连接总量。",
    category: "decision",
  },
  {
    documentId: "contextbase_demo_alpha_incident_001",
    content:
      "2026 年 11 月 3 日，Alpha 项目出现连接占用升高。" +
      "排查发现部分异常路径未释放连接，修复后占用恢复。" +
      "类似问题应先检查连接释放和未结束事务，再决定是否调整连接池。",
    category: "incident",
  },
];
const tags = ["project:alpha", "guide:project-assistant"];
const bankId = requiredEnv("CONTEXTBASE_BANK_ID");
const client = new ContextBaseClient({
  baseUrl: requiredEnv("CONTEXTBASE_API_URL"),
  apiKey: requiredEnv("CONTEXTBASE_API_TOKEN"),
});
const cleanup = process.argv.includes("--cleanup");

try {
  for (const source of sources) {
    const retained = await client.retain(bankId, source.content, {
      documentId: source.documentId,
      metadata: { category: source.category },
      tags,
      updateMode: "replace",
      async: false,
    });
    if (!retained.success) {
      throw new Error("写入失败：" + source.documentId);
    }
  }

  const question = "Alpha 项目数据库变更前需要做什么，连接问题应先核对什么？";
  const recalled = await client.recall(bankId, question, {
    types: ["world", "experience"],
    tags,
    tagsMatch: "all_strict",
    includeChunks: true,
    maxChunkTokens: 3000,
    maxTokens: 2048,
  });
  const fragments = recalled.results.map((item, index) => {
    const number = index + 1;
    const chunk = item.chunk_id ? recalled.chunks?.[item.chunk_id] : undefined;
    if (chunk) {
      console.log("来源片段 [" + number + "]：" + chunk.text);
    }
    return (
      "[" + number + "] 来源：" + (item.document_id || "未提供") +
      "\n" + item.text
    );
  });

  const context = fragments.join("\n\n");
  if (context) {
    console.log("\n可交给应用模型的背景：\n" + context);
  } else {
    console.log("未召回相关内容，请先核对来源、Bank 和标签。");
  }

  const reflected = await client.reflect(bankId, question, {
    tags,
    tagsMatch: "all_strict",
    includeFacts: true,
  });
  console.log("\nReflect 回答：");
  console.log(reflected.text);
  console.log("\n实际返回的依据：");
  console.log(reflected.based_on);

  await client.retain(
    bankId,
    "Alpha 项目使用 PostgreSQL 17。数据库结构变更需要经过代码评审，" +
      "并在预发布环境验证后再发布。",
    {
      documentId: sources[0].documentId,
      metadata: { category: "rules" },
      tags,
      updateMode: "replace",
      async: false,
    }
  );
  const document = await client.getDocument(bankId, sources[0].documentId);
  console.log("\n更新后的来源：", document.id);
  console.log(document.original_text || "当前配置未返回文档原文");

  const updated = await client.recall(
    bankId,
    "Alpha 项目目前使用哪个 PostgreSQL 版本？",
    {
      types: ["world", "experience"],
      tags,
      tagsMatch: "all_strict",
    }
  );
  console.log("\n更新后的相关记忆：");
  for (const item of updated.results) {
    console.log(item.text);
  }

  if (cleanup) {
    for (const source of sources) {
      await client.deleteDocument(bankId, source.documentId);
    }
    console.log("三份演示来源已删除。");
  }
} catch (error) {
  if (error instanceof ContextBaseError) {
    console.error("接口调用失败：", error.statusCode, error.message);
  } else {
    console.error(error);
  }
  process.exitCode = 1;
}
```

运行并保留来源：

```bash
node project-assistant.mjs
```

运行后删除演示来源：

```bash
node project-assistant.mjs --cleanup
```

程序将命中记忆的正文组装为背景，另行输出来源片段供核对，不调用另一个模型服务；Reflect 部分由 ContextBase 完成回答。文档、分块和回答依据应按实际结果核对，不要求固定的记忆条数或生成文字。

只有 `contextbase_demo_alpha_` 开头的三个示例 ID 会被此程序替换和清理。不要将它们用于其他资料。更新规范仅修改服务中的来源内容，不会升级实际数据库。

下一步：[在控制台检查结果](console.md) · [检索结果使用指导](api/memories.md#如何判断和改善检索结果)。
