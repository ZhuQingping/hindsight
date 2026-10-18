# ContextDB v2 本地部署配置清单

> **历史快照，不适用于当前首发版本。** 下文保留当时的配置、接口、表结构和测试环境用于对照，不应照此部署或验证当前代码。当前以[首发设计](contextdb-release-design.md)、[部署合同](contextdb-deployment-contract.md)和[API验证手册](contextdb-optimized-curl-guide.md)为准；开发期旧库不自动升级。


核对日期：2026-10-15。面向开发者和部署人员；列出当前体验实例显式配置的变量，不把全部原生默认项混在一起。真实密码、API Key、pepper 不写入本文。

## 从哪里查看

当前运行目录：

```text
/Users/zhuqingping/Work/Database/Context/test/hindsight_test/contextdb-v2-experience/20261015-104834-735ecc
```

以后优先读取同级 `latest-run.txt` 获取最新目录。当前部署将以下文件内容传入服务进程的环境；Hindsight 并不会自动读取任意命名的 JSON 文件。

| 文件 | 内容 |
| --- | --- |
| `deployment.json` | 数据库连接、ContextDB 身份和管控认证、API 扩展、服务运行配置 |
| `model.env` | 华为云 MaaS 的 LLM、Embedding、Rerank 配置和凭据 |
| `ui-settings.json` | UI 登录口令、服务端管理员 Key、后端地址、ContextDB UI 开关 |
| `runtime.json` | 本次代码目录、数据库名、API/UI 地址；属于运行记录，不是环境变量文件 |
| `control-key.json` | 本地管控客户端使用的服务 Key；服务端配置保存它的摘要 |
| `instance-bootstrap.json` | 初始化响应及首次生成的管理员业务 Key |
| `workspaces.json` | 初始化时创建的空间信息快照；当前状态以 API/PG 为准 |

这些运行文件含敏感信息，只在本机查看，不提交研究仓库。`deployment.json` 与 `ui-settings.json` 不是 shell 脚本，不能直接 `source`。

## 数据库相关

| 变量 | 当前配置 | 用途 |
| --- | --- | --- |
| `HINDSIGHT_API_DATABASE_URL` | `postgresql://zhuqingping@127.0.0.1:5432/contextdb_v2_experience_20261015_104834_735ecc` | Hindsight API 与当前内嵌 Worker 连接 PG |
| `CONTEXTDB_BOOTSTRAP_DATABASE_URL` | 与上述 URL 相同 | 自研 bootstrap 命令安装 `ctxdb_meta` 表结构；不是另一套数据库 |
| `HINDSIGHT_API_DB_POOL_MAX_SIZE` | `10` | 主连接池上限 |
| `HINDSIGHT_API_READ_DB_POOL_MAX_SIZE` | `10` | 读连接池上限；实际是否启用独立池取决于原生配置 |
| `HINDSIGHT_API_TEXT_SEARCH_EXTENSION` | `pgroonga` | 当前全文检索后端 |
| `HINDSIGHT_API_MIGRATION_ISOLATION` | `false` | 当前 ContextDB 部署不使用隔离迁移子进程 |

本机 URL 没有密码段，使用现有 PG 认证配置；换成需要密码的 PG 时应通过部署密钥管理提供完整连接串。

当前未显式设置 `HINDSIGHT_API_VECTOR_EXTENSION`，使用原生默认 `pgvector`。没有用 `HINDSIGHT_API_DATABASE_SCHEMA` 固定一个工作空间：扩展从请求的 `bank_id` 查 metadata，选择对应 schema。

`shared_preload_libraries`、`compute_query_id`、`pgroonga.enable_wal_resource_manager` 等是 **PG 服务端参数**，存放在 PostgreSQL 配置中，不是 Hindsight 环境变量。插件安装状态通过 `pg_extension` 查看，实际索引通过 `pg_indexes` 查看。

