# Agent 与工具接入

已有编程工具可以使用 ContextBase 适配器；支持 HTTP MCP 的宿主也可以直接连接远端 MCP。两种方式的会话保存能力不同，应按实际需要选择。

## 选择方式

| 方式 | 能力 | 会话保存 |
| --- | --- | --- |
| 编程工具适配器 | 按宿主配置本地 MCP、Hooks 或原生插件 | 取决于宿主、启用状态和适配器配置 |
| 远端 MCP | 直接调用服务端开放的工具 | 不自动采集或保存宿主会话 |
| Python / Node.js SDK | 由应用编排记忆调用 | 应用明确调用 Retain 时保存 |

MCP 已连接，只能说明连接已建立。云端读写权限和自动保存是否生效，需要分别验证。

## 安装编程工具适配器

先安装对应宿主和 Node.js 18+，再按[快速开始](quickstart.md)取得 API 地址、业务 Key 和 Bank ID。保存记忆需要读写权限。

在当前终端设置 `CONTEXTBASE_API_TOKEN`，再执行所需命令：

```bash
npx @huaweicloud/contextbase-coding-agents@latest install claude-code --api-url "你的API地址" --bank-id "你的Bank-ID" --project-path "."
npx @huaweicloud/contextbase-coding-agents@latest install codex --api-url "你的API地址" --bank-id "你的Bank-ID" --project-path "."
npx @huaweicloud/contextbase-coding-agents@latest install cursor-cli --api-url "你的API地址" --bank-id "你的Bank-ID" --project-path "."
```

按使用的宿主选择命令，不必全部执行。`@latest` 使用 npm 标记为 latest 的发布版本，需要固定版本时可替换为对应的已发布版本号。

Windows PowerShell 无法执行 `npx.ps1` 时，使用 `npx.cmd` 执行同样的参数。

安装完成后完全退出并重新启动宿主，按宿主要求启用 MCP 工具或审阅 Hooks。

### 配置文件与 Bank 选择

适配器默认使用 `~/.contextbase/coding-agent.json`；Windows 对应 `%USERPROFILE%\.contextbase\coding-agent.json`。设置 `CONTEXTBASE_CONFIG` 后，使用该变量指定的文件。

当前配置使用一个明确的 `bankId`，供读取这份配置的项目和 Agent 共享。不会根据项目目录推导 Bank，也不会自动创建 Bank。缺少有效 Bank 配置时，记忆功能不可用。

`--project-path` 选择项目级宿主配置的注册目录，不建立“项目目录到 Bank”的映射。

切换 Bank：

```bash
npx @huaweicloud/contextbase-coding-agents@latest bank use "新的Bank-ID"
```

切换会保留 API 地址和凭据。完全重启相关 Agent 和 MCP 进程后，新请求使用新的 Bank；旧 Bank 的记忆不会迁移。

