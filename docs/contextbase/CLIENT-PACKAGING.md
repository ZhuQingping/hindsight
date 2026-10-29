# ContextBase 客户端发布与交付

本文面向服务提供方。客户接入命令见[客户使用指南](CUSTOMER-GUIDE.md)。

## Coding Agents：通过 npm 交付

接入页默认使用 `contextbase-coding-agents@latest`，不需要配置下载地址或 npm 包名。
需要固定版本时，在控制台进程的环境配置（部署脚本方式为 `ui.env`）中设置并重启控制台：

```dotenv
CONTEXTBASE_CP_CODING_AGENTS_NPM_PACKAGE=contextbase-coding-agents@1.0.0
```

未设置或留空时使用 `@latest`。固定版本必须已发布到 npm。Coding Agents 不再读取 tgz 下载地址，也不在接入页展示备用下载命令。API Endpoint 仍由 `CONTEXTBASE_CP_PUBLIC_API_URL` 提供，业务 API Key 和已授权 Bank ID 由服务方交付；npm 包不携带这些客户配置。

在 GitHub Actions 运行 **Build and publish Coding Agents npm package**。默认只构建、审计并测试；开启 `publish` 后使用仓库的 `NPM_TOKEN` 发布通过验证的同一份 tgz。客户不需要这个发布 Token。

发布目录由[打包脚本](../../scripts/package-coding-agents.py)生成，仅包含远端客户端运行文件、Skill、Hook、公开说明和许可证。源码包保持私有；不要从源码目录直接执行 npm publish。构建产生的 tgz 是发布产物，不是控制台接入页所需的下载配置。

发布前使用最终包验证安装、MCP 工具和真实云端 Bank 权限。现有自动冒烟测试使用 HTTP 测试服务，不能替代真实服务验收。

## 其他客户端的下载配置

OpenClaw、Hermes 和 Python/Node.js SDK 继续使用各自的分发文件。它们与 Coding Agents 的 npm 接入独立配置：

```dotenv
CONTEXTBASE_CP_OPENCLAW_PACKAGE_URL=https://downloads.example.com/contextbase-openclaw/1.0.0/contextbase-openclaw-1.0.0.tgz
CONTEXTBASE_CP_HERMES_PACKAGE_URL=https://downloads.example.com/hermes-plugin-contextbase/1.2.2/hermes-plugin-contextbase-1.2.2.zip
CONTEXTBASE_CP_PYTHON_SDK_PACKAGE_URL=https://downloads.example.com/contextbase-client/1.0.0/contextbase_client-1.0.0-py3-none-any.whl
CONTEXTBASE_CP_NODE_SDK_PACKAGE_URL=https://downloads.example.com/contextbase-client/1.0.0/contextbase-client-1.0.0.tgz
```

下载地址须指向客户可访问的 HTTPS 安装文件，可使用有效的签名 query，不得包含服务端管理凭据。缺少地址时仅对应客户端不可用。将配置写入实际加载的 `ui.env` 后重启控制台；修改示例文件不会更新运行中的服务。

API 地址通过 `CONTEXTBASE_CP_PUBLIC_API_URL` 配置；远端 MCP 另设 `CONTEXTBASE_CP_PUBLIC_MCP_URL`，不从 API 地址推导。接入页保留业务 Key 占位符，只生成选中客户端的安装命令。API Endpoint、Bank ID 和项目路径在命令后的文字中说明，安装命令不会自动绑定当前工作空间。

使用 **Publish Contextbase Clients** 工作流发布其他客户端文件及校验文件；完整构建入口见[工作流](../../.github/workflows/release.yml)。

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

| Artifact                         | 内容                                           | 安装方式                                                             |
| -------------------------------- | ---------------------------------------------- | -------------------------------------------------------------------- |
| `contextbase-openclaw-candidate` | `contextbase-openclaw-版本.tgz`、校验文件      | OpenClaw 插件管理器；tgz 内置 Node SDK                               |
| `contextbase-hermes-candidate`   | `hermes-plugin-contextbase-版本.zip`、校验文件 | Hermes 用户插件目录；ZIP 包含 Python SDK wheel，交由 Hermes 管理依赖 |

`assistant-openclaw`、`assistant-hermes` 两个任务分别执行源代码测试、SDK 构建、静态产物品牌扫描及源码目录外的实际安装和 HTTP 验证。HTTP 验证使用业务 Key、服务路径前缀和指定 Bank；测试故意包含旧品牌词的客户文本，以确认没有运行时过滤。

其余 8 个宿主继续共用 `contextbase-coding-agents`。包安装验证覆盖 8 个 harness 的 MCP 诊断身份；原生插件生命周期使用仓库现有宿主协议测试。此验证不等价于所有真实宿主版本或 Windows 实机认证。

客户操作见 [客户使用指南](CUSTOMER-GUIDE.md)。OpenClaw、Hermes 配置分别由宿主管理，不自动继承 Coding Agents 的连接文件。服务部署和 Bank 授权由服务方完成；客户端发行包不携带本地引擎。