本次只读核对：体验库编码为 `SQL_ASCII`，preload 为空。当前实例用于基本体验；完整中英文和生产恢复验收应使用 `UTF8` 库并完成插件运行配置与恢复测试。

## 自研 ContextDB 身份与认证

| 变量 | 当前配置 | 用途 |
| --- | --- | --- |
| `CONTEXTDB_INSTANCE_ID` | `ctxdb-local-v2-experience` | 当前实例的固定身份 |
| `CONTEXTDB_CLOUD_TENANT_ID` | `local-cloud-tenant` | 当前所属云租户 |
| `CONTEXTDB_KEY_PEPPER` | 已设置，值隐藏 | 业务 Key 的摘要校验密钥；重启不能重新生成，丢失或改变会使现有 Key 无法认证 |
| `CONTEXTDB_CONTROL_KEYS` | 已设置，值隐藏 | 可信管控服务 Key 的 `key_id` / SHA-256 摘要清单，支持轮换；不保存明文服务 Key |
| `CONTEXTDB_CONTROL_NETWORKS` | `127.0.0.1/32,::1/128` | 管控请求允许的来源网络 |

普通用户、业务 Key 和逐空间授权保存在 `ctxdb_meta` 中，不通过静态环境变量逐条配置。当前未使用 `HINDSIGHT_API_TENANT_USERS`；也不要再加一套静态租户映射与动态 ContextDB 扩展混用。

## Hindsight API：原生扩展点与运行配置

下面的变量属于 Hindsight 原生扩展机制，变量所加载的 `hindsight_ext_contextdb` 类属于本次自研实现。

| 变量 | 当前配置 |
| --- | --- |
| `HINDSIGHT_API_TENANT_EXTENSION` | `hindsight_ext_contextdb.tenant:ContextDBTenantExtension` |
| `HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION` | `hindsight_ext_contextdb.validator:ContextDBOperationValidator` |
| `HINDSIGHT_API_HTTP_EXTENSION` | `hindsight_ext_contextdb.http:ContextDBHttpExtension` |
| `HINDSIGHT_API_MCP_EXTENSION` | `hindsight_ext_contextdb.mcp:ContextDBMCPExtension` |
| `HINDSIGHT_API_MCP_ENABLED` | `true` |
| `HINDSIGHT_API_WORKER_ENABLED` | `true`；当前 API 内嵌 Worker，没有独立 Worker 服务 |
| `HINDSIGHT_API_PORT` | `8888` |

tenant 扩展负责认证和 schema 路由；validator 负责空间与操作授权；HTTP 扩展提供管理 REST 和生命周期；MCP 扩展连接当前权限与原生工具能力。

## 华为云 MaaS 模型

| 用途 | 变量 | 当前配置 |
| --- | --- | --- |
| LLM | `HINDSIGHT_API_LLM_PROVIDER` | `openai`，使用兼容协议适配器 |
| LLM | `HINDSIGHT_API_LLM_BASE_URL` | `https://api.modelarts-maas.com/v2` |
| LLM | `HINDSIGHT_API_LLM_MODEL` | `deepseek-v4.1-flash` |
| LLM | `HINDSIGHT_API_LLM_API_KEY` | MaaS Key，值隐藏 |
| Embedding | `HINDSIGHT_API_EMBEDDINGS_PROVIDER` | `openai` |
| Embedding | `HINDSIGHT_API_EMBEDDINGS_OPENAI_BASE_URL` | `https://api.modelarts-maas.com/v1` |
| Embedding | `HINDSIGHT_API_EMBEDDINGS_OPENAI_MODEL` | `bge-m3` |
| Embedding | `HINDSIGHT_API_EMBEDDINGS_OPENAI_API_KEY` | MaaS Key，值隐藏 |
| Rerank | `HINDSIGHT_API_RERANKER_PROVIDER` | `siliconflow`，使用当前支持 MaaS 请求格式的适配器 |
| Rerank | `HINDSIGHT_API_RERANKER_SILICONFLOW_BASE_URL` | `https://api.modelarts-maas.com/v1` |
| Rerank | `HINDSIGHT_API_RERANKER_SILICONFLOW_MODEL` | `bge-reranker-v2-m3` |
| Rerank | `HINDSIGHT_API_RERANKER_SILICONFLOW_API_KEY` | MaaS Key，值隐藏 |
| 本地辅助 | `MAAS_API_KEY` | curl/配置准备时使用，值隐藏；Hindsight 读取上面各 provider 的专用 Key 变量 |

