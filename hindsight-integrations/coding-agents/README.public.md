# ContextBase Coding Agents

Connect coding agents to your ContextBase memory service. Node.js 18 or later is required.
Obtain an API endpoint, API token, and bank ID from your service provider.

Set `CONTEXTBASE_API_TOKEN` in your environment before installing. Keep credentials out of shell history.

```bash
npx @huaweicloud/contextbase-coding-agents@latest install claude-code --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
npx @huaweicloud/contextbase-coding-agents@latest install codex --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
npx @huaweicloud/contextbase-coding-agents@latest install cursor-cli --api-url <API_ENDPOINT> --bank-id <BANK_ID> --project-path <PROJECT_PATH>
```

Restart your agent after installation. For additional clients and options, run:

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
