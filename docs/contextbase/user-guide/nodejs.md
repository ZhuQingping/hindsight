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
