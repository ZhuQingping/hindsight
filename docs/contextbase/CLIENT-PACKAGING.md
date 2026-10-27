# ContextBase 客户端安装包生成与交付

本文面向服务提供方。客户安装和记忆使用示例见[客户使用指南](CUSTOMER-GUIDE.md)。

## 构建安装包

使用完整仓库，推荐 Linux 或 WSL，准备 Node.js 24、npm 和 Python 3.12（以下命令中的 `python` 应指向该版本）。需要访问 npm 下载依赖。

在包含本次安装器修改的版本上构建；PR #23 合并前使用 `fix/contextbase-customer-onboarding` 分支。以下命令从仓库根目录执行：

```bash
npm ci --ignore-scripts
(
  cd hindsight-integrations/coding-agents
  npm ci --ignore-scripts --workspaces=false
  npm run clean
  npm run skill:build
  npm run typecheck
  npm run build
  npm test
)
python scripts/package-client-plugins.py --output artifacts
```

构建或测试失败时应先修复，不要继续交付。打包脚本会检查品牌生成文件、补入许可证，并生成安装包和校验文件。它也会生成另外两个插件的 ZIP；使用客户指南中的安装方式只需交付 Coding Agents 的 tgz 和 SHA256SUMS。

当前 `hindsight-integrations/coding-agents/package.json` 的版本为 `0.8.1`，对应输出：

```text
artifacts/contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz
artifacts/contextbase-coding-agents/0.8.1/SHA256SUMS
```

`contextbase-coding-agents-版本.tgz` 中的“版本”是占位符。实际名称来自 package.json 的 `version`，不要只重命名文件冒充新版本。

底层使用 `npm pack --ignore-scripts --workspaces=false`，因此必须先构建 `dist`；直接压缩源码不能替代这个安装包。无需发布到 npm，也不需要把服务地址、业务 Key 或客户 Bank 写入包中。

## 校验与验收

在仓库根目录执行，版本变化时替换路径：

```bash
(cd artifacts/contextbase-coding-agents/0.8.1 && sha256sum -c SHA256SUMS)
node hindsight-integrations/coding-agents/scripts/test-customer-install.mjs
```

安装冒烟测试会从当前构建重新打包，在临时配置中验证安装与本地 MCP 的跨客户端读写。它使用测试 HTTP 服务，不能替代真实云服务验收。

交付前，另用测试账号、测试 Bank 和最终下载地址，按[客户使用指南](CUSTOMER-GUIDE.md)完成 Claude Code 保存、Codex 新会话查询。确认 Bank 授权正确、服务可达，且下载文件的校验值与构建产物一致。

## 发布下载地址

将 tgz 和 SHA256SUMS 上传到对象存储或下载站，提供客户可访问的 HTTPS 地址。不要覆盖已交付版本；更新时发布新版本路径。

控制台服务配置示例：

```dotenv
CONTEXTBASE_CP_CODING_AGENTS_PACKAGE_URL=https://downloads.example.com/contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz
CONTEXTBASE_CP_OPENCLAW_PACKAGE_URL=https://downloads.example.com/contextbase-openclaw/1.0.0/contextbase-openclaw-1.0.0.tgz
CONTEXTBASE_CP_HERMES_PACKAGE_URL=https://downloads.example.com/hermes-plugin-contextbase/1.2.2/hermes-plugin-contextbase-1.2.2.zip
CONTEXTBASE_CP_PYTHON_SDK_PACKAGE_URL=https://downloads.example.com/contextbase-client/1.0.0/contextbase_client-1.0.0-py3-none-any.whl
CONTEXTBASE_CP_NODE_SDK_PACKAGE_URL=https://downloads.example.com/contextbase-client/1.0.0/contextbase-client-1.0.0.tgz
```

这些变量分别对应 Coding Agents、OpenClaw、Hermes、Python SDK 和 Node.js SDK。版本以实际构建产物为准，页面命令使用配置的完整地址，不假定包已公开发布到 npm 或 PyPI。地址须指向表中对应的实际安装文件；不能使用 Actions 页面地址或其外层 artifact ZIP。缺少某个包地址时，页面会提示该客户端安装包暂未提供，其他客户端仍可使用。

