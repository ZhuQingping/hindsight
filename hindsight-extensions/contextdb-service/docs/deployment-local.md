# ContextBase 本地启动（Windows / Linux）

本文是本仓库本地 API、内置 Worker 和管理 UI 的统一操作入口。使用同一 checkout 的源码，在仓库根目录执行对应系统的命令。

本地启动默认强制开启 **API/MCP 鉴权、UI 登录鉴权和 UI 用户管理**；首次自动初始化数据库与凭据，初始化失败即停止。默认 API 为 `http://localhost:8888`，UI 为 `http://localhost:9999`。

| 环境 | 安装依赖 | 启动入口 |
| --- | --- | --- |
| Windows 10/11 x64、PowerShell、可写 NTFS 目录 | [Windows 原生准备](#windows) | `scripts/dev/start.ps1`，无需 WSL、Git Bash 或 Docker |
| Linux x86_64、glibc 2.35+、非 root 用户 | [Linux 准备](#linux) | `scripts/dev/start.sh` |
| Linux/macOS 宿主进程部署、外部 PG、生产 UI 产物 | [宿主进程部署](deployment-native.md) | 独立的 intent/render/service.sh 流程 |
| Linux 容器部署 | [Docker Compose](deployment-docker.md) | 独立的镜像与挂载流程 |

本地运行按下面的“准备依赖 → 配置 .env → 启动与登录 → 停止与重启”执行。
上游原生引擎/嵌入式 SDK 的包内 Quick Start、直接运行 `hindsight-api` 或 `npm run dev`，均不能替代这里的 ContextBase 初始化和鉴权装配。
本页的本地入口验收范围为 Windows/Linux x64；macOS 宿主进程方式见上表。

## 1. 准备依赖

两种系统均需 Git、uv，以及 Node.js 24 或 22.12 及以上的 22.x。uv 会准备 Python 3.11。
先取得选定版本的源码并进入仓库根目录，再选择一个系统分支。

<a id="windows"></a>

### Windows 原生 PowerShell

```powershell
.\scripts\dev\setup.ps1
```

脚本安装锁定的 API、pg0、UI 依赖并编译 TypeScript SDK。
使用本地 embedding/reranker 时执行 `setup.ps1 -LocalModels`，首次使用还需下载模型权重。
执行策略阻止脚本时，可按组织策略在当前终端执行 `Set-ExecutionPolicy -Scope Process Bypass`。

<a id="linux"></a>

### Linux Bash

```bash
uv sync --frozen --package hindsight-api-slim --extra embedded-db --python 3.11
npm ci --ignore-scripts --include=dev --include=optional --no-audit --no-fund --workspace=contextbase-control-plane --workspace=hindsight-clients/typescript
npm run build -w contextbase-client
```

使用本地 embedding/reranker 时，在第一条命令中另加 `--extra local-ml`，首次使用时下载模型权重。
`scripts/dev/setup.sh` 用于整个仓库的开发环境，会另外准备 Rust/CLI 等工具；本地服务的最小依赖按本节安装。

## 2. 配置 .env

在仓库根目录创建 UTF-8 编码的 `.env`。使用远程模型时，按实际服务填写：

```dotenv
CONTEXTBASE_API_LLM_PROVIDER=openai
CONTEXTBASE_API_LLM_BASE_URL=https://your-model-service.example/v1
CONTEXTBASE_API_LLM_MODEL=your-model
CONTEXTBASE_API_LLM_API_KEY=your-model-key
CONTEXTBASE_API_EMBEDDINGS_PROVIDER=openai
CONTEXTBASE_API_EMBEDDINGS_OPENAI_BASE_URL=https://your-embedding-service.example/v1
CONTEXTBASE_API_EMBEDDINGS_OPENAI_MODEL=your-embedding-model
CONTEXTBASE_API_EMBEDDINGS_OPENAI_API_KEY=your-embedding-key
CONTEXTBASE_API_EMBEDDINGS_OPENAI_DIMENSIONS=1024
CONTEXTBASE_API_RERANKER_PROVIDER=rrf
```

地址、模型、维度与密钥替换为服务实际值。`rrf` 不调用独立重排模型；使用本地模型或其他提供方时，按对应 provider 配置并安装所需依赖。

### 持久化目录与数据库

| 配置 | 默认值 | 用途 |
| --- | --- | --- |
| `CONTEXTDB_DEPLOY_DIR` | 当前用户的 `~/.contextbase/local` | 运行配置、凭据与会话目录 |
| `CONTEXTDB_PG_DATA_DIR` | 持久化目录下的 `pgdata` | 内置 PG 数据 |
| `CONTEXTBASE_API_DATABASE_URL` | `pg0` | 内置 PG；填写明确的 PostgreSQL URL 则使用外部 PG |

在同一份 `.env` 中按需设置目录，例如 Windows 的 `CONTEXTDB_DEPLOY_DIR=D:/ContextBase/local`，或 Linux 的 `CONTEXTDB_DEPLOY_DIR=/data/contextbase/local`；替换为本机当前账号可写的专用路径。

- **Windows：**目录位于本机 NTFS。建议路径只含英文、数字和空格。内置 PostgreSQL 受系统代码页限制；启动器会尝试兼容的 NTFS 短路径，无法使用时明确提示改用 ASCII 路径。此时同时检查持久化目录与 PG 数据目录，保留已有数据和凭据。
- **Linux：**目录权限为 0700、秘密文件为 0600，pg0 以非 root 用户运行。
- 新目录由启动器设置私有权限；已有目录/文件权限过宽时拒绝启动，修复权限后重试。
- pg0 的注册表与二进制缓存隔离在持久化目录的 `pg0-home` 中。
- 内置 PG 自动启用 `vector`、`pg_trgm`、`btree_gin`。外部 PG 须预先提供这些扩展；连接或鉴权失败不会自动回退到 pg0。
- 默认 native 全文检索不提供中文分词；中文全文检索需要另配支持的搜索扩展。

启动器根据本次配置生成 `api.env` / `ui.env`。本地设置写入仓库根目录的 `.env`，修改后重启；生成的运行文件不作为手工配置入口。

## 3. 启动与登录

依赖与 `.env` 准备完成后，在仓库根目录执行所属系统的一条命令：

```powershell
# Windows PowerShell
.\scripts\dev\start.ps1
```

```bash
# Linux Bash
bash scripts/dev/start.sh
```

首次启动自动准备 PG、管理元数据、管理员 API Key 与独立 UI 密码，随后启动 API、内置 Worker 和开发 UI。终端显示服务地址及凭据文件位置，不打印密码和密钥。

1. 打开终端显示的 UI 地址，默认 `http://localhost:9999`。
2. 用本机编辑器打开该实例的 `ui-secrets.json`，使用 `password` 字段登录。
3. 创建工作空间，在“用户管理”创建业务用户，并为其签发指定空间及只读/读写权限的业务 Key。
4. 应用/Agent 使用该业务 Key 接入；实际写入与召回按[业务接入](../README.md#business-quickstart)验证。

| 文件 | 用途 |
| --- | --- |
| `ui-secrets.json` 的 `password` | 管理 UI 登录密码 |
| `admin-key.json` 的 `secret` | UI 服务端及受控运维使用的管理员 API Key |
| `api-secrets.json` | API Key 验证所需持久凭据 |
| `pg-secrets.json` | 内置 PG 凭据；使用外部 PG 时不生成 |

UI 密码、Admin Key 和业务 Key 各自独立。健康检查允许匿名访问，业务 API/MCP 与用户管理接口要求鉴权。
初始化/健康检查通过只表示服务就绪，模型调用与业务权限仍需完成上述业务验证。

## 4. 分开启动、端口与访问地址

| 任务 | Windows PowerShell | Linux Bash |
| --- | --- | --- |
| API 与内置 Worker | `.\scripts\dev\start.ps1 -Component api` | `bash scripts/dev/start-api.sh` |
| UI | `.\scripts\dev\start.ps1 -Component ui` | `bash scripts/dev/start-control-plane.sh` |
| 指定 API/UI 端口 | `.\scripts\dev\start.ps1 -Port 8888 -UiPort 9999` | `bash scripts/dev/start.sh --port 8888 --ui-port 9999` |
| 自动分配端口 | `.\scripts\dev\start.ps1 -RandomPort` | `bash scripts/dev/start.sh --random-port` |

UI 单独启动需要已初始化并正在运行的 API。UI 单独启动时用 `-UiPort` / `--ui-port` 或随机端口参数调整本次 UI 端口，不改写持久配置中的 API 地址。

API/UI 监听地址分别使用 `CONTEXTBASE_API_HOST` / `CONTEXTBASE_CP_HOST`。默认本机 UI 登录 origin 跟随端口调整；通过其他主机名或代理访问时，在 `.env` 中设置 `CONTEXTBASE_CP_PUBLIC_ORIGIN` 为浏览器实际 origin。
接入页面展示的对外 API 地址使用 `CONTEXTBASE_CP_PUBLIC_API_URL`，它与 UI 服务端访问 API 的内部地址分开配置。

## 5. 停止、重启与恢复

在启动终端按 Ctrl+C，停止本实例 API/Worker/UI，再停止它拥有的内置 PG。外部 PG 不由启动器停止。

重启执行同一条 `start.ps1` 或 `start.sh`，沿用原持久化目录、用户、数据、Key、UI 密码与会话目录。同一目录只允许一个启动器运行。

备份包含完整数据库及匹配的运行配置和凭据，不只保存 `pgdata`。已有数据库对应的秘密文件丢失时恢复一致备份；启动器不会通过重新生成密钥覆盖旧身份。更换数据目录会选择另一份状态，不能用它恢复原实例。
