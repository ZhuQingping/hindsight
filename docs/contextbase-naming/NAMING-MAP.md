# ContextBase 对外命名契约

2026-10-19 用户明确要求：PR #3 涉及的 REST/Web API、Webhook、MCP、插件、模型出站和监控，对外品牌全部统一为 `contextbase`。这取代了此前仅更换展示名、保留 agentstratum 技术标识的实施约定。

| 层 / 入口 | 当前名称 | 说明 |
|---|---|---|
| UI、API/OpenAPI 标题、banner、MCP serverInfo | ContextBase | 展示名继续支持 `product_display_name` 覆盖 |
| 默认部署 slug | contextbase | `contextdb_name` 字段及其校验规则不变 |
| CLI bin / Rust crate | contextbase / hindsight-cli | crate 内部名称不变；保留 Profile 功能 |
| Coding Agents package / bin | contextbase-coding-agents | hook bins 使用 `contextbase-*`；工具使用 `contextbase_*` |
| Claude plugin / standard plugin | contextbase-memory / contextbase | MCP 注册 key 为 `contextbase` |
| 配置目录和环境变量 | ~/.contextbase、CONTEXTBASE_* | 公开 API 配置使用 `CONTEXTBASE_API_*`，内部 HINDSIGHT 配置实现不改名 |
| Webhook 头 | X-ContextBase-Event、X-ContextBase-Signature、X-ContextBase-Signature-V2 | 签名算法、原始 payload 和 X-Hub-Signature-256 不变 |
| Reranker bank header | X-ContextBase-Bank-Id | 与标准的 MCP X-Bank-Id 区分 |
| 模型出站 | contextbase 产品标识 | User-Agent、平台应用标识、批任务名称、模型工具命名空间同步更新 |
| OTel / Prometheus / Grafana | contextbase.*、contextbase_*、contextbase-api / contextbase-worker | 默认 service.name 同步；显式部署 slug 的现有覆盖行为不变 |
| 安装器及发行产物 | install-contextbase.sh、contextbase-* | 只构建 CLI 和三类插件客户端；不新增服务端发行 |
| SDK 包名和 import | 原 Hindsight 名称 | SDK 对外产品元数据同步；包名、导入路径、业务方法签名不改 |
| 业务 API 路径、bank ID、客户内容 | 原值 | 不进行字符串过滤或数据改写 |
| 内部日志、异常堆栈、许可证、历史记录 | 原内容 | 不隐藏诊断或改写归属、历史事实 |

这次明确切换安装和协议身份，不提供旧名称 alias，也不自动搬迁旧配置。已有使用者需要按新命令和配置入口重新配置客户端，并同步更新 Webhook 接收端与监控查询。安装器仍只管理能够确认归属的配置，不接管外部同名 MCP 服务。

`/product-config` 仍使用 v1 两字段结构，`/product-config/v2` 仍是独立展示配置端点；品牌切换不增加或删除业务 API。`historical_display_names` 中的旧名仅用于识别历史引用，不是安装入口或协议别名。

`brand/definition.json` 和 `brand/identity-contract.json` 共同记录本次公开身份；生成器继续拒绝未经契约同步的标识漂移。运行 `bash scripts/sync-product-brand.sh` 更新枚举的生成目标，使用 `--check` 检查漂移；OpenAPI 元数据与 SDK 配置默认值须同步。

本目录旧 RESULT / VALIDATION / GOALS 文档记录此前展示名整合的历史验收，不代表本次公开身份切换已通过那些测试。当前变更的验证结果见对应 PR。
