---
sidebar_position: 9
title: "OpenClaw Memory with ContextBase"
description: "Connect OpenClaw to your ContextBase service for automatic memory recall and retention."
---


Connect OpenClaw to your ContextBase service for automatic memory recall and conversation retention. Node.js 22+ is required. The plugin includes its ContextBase SDK and requires no local memory server or LLM credentials.

## Install

Download `contextbase-openclaw-candidate` from the service provider's successful build. Extract the ZIP, then install its `.tgz` through OpenClaw:

```bash
openclaw plugins install ./contextbase-openclaw-1.0.0.tgz
```

Use the path of the extracted `.tgz` on your machine. Keep the `.tgz` compressed.

## Configure

Use the API Endpoint, API Key and existing authorized Bank supplied by your service provider. Run the installed `contextbase-openclaw-setup` command. If the plugin's commands are not on PATH, run `node` with the installed plugin's `dist/setup.js` file.

```bash
contextbase-openclaw-setup --mode cloud --api-url "https://api.example.com" --token-env CONTEXTBASE_API_TOKEN --bank-id "my-bank"
```

Set `CONTEXTBASE_API_TOKEN` in the environment of the OpenClaw gateway process. The setup command writes an OpenClaw SecretRef, so OpenClaw resolves the token itself. In PowerShell:

```powershell
$env:CONTEXTBASE_API_TOKEN = 'your-api-key'
```

Alternatively use OpenClaw's settings UI to configure the plugin `contextbase-openclaw`:

```json
{
  "contextbaseApiUrl": "https://api.example.com",
  "contextbaseApiToken": {"source": "env", "provider": "default", "id": "CONTEXTBASE_API_TOKEN"},
  "bankId": "my-bank",
  "dynamicBankId": false,
  "autoRecall": true,
  "autoRetain": true
}
```

Setup preserves other plugins and existing conversation-access opt-outs. Automatic retention requires OpenClaw to allow this plugin to access conversation hooks. Restart the gateway after changing configuration.

API paths may include a service prefix. The endpoint and credentials are shared by this plugin's recall, retention and backfill operations. The setup command binds a static Bank; it does not create a Bank. Dynamic routing and `agentBankMap` remain available for deployments whose credentials authorize the selected Banks.

## Verify

Confirm the plugin is loaded and the log reports `initialized (mode: remote API, bank: ...)`. Store a distinctive test fact in a conversation, wait for retention, then ask for it in a new conversation using the same Bank. A successful plugin load alone does not verify service permissions.

A 401/403 requires checking the Endpoint, API Key and Bank authorization. Configuration changes require a gateway restart. Logs use ContextBase branding and preserve the service's original error information.

## Update or remove

Install the new `.tgz` through OpenClaw's plugin manager and restart the gateway. Use that manager to remove `contextbase-openclaw`. Configuration and remote memories are separate; removing the plugin does not delete the Bank.

[View Changelog →](/changelog/integrations/openclaw)