`openai`、`siliconflow` 在这里表示适配协议，实际请求都发往华为云 MaaS。不要将 provider 名称理解为请求发往对应厂商。

当前 **不设置** `HINDSIGHT_API_EMBEDDINGS_OPENAI_DIMENSIONS`。MaaS `bge-m3` 返回 1024 维；该变量会向模型请求发送 `dimensions` 参数，此前实测该模型不支持这个参数。Hindsight 通过响应探测维度。

## UI

| 变量 | 当前配置 | 用途 |
| --- | --- | --- |
| `HINDSIGHT_CP_CONTEXTDB_ENABLED` | `true` | 自研 UI 开关，启用当前 ContextDB 用户/Key 管理和准入边界 |
| `HINDSIGHT_CP_ACCESS_KEY` | 已设置，值隐藏 | 管理员登录 UI 的独立口令 |
| `HINDSIGHT_CP_DATAPLANE_API_KEY` | 已设置，值隐藏 | UI 服务端固定持有的实例管理员 all 业务 Key |
| `HINDSIGHT_CP_DATAPLANE_API_URL` | `http://127.0.0.1:8888` | UI 服务端访问 API 的地址 |

后三个变量为原生 UI 能力；`HINDSIGHT_CP_CONTEXTDB_ENABLED` 是本次新增开关。登录口令与 API Key 分别配置，值应不同。浏览器登录不需要输入后台 API Key。

当前浏览器地址是 `http://localhost:9999`。`9999` 是本次 UI 进程的监听端口，记录在 `runtime.json`；它不是 `HINDSIGHT_API_PORT`，也不是后端 URL。

## 查变量含义、默认值和真实生效状态

当前运行代码目录是：

```text
/Users/zhuqingping/Work/Database/Context/.local/worktrees/contextdb-tenant-admin-20261015
```

| 需要查看 | 位置，相对上述代码目录 |
| --- | --- |
| Hindsight 原生环境变量、默认值 | `hindsight-api-slim/hindsight_api/config.py` |
| 原生部署说明 | `hindsight-docs/docs/developer/configuration.mdx` |
| 自研变量校验 | `hindsight-extensions/contextdb-service/hindsight_ext_contextdb/config.py` |
| 自研 bootstrap 数据库 URL | `hindsight-extensions/contextdb-service/hindsight_ext_contextdb/__main__.py` |
| 扩展部署约定 | `hindsight-extensions/contextdb-service/README.md` |
| UI 自研开关和管理员准入 | `hindsight-control-plane/src/lib/contextdb.ts` |
| UI 固定数据面 URL / Key | `hindsight-control-plane/src/lib/hindsight-client.ts` |
| UI 登录与会话 | `hindsight-control-plane/src/lib/auth/session.ts`、`src/middleware.ts` |

例如在代码目录运行 `rg -n 'HINDSIGHT_API_DATABASE_URL|ENV_DATABASE_URL' hindsight-api-slim/hindsight_api/config.py` 查定义。

运行文件说明“启动时准备了什么”；源代码说明“如何读取及默认值”；服务启动日志、API/数据库查询说明“运行结果”。修改运行文件不会自动更新已启动进程。修改 API/UI 环境需要重启对应服务；修改 PG preload 需要重启 PG。本文只记录配置，没有执行重启。

配套：[v2 本地验证手册](contextdb-v2-local-validation-guide.md)、[v2 设计](https://github.com/ZhuQingping/ContextDB-Research/blob/main/hindsight/member-apikey-bank-service-design-v2.md)。
