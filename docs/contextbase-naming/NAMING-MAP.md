# ContextBase 命名与兼容映射

用户已定展示名：**ContextBase**。技术 slug `contextbase` 采用为本次默认部署标识，属于实施选择，不代表用户逐项批准外部身份迁移。本轮不删除或新增发行 alias，避免多份配置、凭证和 MCP 所有权歧义。

| 层/入口 | 本轮 canonical | 兼容/理由 |
|---|---|---|
| 默认 UI/API/OpenAPI/banner/worker/MCP serverInfo 展示 | ContextBase | 可运行时覆盖；不作为数据库/工具/连接 key |
| 默认部署 slug | contextbase | 小写独立校验；不重命名 bank/Workspace/数据库 |
| v1 /product-config | product_config_version=1 + contextdb_name | 保持原两键及原字段/校验/SDK 签名；旧调用端继续读 slug |
| v2 /product-config/v2 | version=2 + contextdb_name + display_name | 新增独立端点，不把未知字段塞给严格 v1 解析器 |
| 运行配置 | product_display_name；contextdb_name | 显式 display 优先；只有旧 contextdb_name 时显示旧值；均未设时使用品牌默认值；空/非法值失败，不自动正规化 |
| 新 UI + 旧 API | 旧 contextdb_name 模式访问 v1 | 显式 v2 展示模式要求 v2；缺失/格式不符失败关闭，无静默降级；新 API 的 v1 额外 X-Product-Display-Name 头使新 UI 的 legacy 模式也能发现 API-only 展示覆盖 |
| 旧 UI + 新 API | 仅legacy-only的相同旧 contextdb_name 可兼容；独立展示需同步升级UI | 新默认部署与旧 UI 默认不同则拒绝；同步配置/升级，不静默错连 |
| CLI bin / Rust crate | agentstratum / hindsight-cli | 原命令、Profile、旧脚本不破坏；help 显示 ContextBase |
| Coding Agents package/bin | agentstratum-coding-agents；原 hook bins | tarball 正式身份暂保持；描述/安装标题显示 ContextBase |
| Claude plugin ID / standard plugin ID | agentstratum-memory / agentstratum | 宿主安装记录、MCP 所有权保持；描述显示 ContextBase |
| 配置目录和 Profile | ~/.agentstratum；原各文件名 | 原读写优先级不变，无自动迁移/删除，无第二目录 |
| 环境变量 | AGENTSTRATUM_*、HINDSIGHT_* | 保持现有各层优先级及冲突诊断；不新增 CONTEXTBASE_* alias |
| MCP 注册 key/工具名/skill IDs | 原 agentstratum / agentstratum_* | serverInfo 显示与 tool identity 分离；外部同名 HTTP/stdio 不删除 |
| UI /api/health service | ContextBase-control-plane（可覆盖） | 这是运行展示字段，与 telemetry resource service.name 不同 |
| Telemetry resource service.name | 默认 agentstratum-api/worker；显式旧 contextdb_name 继续按旧 slug | product_display_name 不切分监控历史；展示 banner/title 独立 |
| HTTP headers/metrics/log markers | 原 X-Agentstratum-*、原 instrument/log 标识 | 协议消费者及诊断可追踪，不随展示改名 |
| CDN/归档/installer 路径 | 原 agentstratum-* 目录和文件名 | 固定发行身份；下载说明须明确 ContextBase 使用兼容命令 |
| SDK/import/native bank_id/API path | 原 hindsight 包名和原路径 | 432 签名保护；仅 additive v2 合同，内容/ID/归档无词替换 |
| 许可证、作者、历史/客户文本 | 原字节 | 不在品牌渲染或生成范围 |

本轮外部不兼容改动：无计划项。固定 agentstratum 标识是为保留已有消费者作出的兼容实施策略，不声称用户永久选定该发行名。以后若迁移 CLI、包或协议，必须单独明确 alias/安装和冲突规则，不可仅把 display_name 改成 slug。

日后展示改名：编辑 brand/definition.json 的 display_name 和 deployment_slug，运行 `bash scripts/sync-product-brand.sh`，运行现有 `scripts/generate-openapi.sh` 和 `scripts/generate-clients.sh` 同步接口展示元数据，再运行同步脚本 `--check`、构建及验收。运行时覆盖展示名无需重建 UI。品牌定义不含版本、密钥、客户文本或主机配置。
