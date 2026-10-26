# ContextBase 客户使用指南

通过 ContextBase，Claude Code 和 Codex 可以共享项目约定、设计决策和任务进度。按第 1 至 4 节安装并验证；只需手动调用记忆工具时，可直接使用第 5 节的远端 MCP 接入。

## 1 下载和安装

安装包适用于 Windows、Linux 和 macOS，需要 Node.js 24。

- [下载 Coding Agents 安装包（0.8.1，包含在 contextbase-plugin-candidates ZIP 中）](https://github.com/RSIXDB/hindsight/actions/runs/40296078727/artifacts/12638142440)
- [查看后续构建](https://github.com/RSIXDB/hindsight/actions/workflows/release.yml)：选择成功的构建，在 **Artifacts** 中下载 `contextbase-plugin-candidates`。

下载需要登录有仓库访问权限的 GitHub 账号。当前链接为构建候选产物，有保留期限；过期后请从后续构建获取安装包。

解压下载的 ZIP，找到：

```text
contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz
```

只需使用这个 `.tgz`，无需再次解压，也无需安装 ZIP 中的其他组件。从解压后的目录打开终端，按包内的 `SHA256SUMS` 核对文件后执行：

Windows PowerShell：

```powershell
npm.cmd install -g "./contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz"
```

Linux 或 macOS Bash：

```bash
npm install -g "./contextbase-coding-agents/0.8.1/contextbase-coding-agents-0.8.1.tgz"
```

使用其他版本时，将路径和文件名中的 `0.8.1` 替换为实际版本。安装的是客户端集成；记忆保存在 ContextBase 服务端，无需在本机部署数据库。

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

连接和项目映射保存在 `~/.contextbase/coding-agent.json`；Windows 对应 `%USERPROFILE%\.contextbase\coding-agent.json`。设置了 `CONTEXTBASE_CONFIG` 时，以该变量指定的文件为准。文件包含凭据，不要提交到代码仓库。

项目映射示例（仅展示相关字段，修改时保留其他配置）：

```json
{
  "mapPathToBank": {
    "D:/code/my-project": "bank_my_project",
    "D:/code/other-project": "bank_other"
  }
}
```

映射对子目录也生效；多个路径匹配时使用最长路径。Claude Code 和 Codex 在同一项目下使用同一个 Bank，即可共享记忆。

首次接入请指定 `--bank-id`。不指定时复用已有配置；没有映射时按默认规则选择 Bank，云端不一定存在或授权该 Bank。`--project-path` 必须与 `--bank-id` 一起使用。

`optInOnly` 控制未绑定项目是否启用记忆：`true` 表示仅已绑定或明确启用的项目使用记忆，`false` 表示其他项目也按默认规则选择 Bank。未配置时默认 `false`，安装器保留已有值。

其他项目使用不同 Bank 时，添加映射即可，已有映射会保留：

```powershell
contextbase-coding-agents.cmd install claude-code --bank-id "bank_other" --project-path "D:\code\other-project"
```

需要切换 Bank 时，修改对应路径映射并重启客户端。旧 Bank 的记忆不会自动迁移。

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

## 4 使用和验证

启用 Hooks 后，客户端会自动检索相关记忆并保存会话。也可以在对话中要求调用记忆工具。先用下面的示例验证读写：

**保存一条约定：**

> 请调用 contextbase_ingest_document，保存项目约定：迁移脚本先在影子库执行，验证标识为 CB-DEMO-7429。

**换到另一个客户端的新会话：**

> 请调用 contextbase_reflect，从项目记忆中查找迁移脚本的执行约定和验证标识。

看到实际工具调用并返回正确内容，说明跨客户端读写已打通。新记忆可能需要等待处理后才能查询。

### 日常记忆使用示例

以下示例可直接输入 Claude Code 或 Codex。工具名用于说明用途，实际调用以客户端加载的工具列表为准。

#### 保存项目约定

在 Claude Code 中输入：

> 请调用 contextbase_ingest_document，将以下已确认的约定保存到当前项目记忆：数据库变更必须提供回滚脚本；接口新增字段必须补充接口文档；错误日志必须包含 request_id。标题为“项目开发约定”。

以后在 Claude Code 或 Codex 中开始任务时输入：

> 请调用 contextbase_reflect，查询本项目的开发约定，再结合当前代码列出这次修改需要遵守的要求。没有查到的约定请明确说明。

#### 保存设计决策并查询原因

方案讨论结束后输入：

> 请调用 contextbase_ingest_document，保存本次设计决策：批量导入采用异步任务，接口返回 task_id，客户端轮询进度。原因是导入耗时不固定，同步请求容易超时。暂不采用长连接推送，以降低客户端接入成本。标题为“批量导入接口设计决策”。

后续会话中输入：

> 请调用 contextbase_reflect，查询批量导入为什么采用异步任务，以及当时没有选择长连接推送的原因。区分已记录的结论和你的新建议。

#### 从 Claude Code 切换到 Codex 继续工作

结束 Claude Code 会话前输入：

> 请总结本次任务的目标、已完成修改、验证结果和待办事项，调用 contextbase_ingest_document 保存为“批量导入任务交接记录”。只记录实际完成的内容，未运行的测试标明未运行。

然后在同一项目目录启动 Codex 的新会话，输入：

> 请调用 contextbase_reflect，查询最新的“批量导入任务交接记录”。先核对当前代码和 Git 状态，再告诉我还剩哪些工作，暂不修改代码。

应能查到之前保存的工作记录。记忆用于恢复背景，实际进度仍需与当前代码核对。

#### 记录故障处理经验

问题修复后输入：

> 请根据本次已经验证的排查结果，整理故障现象、触发条件、根因、修复方法和验证步骤，调用 contextbase_ingest_document 保存为“连接池耗尽排查记录”。未证实的猜测不要写成结论。

再次遇到类似问题时输入：

> 请调用 contextbase_reflect，查询本项目是否有连接池耗尽的处理经验，结合当前错误日志列出排查步骤，并说明哪些历史条件需要重新验证。

#### 补充新的约定

约定发生变化时输入：

> 请调用 contextbase_ingest_document，记录本项目今天确认的新约定：批量导入的单批上限从 1000 条调整为 500 条，原因是降低单批处理延迟。请写明生效日期和替代的旧约定，标题为“批量导入单批上限调整”。

后续查询时输入：

> 请调用 contextbase_reflect，查询批量导入当前生效的单批上限，列出对应决策的日期；如有冲突记录，请指出冲突。

新增记录不等于删除旧记忆，因此变更约定时应写清日期和替代关系。

保存时查看工具是否实际执行成功。若刚保存的内容暂时查不到，等待处理完成后再查询；跨会话示例应使用新会话验证。

若没有查到，先让客户端调用 **contextbase_diagnose**，核对当前项目、连接和 Bank。不要仅凭模型回答正确就判断记忆接入成功。

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
