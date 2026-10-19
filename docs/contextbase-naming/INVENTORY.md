> 历史记录：本文记录此前仅修改展示名的整合。2026-10-19 的对外身份统一已取代其命名约定；当前契约见 [NAMING-MAP.md](NAMING-MAP.md)。

# 真实命名入口盘点

基点：960983bb4。完整路径/行号搜索记录位于 runs/contextbase-naming-20261019/naming-search.json；搜索命中不等于手改工作量。客户数据不参与生成器输入。

| 真实源入口 | 消费者 | 初次手改及日后生成 |
|---|---|---|
| hindsight-api-slim/hindsight_api/product_config.py | /product-config、brand、banner、worker | 保留 v1 严格模型；新增 v2 展示模型；默认值读生成适配 |
| hindsight-api-slim/hindsight_api/brand.py | HTTP title、MCP initialize、service、固定 webhook/reranker 头 | 动态展示与协议常量分离，固定值来自生成适配 |
| hindsight-control-plane/src/lib/product-config{,-server}.ts | layout metadata、i18n、health、product-runtime、product-guard | 严格解析 v1/v2；部署展示名独立；沿用已有拒绝/会话流程 |
| hindsight-control-plane/src/components/brand.tsx | 顶栏与导航 | 已动态，复用；无逐页品牌输入 |
| hindsight-cli/src/main.rs、Cargo.toml | help、binary、Profiles | help/description 生成品牌；bin、env、目录/配置语义不变 |
| coding-agents/src/core/brand.ts、install-ui.ts、mcp-server.ts | ANSI/plain 安装 UI、MCP serverInfo | 生成默认展示适配；工具/注册 key 保持原身份 |
| claude-code/scripts/mcp_server.py、lib/config.py、run_mcp.sh | MCP 显示、远程配置、launcher | 生成展示适配；配置、目录及 ownership 不变 |
| 三类插件 manifest、.claude-plugin/marketplace.json | 四类候选中的插件描述/注册 | 生成器仅更新明确的展示字段，版本/许可证/注册不变 |
| scripts/install-agentstratum.sh | 独立下载安装 | 从专用模板生成展示文字；机器路径/校验协议不变 |
| scripts/package-client-plugins.py、.github/workflows/release.yml | archive/CDN 路径与手动候选 | 引用固定身份；候选打包前检查品牌生成漂移 |
| scripts/generate-{openapi,clients}.sh、prepare-client-spec.py | SDK/OpenAPI | 从本次 API 源生成；不手改生成 SDK；432 签名 guard 保留 |
| brand/definition.json | 上述各语言默认值、元数据及生成清单 | 唯一品牌权威；二次改名只改其展示名/slug 后运行 generator |

源 manifest 和 Cargo description 是字段级生成物，不把整个业务文件当模板。独立 shell 发行脚本使用显式模板；生成 ledger 记录来源及 hash。已有 README→skill/docs 生成链继续沿用；兼容命令示例保持可执行，不替换客户文本。

以下保留：技术 package/import（hindsight_*）、agentstratum CLI/插件注册/工具/env/目录/metrics/header、测试的旧配置与外部 MCP fixture、历史 docs/报告、许可证/作者、用户 bank ID 和任意内容。仅当前用户展示另行接入品牌权威，不能用“历史”替代实际入口分类。

保留功能：原 UI 布局、分页搜索/61 项、locale/query/hash、原生归档/下载、旧页签拒绝写入、会话撤销/Host/Origin、原生 API/SDK/MCP、远程端点和凭证隔离、11 JSON 宿主/Codex ownership、Rust regress 依赖及 nullable PATCH。它们均继承指定祖先；实际回归尚待执行。

补充入口（独立初审后）：CLI configure 标题；Coding Agents attribution/inject/knowledge-tools/knowledge-injection/runtime/session-start 的自身提示；usage 当前/历史归因识别；三类客户端当前 README/skill prose；docs companion page metadata。这些均通过生成常量或显式 prose 模板适配，工具名、wrapper tag、历史数据和命令不变。模板清单见 brand/text-targets.json；历史 AMB 测量主体固定保留。非完整 locale 文件仍在仓库保留，但 request.ts 只加载 en/zh-CN（其他 locale 显式回退），不把未加载历史翻译当当前显示。

.env.example 及 bundled env 使用中性的 My Company/my-deployment 示例，不维护另一份产品默认值；两份按既有模板合同保持一致。客户端 prose 模板是新增的最上游文本源，原 README→skill/docs 构建继续沿用，CLAUDE.md 已明确编辑入口。
