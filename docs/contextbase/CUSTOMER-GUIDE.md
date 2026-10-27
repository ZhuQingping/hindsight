# ContextBase 客户使用指南

通过 ContextBase，Claude Code 和 Codex 可以共享项目约定、设计决策和任务进度。按第 1 至 4 节安装并验证。
只需手动调用记忆工具时，可直接使用第 5 节的远端 MCP 接入。

## 1 下载和安装

安装包适用于 Windows、Linux 和 macOS，需要 Node.js 24。

- [下载 Coding Agents 安装包（0.8.1，包含在 contextbase-plugin-candidates ZIP 中）](https://github.com/RSIXDB/hindsight/actions/runs/40296078727/artifacts/12638142440)
- [查看后续构建](https://github.com/RSIXDB/hindsight/actions/workflows/release.yml)：选择成功的构建，在 **Artifacts** 中下载 `contextbase-plugin-candidates`。

解压下载的 ZIP，找到：

```text
contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz
```

只需使用这个 `.tgz`，无需再次解压，也无需安装 ZIP 中的其他组件。从解压后的目录打开终端，执行：

Windows PowerShell：

```powershell
npm.cmd install -g "./contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz"
```

Linux 或 macOS Bash：

```bash
npm install -g "./contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz"
```

## 2 配置连接和项目

先进入需要启用记忆的项目目录，再填写服务提供方给出的 API 地址、API Key 和 Bank ID。Bank 需已创建并授权；`--project-path '.'` 绑定的是执行命令时的当前目录。

Windows PowerShell：

```powershell
cd D:\code\my-project
$env:CONTEXTBASE_API_TOKEN = '你的业务API-Key'
contextbase-coding-agents.cmd install claude-code codex --api-url 'https://实际API端点' --api-token "$env:CONTEXTBASE_API_TOKEN" --bank-id '实际Bank-ID' --project-path '.'
```

Linux 或 macOS Bash：

```bash
cd /home/alice/work/my-project
export CONTEXTBASE_API_TOKEN='你的业务API-Key'
contextbase-coding-agents install claude-code codex --api-url 'https://实际API端点' --api-token "$CONTEXTBASE_API_TOKEN" --bank-id '实际Bank-ID' --project-path '.'
```

只使用 Claude Code 时保留 `claude-code`；只使用 Codex 时保留 `codex`。API 地址不要填写下载地址或 MCP Endpoint。

安装器会配置本地 MCP 工具、自动读写记忆的 Hooks 和配套 Skill。安装对当前系统用户生效，**API 地址和 Key 全局共享，Bank 按项目目录选择**。

连接和项目映射保存在 `~/.contextbase/coding-agent.json`；Windows 对应 `%USERPROFILE%\.contextbase\coding-agent.json`。设置了 `CONTEXTBASE_CONFIG` 时，以该变量指定的文件为准。

Claude Code 和 Codex 在同一项目下使用同一个 Bank，即可共享记忆。

首次接入请指定 `--bank-id`。不指定时复用已有配置；没有映射时按默认规则选择 Bank，云端不一定存在或授权该 Bank。`--project-path` 必须与 `--bank-id` 一起使用。

`optInOnly` 控制未绑定项目是否启用记忆：`true` 表示仅已绑定或明确启用的项目使用记忆，`false` 表示其他项目也按默认规则选择 Bank。未配置时默认 `false`，安装器保留已有值。

### 为项目指定或切换 Bank

已配置 API 地址和 Key 后，可直接为项目指定 Bank，无需重复填写连接信息。Bank 需已创建，且当前 Key 有访问权限。

在项目目录中执行（Windows PowerShell）：

```powershell
cd D:\code\xiyan
contextbase-coding-agents.cmd install claude-code codex --bank-id "test_cli" --project-path "."
```

也可以直接指定其他项目的绝对路径：

```powershell
contextbase-coding-agents.cmd install claude-code codex --bank-id "bank_other" --project-path "D:\code\other-project"
```

Linux 或 macOS Bash：

```bash
contextbase-coding-agents install claude-code codex --bank-id "bank_other" --project-path "/home/alice/work/other-project"
```

只使用一个客户端时，保留对应的 `claude-code` 或 `codex`。这些命令会更新指定项目的绑定，保留其他项目的映射和已有 API 地址、Key。

映射写入前述用户配置文件的 `mapPathToBank` 字段，子目录也适用；多个路径匹配时使用最长路径。例如：

```json
{
  "mapPathToBank": {
    "D:/code/xiyan": "test_cli",
    "D:/code/other-project": "bank_other"
  }
}
```

以上仅展示映射字段，手动修改时保留文件中的其他配置。为同一项目切换 Bank 时，重新执行绑定命令并替换 `--bank-id` 即可，旧 Bank 的记忆不会自动迁移。

绑定或切换后，在对应项目目录重新启动 Claude Code 或 Codex。可让客户端调用已加载的 ContextBase 诊断工具，确认返回的 `workspace` 和 `bank_id` 与预期一致。

重复安装会保留已有项目映射。已有同名 Claude MCP 配置若不属于本集成，安装器会提示处理，不会直接覆盖。

## 3 启动客户端

### Claude Code

进入已配置的项目目录，执行：

```bash
claude mcp list
claude
```

在会话中输入 **/mcp**，确认 contextbase 已连接。

### Codex

安装器会在 **~/.codex/config.toml** 中启用 Hooks，可检查 features 表：

```toml
[features]
hooks = true
```

已有 [features] 时只补充 hooks，不重复添加表。保留原有模型配置。

进入同一项目目录，执行：

```bash
codex mcp list
codex
```

在会话中输入 **/hooks**，按提示审阅并信任 ContextBase Hook；输入 **/mcp**，确认 contextbase 已连接。完成设置后重新启动客户端。

## 4 验证安装

在已绑定项目目录启动 Claude Code 或 Codex，输入 `/mcp`，确认 `contextbase` 显示已连接，并加载 8 个工具。

随后在对话中输入：

> 请调用当前已加载的 ContextBase 诊断工具，返回 workspace、bank_id、harness 和 api_url。请使用工具的实际返回结果。

确认工具调用成功，且返回的项目路径、Bank、客户端类型和 API 地址与配置一致，即可确认本地 MCP 已安装并可调用。仅显示“已连接”或模型声称安装成功，不代表工具调用成功。

此检查不验证云端读写权限或 Hooks 自动保存；遇到错误可参考第 6 节。

## 5 可选的远端 MCP 接入

只需要按需查询和保存记忆时，可直接连接远端 MCP，无需安装本地适配器。此方式不自动保存会话。

使用服务提供方给出的**完整 MCP Endpoint 和对应凭据**。若已启用前面的集成，不要直接用远端地址替换本地适配器配置。

### Claude Code

PowerShell 和 Bash 均可执行，替换地址及凭据：

```bash
claude mcp add --scope user --transport http contextbase-remote "完整MCP地址" --header "Authorization: Bearer 实际MCP凭据"
claude mcp list
```

该命令会将凭据写入宿主配置。重启 Claude Code，通过 /mcp 检查连接。

### Codex

先在启动 Codex 的终端设置凭据。

PowerShell：

```powershell
$env:CONTEXTBASE_MCP_TOKEN = '实际MCP凭据'
```

Bash：

```bash
export CONTEXTBASE_MCP_TOKEN='实际MCP凭据'
```

在 **~/.codex/config.toml** 中添加：

```toml
[mcp_servers.contextbase-remote]
url = "完整MCP地址"
bearer_token_env_var = "CONTEXTBASE_MCP_TOKEN"
```

从同一终端启动 Codex，通过 /mcp 检查。新终端也需要设置该变量。

随后要求客户端“使用 contextbase-remote 保存并查询一条测试记忆”。远端工具与本地适配器不同，以客户端显示的工具列表为准。如果服务提供方要求额外配置 Bank 请求头，使用其提供的配置。

## 6 常见问题和维护

| 问题                       | 处理                                               |
| -------------------------- | -------------------------------------------------- |
| 401 或 403                 | 核对凭据、API/MCP 地址及 Bank 权限                 |
| 修改环境变量后仍使用旧凭据 | 检查 coding-agent.json，文件中的值优先             |
| MCP 连接成功但没有工具     | 检查当前目录是否匹配 mapPathToBank                 |
| 两个客户端无法共享记忆     | 确认连接到同一服务和 Bank，等待写入处理完成        |
| Codex 不自动保存           | 检查 hooks = true 和 /hooks 信任状态               |
| Claude 安装后没有 MCP      | 按安装输出的手动注册命令补配；仍失败时联系服务支持 |
| 改配置后未生效             | 完全重启客户端                                     |
| PowerShell 拒绝执行 .ps1   | 使用 npm.cmd、contextbase-coding-agents.cmd        |

**查看日志**

日志位于 ~/.contextbase/coding-agents-logs/plugin.log。需要服务支持时，提供客户端版本、错误信息和脱敏日志，不发送访问凭据。

**更新**

安装新版本 tgz，然后重新运行第 2 节的 install 命令并重启客户端。需要保留现有连接和项目映射时，可只执行 `contextbase-coding-agents install claude-code codex`（PowerShell 使用 `.cmd`）。

**卸载**

PowerShell：

```powershell
contextbase-coding-agents.cmd uninstall claude-code codex
npm.cmd uninstall -g contextbase-coding-agents
```

Bash：

```bash
contextbase-coding-agents uninstall claude-code codex
npm uninstall -g contextbase-coding-agents
```

卸载不会删除远端记忆。若只配置了远端 MCP，使用宿主的 MCP 管理命令移除 contextbase-remote。
