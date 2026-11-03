# ContextBase for Hermes Agent

The ContextBase Memory Provider adds automatic recall, conversation retention and the `contextbase_retain`, `contextbase_recall`, `contextbase_reflect` tools. It connects to an explicit API Endpoint. Python 3.11+ and a Hermes build supporting external Memory Providers are required.

## Install

Download and extract `contextbase-hermes-candidate` from the service provider's successful build. It contains `hermes-plugin-contextbase`, including a ContextBase SDK wheel in `sdk/`.

Copy that directory to the active Hermes profile's `plugins/contextbase` directory. Use your actual Hermes home (the `HERMES_HOME` setting when configured). Back up an existing ContextBase plugin directory before replacing it; retain the profile's `contextbase/config.json` and `.env` files.

The plugin's `pyproject.toml` points to the bundled SDK wheel. Enable it through Hermes, accepting the dependency installation if prompted:

```bash
hermes plugins enable contextbase
hermes memory setup
```

Select the ContextBase provider. Enter the service provider's **API Endpoint**, **API Key** and **existing authorized Bank ID**. Do not use a catalog install command to obtain this service-specific build.

## Configure

The setup wizard merges connection settings into the active profile's `contextbase/config.json`; it preserves other settings. A replacement API Key is saved to that profile's `.env` as `CONTEXTBASE_API_TOKEN`.

The connection can also use these profile-scoped variables:

```text
CONTEXTBASE_API_URL=https://api.example.com
CONTEXTBASE_API_TOKEN=your-api-key
CONTEXTBASE_BANK_ID=my-bank
```

An explicit key/endpoint in `contextbase/config.json` takes precedence over the corresponding variable. An explicit `CONTEXTBASE_BANK_ID` takes precedence over the static Bank in that file. Restart Hermes after changes.

Bank ID is required. The provider never derives it from a repository, directory, profile or session, and never falls back to a default Bank. Additional writable or recall-only Banks remain explicit opt-ins and must each be authorized.

## Switch Bank

Change `bank_id` in the active profile's `contextbase/config.json`, or change `CONTEXTBASE_BANK_ID` if it is set, then restart Hermes. The environment variable takes precedence. The setup wizard removes retired Bank-template and trusted-project settings.

## Verify

Restart Hermes and confirm ContextBase is the selected Memory Provider. Ask it to use the actual loaded `contextbase_retain` tool to store a distinctive test fact, then use `contextbase_recall` to retrieve it from the same Bank. Check the tool results, rather than an unverified model statement.

A missing Endpoint produces configuration guidance. A 401/403 requires checking the API Key, Endpoint and Bank permissions. The client preserves service errors and customer text unchanged.

## Update or remove

Stop Hermes, back up and replace only the ContextBase plugin directory with the new build, then enable it again so Hermes refreshes its dependencies. Keep the profile configuration. To remove it, select a different Memory Provider and disable `contextbase` through Hermes before removing the plugin directory. Remote memories remain in ContextBase.
