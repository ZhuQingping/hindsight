# ContextBase 客户使用指南

让 Claude Code 和 Codex 使用同一个项目记忆库，自动保存工作记录，并在后续会话中调用。推荐按第 1 至 5 节完成安装；只需要远端 MCP 时，直接使用第 6 节。

## 1 准备

请准备 Node.js 24、已能正常使用的 Claude Code 或 Codex CLI，以及服务提供方给出的：

- Coding Agents 安装包或下载地址。

- API Endpoint 和访问凭据。

- 已授权的 Bank ID。

本地 MCP 适配器随集成安装，记忆保存在远端，无需在本机部署数据库。

## 2 安装

下载服务提供方交付的 tgz 文件，按提供的 SHA256SUMS 校验后安装。将以下文件名替换为实际文件名。

Windows PowerShell：

```powershell
npm.cmd install -g ./contextbase-coding-agents-版本.tgz
```

Linux 或 macOS Bash：

```bash
npm install -g ./contextbase-coding-agents-版本.tgz
```

也可以将本地文件名替换为服务提供方给出的完整 HTTPS 下载地址。

## 3 配置连接和项目

进入需要启用记忆的项目目录，使用服务提供方给出的 API 地址、业务 API Key 和 Bank ID 执行安装命令。Bank 必须已创建，Key 必须具有对应读写权限。

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

安装器会注册本地 MCP、Hooks 和配套 Skill，并把连接与项目映射写入 **~/.contextbase/coding-agent.json**。Windows 的 ~ 通常为 C:/Users/用户名；如果设置了 CONTEXTBASE_CONFIG，则使用该变量指定的文件。配置文件包含凭据，不要提交到代码仓库。

配置示例：

```json
{
  "apiUrl": "https://实际API端点",
  "apiToken": "实际访问凭据",
  "optInOnly": true,
  "mapPathToBank": {
    "D:/code/my-project": "实际Bank-ID"
  },
  "banks": {
    "实际Bank-ID": {
      "manageBankConfig": false,
      "autoSeed": false,
      "codebaseSurvey": false
    }
  }
}
```

`mapPathToBank` 将项目目录绑定到 Bank，子目录也适用；多个映射匹配时使用最长路径。`optInOnly: true` 表示只有已绑定或明确启用的项目才使用记忆。Claude Code 和 Codex 使用相同映射即可共享记忆。

API 地址和 Key 由各项目共用；不同项目可绑定不同 Bank。修改全局连接会影响所有已配置项目。客户模式不自动修改云端 Bank 配置、不初始化历史数据或启动代码调查，仍可保存会话、查询记忆和主动写入文档。

首次接入建议指定 `--bank-id`；后续重装可复用已有配置。不指定时保留原配置，没有映射时通常按项目名生成 Bank 名称，但云端不一定存在或授权该 Bank。`--project-path` 必须配合 `--bank-id` 使用。

需要切换 Bank 时，修改对应路径映射并重启客户端。旧 Bank 的记忆不会自动迁移。

## 4 启动客户端

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

## 5 使用和验证

安装后正常工作即可。Hook 会在提问时获取相关记忆，在每轮回复结束后保存会话。也可以明确要求客户端调用记忆工具。

**保存一条约定：**

> 请调用 contextbase_ingest_document，保存项目约定：迁移脚本先在影子库执行，验证标识为 CB-DEMO-7429。

**换到另一个客户端的新会话：**

> 请调用 contextbase_reflect，从项目记忆中查找迁移脚本的执行约定和验证标识。

看到实际工具调用并返回正确内容，说明跨客户端读写已打通。新记忆可能需要等待处理后才能查询。

### 日常记忆使用示例

以下提示词可直接输入 Claude Code 或 Codex 的对话框，适用于前面安装的本地 MCP 集成。两端连接同一服务、映射到同一个 Bank 后，可以共享这些记忆。

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

## 6 可选的远端 MCP 接入

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

## 7 常见问题和维护

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

安装新版本 tgz，然后重新运行第 3 节的 install 命令并重启客户端。需要保留现有连接和项目映射时，可只执行 `contextbase-coding-agents install claude-code codex`（PowerShell 使用 `.cmd`）。

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
