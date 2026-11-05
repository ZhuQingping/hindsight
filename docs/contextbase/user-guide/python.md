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

`append` 需要启用原文保存，并依赖已保存的旧正文。`store_document_text=false` 时不支持追加，同步写入会返回 HTTP 400。无法使用追加时，由应用合并完整正文后用 `replace` 提交，或将独立片段保存为不同文档。详见[更新已有文档](api/memories.md#更新已有文档)。

参数和重试规则见[记忆 API](api/memories.md)，后台任务的完成条件见[异步任务](api/operations.md)。

## 完整案例：项目助手

下面的程序对应[项目助手教程](project-assistant.md)。它在同一 Bank 中保存三份来源，检索并组织带编号的上下文，调用 Reflect，然后更新规范并读取来源。默认保留资料，便于在控制台查看。

此示例使用异步 I/O，但每次写入仍等待主要处理完成。Python 的文档读取与删除使用 SDK 暴露的低层异步 `documents` 接口。

保存为 `project_assistant.py`，使用专用测试 Bank：

```python
import argparse
import asyncio
import os
from dataclasses import dataclass

from contextbase_client import ContextBase


@dataclass(frozen=True)
class Source:
    document_id: str
    content: str
    category: str


SOURCES = [
    Source(
        "contextbase_demo_alpha_rules",
        "Alpha 项目使用 PostgreSQL 16。数据库结构变更需要经过代码评审，"
        "并在预发布环境验证后再发布。",
        "rules",
    ),
    Source(
        "contextbase_demo_alpha_decision_001",
        "2026 年 11 月 2 日，Alpha 项目评审决定将应用连接池上限设置为 80。"
        "原因是需要为管理和后台任务预留连接。调整前需要核对实例连接总量。",
        "decision",
    ),
    Source(
        "contextbase_demo_alpha_incident_001",
        "2026 年 11 月 3 日，Alpha 项目出现连接占用升高。"
        "排查发现部分异常路径未释放连接，修复后占用恢复。"
        "类似问题应先检查连接释放和未结束事务，再决定是否调整连接池。",
        "incident",
    ),
]
TAGS = ["project:alpha", "guide:project-assistant"]


async def main(cleanup: bool) -> None:
    bank_id = os.environ["CONTEXTBASE_BANK_ID"]
    client = ContextBase(
        base_url=os.environ["CONTEXTBASE_API_URL"],
        api_key=os.environ["CONTEXTBASE_API_TOKEN"],
    )
    try:
        for source in SOURCES:
            retained = await client.aretain(
                bank_id=bank_id,
                content=source.content,
                document_id=source.document_id,
                metadata={"category": source.category},
                tags=TAGS,
                update_mode="replace",
                retain_async=False,
            )
            if not retained.success:
                raise RuntimeError(f"写入失败：{source.document_id}")

        question = "Alpha 项目数据库变更前需要做什么，连接问题应先核对什么？"
        recalled = await client.arecall(
            bank_id=bank_id,
            query=question,
            types=["world", "experience"],
            tags=TAGS,
            tags_match="all_strict",
            include_chunks=True,
            max_chunk_tokens=3000,
            max_tokens=2048,
        )

        fragments: list[str] = []
        chunks = recalled.chunks or {}
        for number, item in enumerate(recalled.results, 1):
            fragments.append(
                f"[{number}] 来源：{item.document_id or '未提供'}\n{item.text}"
            )
            chunk = chunks.get(item.chunk_id) if item.chunk_id else None
            if chunk is not None:
                print(f"来源片段 [{number}]：{chunk.text}")

        context = "\n\n".join(fragments)
        if context:
            print("\n可交给应用模型的背景：\n" + context)
        else:
            print("未召回相关内容，请先核对来源、Bank 和标签。")

        reflected = await client.areflect(
            bank_id=bank_id,
            query=question,
            tags=TAGS,
            tags_match="all_strict",
            include_facts=True,
        )
        print("\nReflect 回答：")
        print(reflected.text)
        print("\n实际返回的依据：")
        print(reflected.based_on)

        await client.aretain(
            bank_id=bank_id,
            content=(
                "Alpha 项目使用 PostgreSQL 17。数据库结构变更需要经过代码评审，"
                "并在预发布环境验证后再发布。"
            ),
            document_id=SOURCES[0].document_id,
            metadata={"category": "rules"},
            tags=TAGS,
            update_mode="replace",
            retain_async=False,
        )
        document = await client.documents.get_document(
            bank_id=bank_id,
            document_id=SOURCES[0].document_id,
        )
        print("\n更新后的来源：", document.id)
        print(document.original_text or "当前配置未返回文档原文")

        updated = await client.arecall(
            bank_id=bank_id,
            query="Alpha 项目目前使用哪个 PostgreSQL 版本？",
            types=["world", "experience"],
            tags=TAGS,
            tags_match="all_strict",
        )
        print("\n更新后的相关记忆：")
        for item in updated.results:
            print(item.text)

        if cleanup:
            for source in SOURCES:
                await client.documents.delete_document(
                    bank_id=bank_id,
                    document_id=source.document_id,
                )
            print("三份演示来源已删除。")
    finally:
        await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    asyncio.run(main(cleanup=parser.parse_args().cleanup))
```

运行并保留来源：

```bash
python project_assistant.py
```

运行后删除演示来源：

```bash
python project_assistant.py --cleanup
```

程序将命中记忆的正文组装为背景，另行输出来源片段供核对，不包含另一个模型服务的调用。Reflect 部分则由 ContextBase 完成回答。打印的文档 ID、分块与 `based_on` 用于核对来源；不应要求记忆数或回答文字固定。

只有 `contextbase_demo_alpha_` 开头的三个示例 ID 会被此程序替换和清理。不要将它们用于其他资料。更新规范仅修改服务中的来源内容，不会升级实际数据库。

下一步：[在控制台检查结果](console.md) · [检索结果使用指导](api/memories.md#如何判断和改善检索结果)。
