# Python SDK

Python SDK 连接已经部署的 ContextBase 服务，不会在本机安装服务或自动创建 Bank。运行环境要求为 Python 3.10 或以上版本。

开始前，按[快速开始](quickstart.md)准备连接信息并设置环境变量。

## 安装

取得服务方提供的 wheel，在安装包所在目录执行：

```bash
python -m pip install ./contextbase_client-1.0.0-py3-none-any.whl
```

将文件名替换为实际下载的安装包名称。

## 写入、检索和回答

保存为 `quickstart.py`：

```python
import os

from contextbase_client import ContextBase


def main() -> None:
    bank_id = os.environ["CONTEXTBASE_BANK_ID"]

    with ContextBase(
        base_url=os.environ["CONTEXTBASE_API_URL"],
        api_key=os.environ["CONTEXTBASE_API_TOKEN"],
    ) as client:
        retained = client.retain(
            bank_id=bank_id,
            content=(
                "Alpha 项目使用 PostgreSQL 16。"
                "数据库结构变更需要经过代码评审，"
                "并在预发布环境验证后再发布。"
            ),
            document_id="alpha_project_overview",
            tags=["project:alpha"],
            retain_async=False,
        )
        if not retained.success:
            raise RuntimeError("写入未成功")

        recalled = client.recall(
            bank_id=bank_id,
            query="Alpha 项目的数据库结构变更有什么要求？",
            tags=["project:alpha"],
            tags_match="all_strict",
            budget="mid",
            max_tokens=2048,
        )
        print("相关记忆：")
        for item in recalled.results:
            print(f"- {item.text}")

        reflected = client.reflect(
            bank_id=bank_id,
            query="请整理 Alpha 项目的数据库变更要求。",
            tags=["project:alpha"],
            tags_match="all_strict",
            include_facts=True,
        )
        print("\n回答：")
        print(reflected.text)
        print("\n回答依据：")
        print(reflected.based_on)


if __name__ == "__main__":
    main()
```

执行：

```bash
python quickstart.py
```

`retain_async=False` 等待主要写入处理完成，再进行查询。观察整理和知识页刷新可能晚于这次写入完成。

Recall 返回的 `results` 是记忆条目；Reflect 的 `text` 是回答。只有请求 `include_facts=True` 时，才会提供相应的 `based_on` 依据字段。

## 异步应用

在已经运行事件循环的应用中，使用 `aretain`、`arecall`、`areflect`，并在结束时调用 `aclose`：

```python
import asyncio
import os

from contextbase_client import ContextBase


async def main() -> None:
    client = ContextBase(
        base_url=os.environ["CONTEXTBASE_API_URL"],
        api_key=os.environ["CONTEXTBASE_API_TOKEN"],
    )
    try:
        result = await client.arecall(
            bank_id=os.environ["CONTEXTBASE_BANK_ID"],
            query="Alpha 项目的数据库变更有什么要求？",
        )
        for item in result.results:
            print(item.text)
    finally:
        await client.aclose()


asyncio.run(main())
```

异步 I/O 与服务端后台处理是两个独立选项：

| 写法 | 含义 |
| --- | --- |
| `await client.aretain(...)` | 以异步 I/O 发起请求 |
| `retain_async=True` | 让服务端在后台处理写入 |

因此，`aretain(..., retain_async=False)` 仍会等待服务端主要处理完成。

## 更新已有来源

以下代码放在已经初始化的 `client` 使用范围内：

```python
client.retain(
    bank_id=bank_id,
    content=(
        "Alpha 项目使用 PostgreSQL 17。"
        "数据库结构变更需要经过代码评审，"
        "并在预发布环境验证后再发布。"
    ),
    document_id="alpha_project_overview",
    tags=["project:alpha"],
    update_mode="replace",
)
```

`replace` 提交完整的新内容；`append` 将新内容拼接到旧正文后重新处理。两种方式都可能改变提取的记忆。

参数和重试规则见[记忆 API](api/memories.md)，后台任务的完成条件见[异步任务](api/operations.md)。