重新安装时，同一 API 地址下的 Key 选择顺序为：`--api-token` 参数、已保存的 `apiToken`、`CONTEXTBASE_API_TOKEN` 环境变量、`CONTEXTBASE_API_KEY` 环境变量。只修改环境变量不会覆盖已保存的 Key，更换步骤见[更换适配器的 API Key](#更换适配器的-api-key)。

### Claude Code 与 Codex

Claude Code 启动后，通过 `/mcp` 检查 ContextBase。需要时可先执行 `claude mcp list` 查看注册。

Codex 可通过 `codex mcp list` 和会话中的 `/mcp` 检查连接。Hooks 自动保存还需要启用 Hooks 并完成宿主要求的信任确认；按安装输出和 `/hooks` 提示检查，完成后重新启动。

不要把工具已加载等同于 Hooks 已经执行。按下面的步骤分别验证。

### 验证接入

1. 让 Agent 调用当前已加载的 ContextBase 诊断工具，查看实际返回的 `workspace`、`bank_id`、`harness` 和 `api_url`。
2. 主动保存一条带有独特标识的测试记忆，等待后台处理完成。
3. 在新会话中查询该信息，核对服务地址和 Bank。
4. 需要自动保存时，再进行一次不主动调用保存工具的会话，结束后检查是否形成来源文档。

前三步验证工具调用和云端读写，第四步单独验证宿主的自动保存能力。

## 华为云 CodeArts

CodeArts Agent（IDE／插件）和 CodeArts CLI 通过共享的本地 stdio MCP 工具接入。当前不会安装自动召回或自动保存会话的 Hooks，需要由 Agent 主动调用记忆工具。

### CodeArts Agent

先安装 CodeArts Agent，在宿主中打开 **Settings > MCP tools > Configure MCP**，取得 `mcp_settings.json` 的完整路径：

```bash
npx --yes @huaweicloud/contextbase-coding-agents@latest install codearts-agent --api-url "你的API地址" --bank-id "你的Bank-ID" --mcp-config "MCP配置文件完整路径"
```

重启后启用 `contextbase` MCP 工具并进入 Agent 模式。先调用 `contextbase_diagnose`，再主动保存和检索测试记忆。

### CodeArts CLI

```bash
npx --yes @huaweicloud/contextbase-coding-agents@latest install codearts-cli --api-url "你的API地址" --bank-id "你的Bank-ID"
```

默认注册到 `~/.codeartsdoer/codearts_cli.jsonc`，或已有的 `.json` 文件。使用项目配置时，以 `--mcp-config` 指定文件完整路径。

重启后通过 `/mcps` 检查连接，再调用诊断和记忆工具。卸载时使用相同宿主名；安装时指定过 `--mcp-config` 的，卸载时也应指定同一路径。

宿主配置说明：[CodeArts IDE MCP](https://support.huaweicloud.com/usermanual-codeartsagent/codeartsagent_ug_0010.html)、[CodeArts CLI MCP](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0035.html)。

## 远端 MCP

只需要按需调用记忆工具时，可以直接连接远端 MCP。先取得服务方提供的完整 MCP Endpoint、认证凭据，以及必要的 Bank 选择配置。

MCP Endpoint 不从 REST 地址推导。已经使用本地适配器时，也不要直接把它的本地连接替换成远端地址，两者承担的集成工作不同。

### Codex 配置示例

在启动 Codex 的终端中设置 `CONTEXTBASE_MCP_TOKEN`，并在 `~/.codex/config.toml` 中配置：

```toml
[mcp_servers.contextbase-remote]
url = "服务方提供的完整MCP地址"
bearer_token_env_var = "CONTEXTBASE_MCP_TOKEN"
```

从同一终端重启 Codex，通过 `/mcp` 检查连接。

### Claude Code 配置示例

使用宿主的 HTTP MCP 注册命令：

```bash
claude mcp add --scope user --transport http contextbase-remote "服务方提供的完整MCP地址" --header "Authorization: Bearer 你的MCP凭据"
```

该命令会将凭据写入宿主配置。重启后通过 `/mcp` 检查连接，再实际调用保存和查询工具。

### 工具与 Bank 范围

服务端开放的工具受到实例配置、Bank 配置和 Key 权限限制，以宿主实际取得的工具列表为准。

绑定单个 Bank 的 MCP 地址只能访问该 Bank，不能通过工具参数切换到另一个 Bank。使用支持选择 Bank 的入口时，也仍需具备目标 Bank 的授权。

远端 MCP 不自动保存宿主会话。需要保留信息时，应明确调用可用的写入工具。

## 其他 Agent

安装器还支持以下常用宿主：

| 宿主 | 安装目标 | 集成方式 |
| --- | --- | --- |
| OpenCode | `opencode` | 原生插件 |
| OpenCode 2 | `opencode2` | 原生插件 |
| DSH / DeepSeek Harness | `dsh` | 原生插件 |
| pi | `pi` | 原生扩展 |
| WorkBuddy | `workbuddy` | Hooks + 本地 MCP |

将前面安装命令的目标替换为对应名称。原生插件的工具由宿主加载，不必另建重复的 MCP 注册。完整目标和选项以安装器 `--help` 为准。

OpenClaw 与 Hermes 使用各自的独立安装包和宿主配置，不能作为上述命令的安装目标，也不会自动读取 `coding-agent.json`。具体见 [OpenClaw 指南](../../../hindsight-integrations/openclaw/README.md)和 [Hermes 指南](../../../hindsight-integrations/hermes/README.md)。

## 更换适配器的 API Key

先按[成员与 Key 管理](administration.md#更换-api-key)签发新 Key，并确认它具有目标 Bank 所需的权限。将当前终端的 `CONTEXTBASE_API_TOKEN` 设置为非空的新 Key，再通过 `--api-token` 明确覆盖已保存的凭据。

Bash 示例：

```bash
npx @huaweicloud/contextbase-coding-agents@latest install claude-code --api-url "你的API地址" --bank-id "你的Bank-ID" --project-path "." --api-token "$CONTEXTBASE_API_TOKEN"
```

PowerShell 示例：

```powershell
npx.cmd @huaweicloud/contextbase-coding-agents@latest install claude-code --api-url "你的API地址" --bank-id "你的Bank-ID" --project-path "." --api-token "$env:CONTEXTBASE_API_TOKEN"
```

将 `claude-code` 替换为实际宿主。保留原安装使用的 `--project-path` 或 `--mcp-config`；使用 `CONTEXTBASE_CONFIG` 时，也要指向原配置文件。

确认生效配置中的 `apiToken` 已更新为新 Key，再完全退出并重新启动相关宿主、插件和 MCP 进程。按[验证接入](#验证接入)执行实际的保存和检索请求，确认权限符合预期后吊销旧 Key，再验证一次。仅看到 MCP 已连接，不能确认请求已经使用新凭据。

这一流程用于本地编程工具适配器。远端 MCP 的凭据应在相应宿主配置或 `bearer_token_env_var` 指定的环境变量中更新，再重启并验证。

## 更新、卸载与排查

更新时重新执行对应宿主的安装命令，然后重启。卸载示例：

```bash
npx @huaweicloud/contextbase-coding-agents@latest uninstall claude-code
npx @huaweicloud/contextbase-coding-agents@latest uninstall codex
```

卸载本地集成不会删除服务端记忆。只配置过远端 MCP 时，通过宿主的 MCP 管理方式移除对应注册。

更多参数：

```bash
npx @huaweicloud/contextbase-coding-agents@latest --help
```

适配器日志默认位于 `~/.contextbase/coding-agents-logs/plugin.log`。提交问题时提供宿主版本、安装器版本、Bank、错误信息和脱敏日志，不发送访问凭据。