API 地址由 `CONTEXTBASE_CP_PUBLIC_API_URL` 配置；需要远端 MCP 时另设 `CONTEXTBASE_CP_PUBLIC_MCP_URL`，不要从 API 地址推导。所有地址须为客户可访问的 HTTPS URL，不含用户名、密码或 fragment；API/MCP 地址不接受 query，下载地址允许签名 query。

把变量写入控制台实际加载的环境配置（部署脚本方式为持久目录中的 `ui.env`），再按部署方式重启控制台。编辑 `contextdb.env.example` 不会更新已运行的服务。下载地址会交给浏览器和客户端，不应放入服务端管理凭据；签名下载链接须在客户安装时仍有效。

接入页按客户端提供命令或代码，API Key 始终保留 `<API_KEY>` 占位符，不读取控制台管理 Key。项目型 Agent 命令只安装选中客户端，并通过 `--bank-id` 与 `--project-path '.'` 绑定当前项目；OpenClaw/Hermes 使用各自的宿主设置。CMD 遇到会被终端展开的特殊字符时提示改用 PowerShell。

向客户交付安装包地址、SHA256SUMS、API Endpoint、业务 API Key 和已授权的 Bank ID，并附客户指南。

## 使用 GitHub Actions 构建

也可在 Actions 中运行 **Build contextbase client candidates**，选择包含修改的分支，完成后下载 `contextbase-plugin-candidates` artifact，其中包含安装包和校验文件。

此工作流只生成候选产物，不会自动发布到 npm 或对象存储。仍需完成上面的真实服务验收和下载地址发布。

实现入口：[打包脚本](../../scripts/package-client-plugins.py)、[构建工作流](../../.github/workflows/release.yml)。

## Python 与 Node.js SDK

同一工作流中的 `sdk-python` 和 `sdk-node` 分别生成以下独立 artifact：

| Artifact                           | 文件                                                                              |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| `contextbase-python-sdk-candidate` | `1.0.0/contextbase_client-1.0.0-py3-none-any.whl`、源码包 `.tar.gz`、`SHA256SUMS` |
| `contextbase-node-sdk-candidate`   | `1.0.0/contextbase-client-1.0.0.tgz`、`SHA256SUMS`                                |

版本取自各 SDK 的 manifest。Python 导入名为 `contextbase_client`，低层接口为 `contextbase_client_api`；Node.js 包名为 `contextbase-client`，支持 ESM、CommonJS 和 TypeScript 类型声明。

本地构建入口：

```bash
python -m pip install build
python scripts/package-sdks.py python --output artifacts
(cd hindsight-clients/typescript && npm ci --ignore-scripts --workspaces=false)
python scripts/package-sdks.py node --output artifacts
```

出包任务扫描归档内的文件名和内容，检查旧 SDK 名称，并在独立临时目录安装 wheel、源码包和 tgz，验证自定义 Endpoint、Bearer 鉴权、User-Agent 及服务响应/错误原文。这里使用本地 HTTP 测试服务，不替代真实云服务验收。安装与调用示例见 [Python SDK](../../hindsight-clients/python/README.md) 和 [Node.js SDK](../../hindsight-clients/typescript/README.md)。


## OpenClaw 与 Hermes

| Artifact | 内容 | 安装方式 |
| --- | --- | --- |
| `contextbase-openclaw-candidate` | `contextbase-openclaw-版本.tgz`、校验文件 | OpenClaw 插件管理器；tgz 内置 Node SDK |
| `contextbase-hermes-candidate` | `hermes-plugin-contextbase-版本.zip`、校验文件 | Hermes 用户插件目录；ZIP 包含 Python SDK wheel，交由 Hermes 管理依赖 |

`assistant-openclaw`、`assistant-hermes` 两个任务分别执行源代码测试、SDK 构建、静态产物品牌扫描及源码目录外的实际安装和 HTTP 验证。HTTP 验证使用业务 Key、服务路径前缀和指定 Bank；测试故意包含旧品牌词的客户文本，以确认没有运行时过滤。

其余 8 个宿主继续共用 `contextbase-coding-agents`。包安装验证覆盖 8 个 harness 的 MCP 诊断身份；原生插件生命周期使用仓库现有宿主协议测试。此验证不等价于所有真实宿主版本或 Windows 实机认证。

客户操作见 [客户使用指南](CUSTOMER-GUIDE.md)。OpenClaw、Hermes 配置分别由宿主管理，不自动继承 Coding Agents 的连接文件。服务部署和 Bank 授权由服务方完成；客户端发行包不携带本地引擎。
