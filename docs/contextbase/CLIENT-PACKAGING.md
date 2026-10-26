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
```

该变量仅用于安装包下载地址。API 地址由 `CONTEXTBASE_CP_PUBLIC_API_URL` 配置；需要远端 MCP 时另设 `CONTEXTBASE_CP_PUBLIC_MCP_URL`。更新环境变量后按部署方式重启控制台服务。

向客户交付安装包地址、SHA256SUMS、API Endpoint、业务 API Key 和已授权的 Bank ID，并附客户指南。

## 使用 GitHub Actions 构建

也可在 Actions 中运行 **Build contextbase client candidates**，选择包含修改的分支，完成后下载 `contextbase-plugin-candidates` artifact，其中包含安装包和校验文件。

此工作流只生成候选产物，不会自动发布到 npm 或对象存储。仍需完成上面的真实服务验收和下载地址发布。

实现入口：[打包脚本](../../scripts/package-client-plugins.py)、[构建工作流](../../.github/workflows/release.yml)。
