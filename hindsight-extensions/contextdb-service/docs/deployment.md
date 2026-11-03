# ContextBase 部署总览（宿主进程 / Docker）

本地运行 API、内置 Worker 和管理 UI，使用[本地启动指南（Windows / Linux）](deployment-local.md)，其中统一说明依赖、.env、自动初始化及鉴权。
以下内容面向使用外部 PG、intent 配置及生产 UI 产物的服务运营者与贡献者。插件可以由宿主进程或 Docker 运行，两种方式共用同一套配置、离线初始化、权限与业务接口；API 使用 Python，UI 使用 Node.js，API 内置 Worker。已有服务的应用用户直接看[业务接入](../README.md#business-quickstart)，管理员看[UI 操作](../README.md#admin-quickstart)。

所有运行组件使用同一份源码版本；设计与生命周期以[唯一 DESIGN](../../../docs/contextdb-management/DESIGN.md#overview)为准，接口以[同版 OpenAPI](../schemas/contextdb-control-plane.openapi.yaml)为准。原生上游镜像或另一版本的 UI 不保证匹配。资料仓的旧指南仅提供背景。

<a id="先明确这次要做什么"></a>

## 先选择部署方式

| 场景 | 阅读路径 |
| --- | --- |
| Windows 原生 / Linux 本地运行 | [统一本地启动指南](deployment-local.md)，配置 .env 后自动初始化 |
| Linux/macOS 宿主服务、外部 PG 与生产 UI 产物 | [宿主进程部署](deployment-native.md)，复用现有 Bash/Python 启动脚本 |
| Linux 容器交付 | [Docker Compose 部署](deployment-docker.md)，从同一源码构建镜像 |
| 已经部署，只需启停或更新 | 对应指南的启停章节，以及本页[更新与恢复边界](#8-停止重启与版本更新) |

宿主进程或 Docker 首次部署的阅读顺序：本页了解共同前提和配置 → 选择一种部署指南完成服务检查 → [管理员创建空间和业务 Key](../README.md#admin-quickstart) → [业务写入与召回](../README.md#business-quickstart)。无需把两种部署方式都执行一遍。

宿主进程流程面向 Linux/macOS 的 POSIX 环境；Windows 原生本地运行按[本地指南的 PowerShell 章节](deployment-local.md#windows)执行，无需 WSL。macOS 可通过已有 Colima 等 Linux 虚拟机使用 Docker，但 Linux Docker 示例的宿主路径、UID/GID、共享目录和 PG 地址需适配，不能原样照搬。

> 验证状态：文档、命令语法和临时虚构输入的配置生成可独立检查；完整安装、UI 构建、服务启停、PG/MaaS 及业务调用需在隔离环境执行并分别记录。本轮不启停现有服务，未运行的环节不标为通过。两种流程的目标平台不等于所有系统版本和架构都已实测。

## 1. 前提与支持范围

- 使用独立实例的 UTF8 PostgreSQL 和服务账号，目标库启用 `vector`、`pg_trgm`、`btree_gin`。服务账号需要自己数据库内的 schema/DDL 权限，无需 SUPERUSER。数据库和扩展由 PG 管理员准备。
- 当前生成器固定 `topology=merged`、`text_search=native`、`language=english`。`merged` 使用 API 内置 Worker 和配套 UI；容器与宿主进程运行方式都复用此配置。`english` 是全文验收范围，不禁止中文输入或中文向量召回。
- 模型预设固定为华为 MaaS：OpenAI 兼容 LLM（默认 `deepseek-v4.1-flash`）、`bge-m3` Embedding、siliconflow 兼容接口的 `bge-reranker-v2-m3`。需有可用模型权限与配额；生成器默认不是 RRF，没有通用 provider/base URL 的 intent 字段。
- 从 API 运行环境可达 PG 和 MaaS。宿主进程的 localhost 指宿主；容器内的 localhost 指容器自身。
- 对外 TLS、入口限制及备份由运营方提供。HTTP 本机示例只用于试用；交付公网时应配置真实入口。

<a id="pg-preparation"></a>

## 2. 准备 PG 与私密输入

### PG 管理员：仅在首次创建新库时执行

[prepare-pg.sql](../deployment/prepare-pg.sql)创建新账号、新库和扩展，同名对象存在即停止，不接管旧库；脚本不是已有数据库的修复命令。先在 PG 服务端安装扩展文件，托管 PG 由有权限的管理员启用扩展。`service.sh init` 不执行 CREATE DATABASE。

在仓库根目录的 Bash 执行下面示例。`contextdb-provisioner` 是 PG 管理员事先配置、指向维护库的 libpq service 名；使用受保护的 libpq 密码文件等方式提供认证。客户端 psql 需支持脚本使用的 `\getenv`。

```bash
read -r -s -p 'New ContextDB service-role password: ' CONTEXTDB_NEW_DB_PASSWORD
export CONTEXTDB_NEW_DB_PASSWORD
psql 'service=contextdb-provisioner' \
  -v service_role=contextdb_service -v service_db=contextdb \
  -f hindsight-extensions/contextdb-service/deployment/prepare-pg.sql
unset CONTEXTDB_NEW_DB_PASSWORD
```

失败后由 PG 管理员核对已创建对象，不盲目重跑或删除数据库。若由其他管理员已准备全新专用库，核对上面的前提后跳过创建脚本。允许客户 SQL 账号直连时，另评估[pg-role-boundary.sql](../deployment/pg-role-boundary.sql)；仅通过 API 使用无需执行这个权限示例。

### 运营者：准备三个输入文件

| 私密输入 | 内容 |
| --- | --- |
| `database-url` | 目标服务账号 URL，例如 `postgresql://contextdb_service:<URL编码后的密码>@<PG主机>:5432/contextdb`；按 PG TLS 策略显式提供 SSL 参数 |
| `maas-key` | 有权限的华为 MaaS Key |
| `ui-password` | 独立 UI 密码，至少 12 字符，不以 `ctx_admin_`、`ctx_live_`、`ctx_ctrl_` 开头；不是 API Key |

文件内容是一行，权限 0600，允许一个结尾换行。秘密不放进版本库、聊天或普通日志；输入和运行目录由实际部署账号访问。各部署指南说明如何选路径和复制输入。不要从其他实例复制 pepper/秘密来创建新实例；已有实例秘密丢失时恢复本实例的一致备份。

<a id="3-从同一源码构建镜像"></a>

## 3. 构建与运行入口

按所选方式执行一条路径：

- [宿主进程依赖与 UI 构建](deployment-native.md#native-build)：Python 3.11～3.14（示例选 3.11）、uv、Node 24 或 Node 22.12 及以上的 22.x、npm、Bash。无需 Docker。
- [Docker 镜像构建](deployment-docker.md#3-从同一源码构建镜像)：Linux、Docker BuildKit/Compose v2；镜像内构建匹配 Python 和 Node UI。

API/UI/扩展都来自同一源码版本。Node 23 不在当前 UI 构建预检接受范围内；“本机某个旧产物能启动”不代表新构建已验证。

<a id="4-配置意图校验与渲染"></a>

## 4. 配置意图、校验与渲染

主要编辑文件是从[意图示例](../deployment/intent.example.json)创建的 `intent.json`。路径是 **render 进程能看到的绝对路径**；JSON 不展开 `$HOME` 等 Shell 变量。`ui_session_dir` 则是 **UI 运行进程**使用的绝对路径：宿主方式填真实宿主目录，容器方式填容器内路径。

| 字段 | 含义 |
| --- | --- |
| `instance_id` / `cloud_tenant_id` | 实例与归属标识，初始化后不可通过改 ID 接管旧库 |
| `database_url_file` / `maas_api_key_file` / `ui_password_file` | 上述三个输入文件的绝对路径 |
| `api_port` / `ui_port` | 默认 8888/9999，彼此不同；Docker 发布端口须一致 |
| `ui_api_url` | UI 服务端访问 API 的内部 origin，如 `http://127.0.0.1:8888` |
| `ui_public_origin` | 浏览器实际访问 UI 的 origin，含端口；远程部署不要照抄 localhost，公网使用 TLS 入口 |
| `ui_session_dir` | UI 私有可写会话目录，宿主与容器路径按相应指南设置 |
| `worker_id` | 本实例 Worker 标识 |
| `db_pool_max` | 每个相关连接池上限，不是实例总连接数 |
| `llm_model` | 华为预设内的 LLM 名称，不改变 Embedding/reranker |
| `recall_usage_enabled` | 布尔值，默认 false；启用召回统计 |
| `topology` / `text_search` / `language` | 当前固定 `merged` / `native` / `english` |
| `ca_bundle_file`（可选） | 私有 CA 绝对路径；相关校验、初始化、运行、status 进程均须能访问；容器需额外挂载同一路径 |

两种指南都调用已有 validate/render；成功输出 `ok:true`。render 只准备 `api.env`、`ui.env` 和会话目录，不创建 PG 管理表或管理员。未知 intent 字段会被拒绝，不能把任意环境变量加到 JSON 中。

<a id="configuration"></a>

## 5. 配置如何生效

```text
intent.json + 三个私密输入文件
  → validate / render
  → api.env、ui.env
  → init 持久化实例秘密并初始化 PG
  → service.sh 导出配置 → 启动器加载秘密 → Python API / Node UI
```

[contextdb.env.example](../deployment/contextdb.env.example)是补充参考，不自动加载，也不是复制后即可启动的完整 `.env`。插件配置由同一个生成器维护，两种部署方式不各写一套变量。

<a id="plugin-configuration"></a>

### 5.1 插件具体如何启用、配置在哪里

**运行 render 后，四个扩展槽自动写入生成的 `api.env`；无需在 intent 或 UI 配置中重复填写。** [生成器](../hindsight_ext_contextdb/deployment.py)写入：

```sh
HINDSIGHT_API_TENANT_EXTENSION=hindsight_ext_contextdb.tenant:ContextDBTenantExtension
HINDSIGHT_API_OPERATION_VALIDATOR_EXTENSION=hindsight_ext_contextdb.validator:ContextDBOperationValidator
HINDSIGHT_API_HTTP_EXTENSION=hindsight_ext_contextdb.http:ContextDBHttpExtension
HINDSIGHT_API_MCP_EXTENSION=hindsight_ext_contextdb.mcp:ContextDBMCPExtension
```

| 配置 | 职责 |
| --- | --- |
| `TENANT_EXTENSION` | 认证 Key，将目标空间路由到 PG schema |
| `OPERATION_VALIDATOR_EXTENSION` | 原生操作入口的空间、读写与管理权限检查 |
| `HTTP_EXTENSION` | 装配管理 HTTP 接口及工作空间管理能力 |
| `MCP_EXTENSION` | 原生 MCP 工具的空间选择与权限规则 |

值采用 `Python模块:类名`，API 通过 `PYTHONPATH` 导入。宿主方式由 [service.sh](../scripts/service.sh)设置源码路径；容器由 [Dockerfile](../deployment/Dockerfile)复制模块并设置路径。API 分支使用 `set -a` 和 `. "$DEPLOY/api.env"` 导出配置；[launch.py](../hindsight_ext_contextdb/launch.py)启动 `uvicorn hindsight_ext_contextdb.asgi:create_app --factory`，装配原生 API 与插件保护层。

配套生成 `HINDSIGHT_API_MCP_ENABLED=true`、`HINDSIGHT_API_WORKER_ENABLED=true`、`HINDSIGHT_API_RUN_MIGRATIONS_ON_STARTUP=false`。四项扩展作用于 API（含内置 Worker），无需加入 `ui.env`。同版模块、四项设置、离线初始化、专用 ASGI 和匹配 UI 共同构成部署；只装 Python 模块或给原生启动命令补四个变量不足以完成部署。

容器的镜像复制、文件挂载和 ENTRYPOINT 链路见[Docker 指南](deployment-docker.md#docker-plugin-loading)；宿主流程直接读取运行目录中的同一份配置。

<a id="52-如何检查生成与挂载结果"></a>

### 5.2 如何检查生成配置

由可读运行目录的部署账号执行，只输出扩展类路径，不打印 PG、模型或凭据。变量在所选指南中定义：

```bash
awk -F= '/^HINDSIGHT_API_(TENANT_EXTENSION|OPERATION_VALIDATOR_EXTENSION|HTTP_EXTENSION|MCP_EXTENSION)=/ {print}' \
  "$CONTEXTDB_DEPLOY_DIR/api.env"
```

预期四项与上面一致。Docker 宿主若文件归容器 UID 所有，需以有权限的账号检查，容器内检查见 Docker 指南。这里验证生成文件，不能代替进程身份或业务验证。

`service.sh` 在启动时导出变量；新开的 Shell、`docker exec env` 或 `docker inspect Config.Env` 不完整反映 API 后来继承的环境。自行设置高优先级别名时，还须按下表检查是否遮蔽生成值。

### 5.3 其他配置来源与公开连接设置

| 来源 | 用途与优先规则 |
| --- | --- |
| `api.env` | PG、模型、实例、扩展和 Worker，由脚本显式 source |
| `ui.env` | UI 认证、内部 API、浏览器 origin、会话路径，由 UI 路径显式 source |
| `CONTEXTBASE_API_*` / `CONTEXTBASE_CP_*` | 对相应 `HINDSIGHT_*` 兼容变量优先，存在即优先，包括空字符串；避免冲突遗留值 |
| `CONTEXTDB_*` | 按各自插件字段规则读取，不能泛化套用前缀映射 |
| `api-secrets.json` | API/Worker 的 pepper，由持久秘密加载 |
| `ui-secrets.json` | UI 启动时覆盖两套前缀的密码和后台 Admin Key；仅改 ui.env 不能改密 |
| `admin-key.json` | 运维保存的管理员凭据，与 PG/UI 匹配，不交给业务应用 |

`init` 首次准备三个 JSON 秘密，目录 0700、文件 0600。启动前设置 `PYTHON_DOTENV_DISABLED=1`，阻止意外加载其他 `.env`。凭据与改密规则见[设计 2.2～2.4](../../../docs/contextdb-management/DESIGN.md#22-三种凭据及保存位置)。

按实际对外入口编辑运行目录下的 `ui.env`，再按所选指南重新加载 UI；只加入已确认可用的设置：

```sh
CONTEXTBASE_CP_PUBLIC_API_URL=https://api.example.com
CONTEXTBASE_CP_PUBLIC_MCP_URL=https://mcp.example.com/mcp/{bank_id}/
# 可选：固定客户端版本；省略时使用 @latest。
CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE=@huaweicloud/contextbase-coding-agents@1.0.0
```

域名是占位符。公开 API/MCP 不回退到内部 `DATAPLANE_API_URL`；缺失或非法时对应示例隐藏，生产要求 HTTPS。MCP 地址独立提供，不能从 REST 猜测。UI 后台 `DATAPLANE_API_KEY` 不交给客户。下载参数按模板逐项确认可用后加入，示例 URL 不是发布证明。

显式空别名会遮蔽兼容值，但后续行为各字段不同：公开地址空会隐藏示例，Coding Agents 包空仍回退到 `@huaweicloud/contextbase-coding-agents@latest`，不是关闭开关。

**重新生成：**内容相同不修改，不同默认拒绝。替换时先停止受影响组件，再显式 render `--replace`；不合并人工追加项，替换后须补回公开连接等设置。普通 render 不负责秘密轮换，UI 密码输入与持久密码不一致会拒绝；不能靠反复 init 重置旧实例凭据。

原生引擎支持其他 provider 不等于本生成器支持通用 MaaS；人工修改模型配置属于另行适配，后续 render 不保留。通用 MaaS/RRF 参数化不在本文实施。

## 6. 离线初始化，再启动

两种方式共用 `preflight → prepare → migrate`：初始化/核验 `ctxdb_meta` 六表、管理员及四个共享维护函数。不创建数据库或 public 业务表；空间创建时初始化 `ctxdb_ws_<bank_id>`。秘密丢失、绑定不匹配或结构不支持时停止，恢复匹配备份或诊断，不手改版本号绕过。

操作命令分别见[宿主进程初始化与启动](deployment-native.md#native-start)和[Docker 初始化与启动](deployment-docker.md#6-离线初始化再启动)。普通重启复用秘密，不重复生成配置或初始化。

## 7. 验证与交付

先验证服务 readiness 和实例身份，再由管理员创建空间/用户/读写业务 Key，最后使用业务身份完成 Retain→完成→Recall；只读 Key 另验证读取授权。各指南提供可执行健康/status 命令。

readiness、UI probe 和 status 都不证明模型或 Worker 实际执行成功。异步操作确认 `completed` 后再查询，失败或超时不能当成功；观察/知识生成可能更晚，空知识树合法。插件不自动保证 Agent 执行“先查知识再召回”。

只向业务用户交付对外端点、bank_id、业务 Key；管理员取得 UI 地址与密码。记录源码提交、构建产物标识、配置版本及验证结果，不公开秘密。客户步骤和示例见[管理员操作](../README.md#admin-quickstart)、[业务接入](../README.md#business-quickstart)。

## 8. 停止、重启与版本更新

先阻止新业务并等待已有请求和后台工作结束；插件没有额外全局排空屏障。停止方式见[宿主进程](deployment-native.md#native-stop)或[Docker](deployment-docker.md#8-停止重启与版本更新)，只操作所属实例，不使用按进程名全局 kill。

更新前备份 ctxdb_meta、所有业务 schema 及匹配配置和秘密；单 Bank 导出不是完整实例备份。API、扩展、UI 保持同版，核对目标版本迁移要求。不要运行 `run-db-migration --schema public` 升级插件，不删除 public，不承诺滚动升级或任意降级；恢复使用数据库/产物/秘密的一致备份。Bank 管理中断核查见[设计 8.13](../../../docs/contextdb-management/DESIGN.md#bank-rest-interrupted-cleanup)。

## 9. 开发与排障入口

- [唯一 DESIGN](../../../docs/contextdb-management/DESIGN.md#overview)、[生成器模型](../hindsight_ext_contextdb/deployment.py)、[测试入口](../README.md#测试入口)、[验证入口与边界](../../../docs/contextdb-management/VALIDATION.md)、[云环境交付待办](../../../docs/contextbase/CLOUD-READINESS.md)。
- 预检区分依赖、源码路径、PG 扩展和权限；业务失败区分网络、Key 授权、后台任务和模型调用。
- 本页保留原部署链接的重要锚点；原 Docker 操作已移至 Docker 指南，宿主用户按宿主指南执行，不把两个执行环境的命令混用。
