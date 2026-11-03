"""ContextBase's declared config surface — rendered by the generic desktop panel."""

from plugins.memory.config_schema import (
    KIND_SECRET,
    KIND_SELECT,
    KIND_TEXT,
    ProviderConfigSchema,
    ProviderField,
    ProviderFieldOption,
)

CONFIG_SCHEMA = ProviderConfigSchema(
    name="contextbase",
    label="ContextBase",
    fields=(
        ProviderField(
            key="mode",
            label="Mode",
            kind=KIND_SELECT,
            default="cloud",
            description="How Hermes connects to ContextBase.",
            options=(
                ProviderFieldOption(
                    "cloud", "Cloud", "Remote ContextBase API (requires your service URL and credentials)"
                ),
                ProviderFieldOption("self-hosted", "Self-hosted", "Connect to your explicitly configured API Endpoint"),
            ),
            inline=True,
        ),
        ProviderField(
            key="api_key",
            label="API key",
            kind=KIND_SECRET,
            env_key="CONTEXTBASE_API_TOKEN",
            description="Used to authenticate with the ContextBase API.",
            placeholder="Enter ContextBase API key",
            inline=True,
        ),
        ProviderField(
            key="api_url",
            label="API URL",
            kind=KIND_TEXT,
            default="",
            aliases=("apiUrl",),
            env_fallbacks=("CONTEXTBASE_API_URL",),
            inline=True,
        ),
        ProviderField(
            key="bank_id",
            label="Bank ID",
            kind=KIND_TEXT,
            default="",
            aliases=("bankId",),
            env_fallbacks=("CONTEXTBASE_BANK_ID",),
            inline=True,
        ),
        ProviderField(
            key="additional_banks",
            label="Additional banks",
            kind=KIND_TEXT,
            default="",
            inline=True,
            description="Extra ContextBase banks to write to and recall from, in priority order (comma-separated). Off = single-bank behavior.",
        ),
        ProviderField(
            key="recall_additional_banks",
            label="Recall-only banks",
            kind=KIND_TEXT,
            default="",
            aliases=("recallAdditionalBanks",),
            inline=True,
            description="Extra ContextBase banks to recall from but never write to, searched after the write banks (comma-separated). A bank also in Additional banks stays writable.",
        ),
        ProviderField(
            key="recall_budget",
            label="Recall budget",
            kind=KIND_SELECT,
            default="mid",
            aliases=("budget",),
            options=tuple(ProviderFieldOption(b, b) for b in ("low", "mid", "high")),
            inline=True,
        ),
    ),
)
