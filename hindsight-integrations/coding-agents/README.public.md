# ContextBase Coding Agents

Connect coding agents to your ContextBase memory service. Node.js 18 or later is required.
Obtain an API endpoint, API token, and bank ID from your service provider.

Set `CONTEXTBASE_API_TOKEN` in your environment before installing. Keep credentials out of shell history.

```bash
npx @huaweicloud/contextbase-coding-agents@latest install claude-code --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
npx @huaweicloud/contextbase-coding-agents@latest install codex --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
npx @huaweicloud/contextbase-coding-agents@latest install cursor-cli --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
```

### Huawei Cloud CodeArts

Install CodeArts Agent (IDE/plugin) or CodeArts CLI first, together with Node.js 18+.
Both integrations expose the shared local stdio MCP memory tools. They do not install
hooks for automatic conversation recall or session capture.

For the IDE/plugin, open **Settings > MCP tools > Configure MCP**, copy the full path
of `mcp_settings.json`, and use it below:

```bash
npx --yes @huaweicloud/contextbase-coding-agents@latest install codearts-agent --api-url <API_ENDPOINT> --bank-id <BANK_ID> --mcp-config "<MCP_CONFIG_PATH>"
```

For the CLI:

```bash
npx --yes @huaweicloud/contextbase-coding-agents@latest install codearts-cli --api-url <API_ENDPOINT> --bank-id <BANK_ID>
```

CLI registration uses `~/.codeartsdoer/codearts_cli.jsonc`, or the existing `.json` file.
To use a project configuration, pass `--mcp-config` with the full path of the project's
`.codeartsdoer/codearts_cli.jsonc`. Uninstall with the same client name and config path.
Other settings and MCP servers are preserved; an existing user-managed `contextbase`
server is not overwritten.

Restart CodeArts after installing or switching Bank. Enable `contextbase` in the IDE's
MCP tools and switch to Agent mode, or check `/mcps` in the CLI. Ask the agent to call
`contextbase_diagnose`, then recall or save a memory explicitly.

Configuration references: [IDE MCP](https://support.huaweicloud.com/usermanual-codeartsagent/codeartsagent_ug_0010.html),
[CLI MCP](https://support.huaweicloud.com/usermanual-cli/codeartsagent_cli_0035.html).

The installer saves `bankId` as one workspace shared by all projects and agents. It never derives a workspace from the directory or creates one automatically. Missing `bankId` disables memory.

Switch without reinstalling:

```bash
npx @huaweicloud/contextbase-coding-agents@latest bank use <BANK_ID>
```

This preserves the API endpoint and token. `--project-path` only selects a directory for project-specific client registration.
Restart your agent and MCP server after installation or switching. For additional clients and options, run:

```bash
npx @huaweicloud/contextbase-coding-agents@latest --help
```

Uninstall an integration with:

```bash
npx @huaweicloud/contextbase-coding-agents@latest uninstall claude-code
npx @huaweicloud/contextbase-coding-agents@latest uninstall codex
```

This package contains the client installer, hooks, skills, and MCP client tools.
Configured agents send supported session content and memory requests to your configured service.
Contact your service provider for access and support.
