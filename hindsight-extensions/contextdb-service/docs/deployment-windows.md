# Windows 原生本地启动

在 Windows 10/11 x64 的 PowerShell 中运行，不需要 WSL、Git Bash 或 Docker。
API 鉴权、UI 登录鉴权和 UI 用户管理由本地启动器强制开启；初始化失败时停止启动。

## 1. 准备依赖

安装 Git、uv，以及 Node.js 24（也接受 Node.js 22.12+），在仓库根目录执行：

```powershell
.\scripts\dev\setup.ps1
```

脚本通过 uv 准备 Python 3.11、API 和嵌入式 PostgreSQL 依赖，并安装 UI 依赖及编译 SDK。
使用远程模型时无需下载本地模型；如果使用本地 embedding/reranker，执行
`setup.ps1 -LocalModels` 安装对应依赖。首次使用本地模型时还需下载权重。

若 PowerShell 的当前执行策略阻止本地脚本，可按组织策略在当前进程允许脚本执行：
`Set-ExecutionPolicy -Scope Process Bypass`。不修改整机执行策略。

## 2. 配置 .env

在仓库根目录创建 UTF-8 编码的 `.env`，按实际模型服务填写，例如：

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
CONTEXTDB_DEPLOY_DIR=D:/ContextBase/local
```

模型名称、地址、维度和密钥按服务实际值填写。`rrf` 不调用独立重排模型；需要模型重排时按提供方配置。
省略 `CONTEXTDB_DEPLOY_DIR` 时使用当前用户的 `~/.contextbase/local`。
省略数据库 URL 时使用 Windows x64 的 pg0；数据默认位于持久化目录下的 `pgdata`，
可用 `CONTEXTDB_PG_DATA_DIR` 指定。外部 PG 可设置 `CONTEXTBASE_API_DATABASE_URL`，
必须预先安装 `vector`、`pg_trgm`、`btree_gin`；连接失败不会自动改用嵌入式 PG。

运行目录应位于本机 NTFS 磁盘。首次创建时仅授予当前用户与 SYSTEM 访问权限；
已有目录/文件权限过宽时启动会拒绝，恢复私有 ACL 后重试，不通过关闭鉴权绕过。

## 3. 启动与登录

```powershell
.\scripts\dev\start.ps1
```

首次启动自动初始化数据库、管理员 API Key 和独立 UI 登录密码，随后启动 API、内置 Worker 和 UI。
默认 API 地址为 `http://localhost:8888`，UI 为 `http://localhost:9999`。
终端显示凭据文件位置，不打印密码与密钥。

| 文件 | 用途 |
| --- | --- |
| `ui-secrets.json` 的 `password` | 浏览器 UI 登录密码 |
| `admin-key.json` 的 `secret` | 初始化管理使用的管理员 API Key |
| `api-secrets.json` | API Key 验证所需持久凭据 |
| `pg-secrets.json` | 嵌入式 PostgreSQL 凭据 |

登录后进入“用户管理”，创建业务用户与 API Key，再为业务工作空间配置访问授权。
API/MCP 客户端使用获授权的业务 Key。UI 密码和 API Key 各自独立。
健康检查允许匿名访问，业务 API 与用户管理接口仍需要鉴权。

只启动部分组件或调整端口：

```powershell
.\scripts\dev\start.ps1 -Component api
.\scripts\dev\start.ps1 -Component ui
.\scripts\dev\start.ps1 -Port 8888 -UiPort 9999
```

UI 单独启动需要已初始化并正在运行的 API；可用 `-UiPort` 覆盖本次 UI 端口。
默认本机登录 origin 跟随端口调整。通过其他主机名/代理访问时，设置
`CONTEXTBASE_CP_PUBLIC_ORIGIN` 为浏览器实际 UI origin。
接入页面的对外 API 地址使用 `CONTEXTBASE_CP_PUBLIC_API_URL` 配置。

## 4. 停止与重启

在启动终端按 Ctrl+C 停止本实例的 API/Worker/UI 及其嵌入式 PG。
重启执行同一条 `start.ps1`，保留原有用户、数据、Key、UI 密码和会话目录。
同一持久化目录只能运行一个启动器。已有数据库对应的凭据文件丢失时，需恢复一致备份；
启动器不会自动生成新密钥覆盖已有身份。外部 PG 不由启动器停止。
