# Product naming

`definition.json` is the authority for display defaults and compatibility identities.
Change `display_name` / `deployment_slug` and retain prior names in `historical_display_names`
(for attribution recognition only), then run:

```sh
bash scripts/sync-product-brand.sh
./scripts/generate-openapi.sh
./scripts/generate-clients.sh
bash scripts/sync-product-brand.sh --check
```

The brand generator updates only its enumerated adapters, metadata fields and installer template.
The existing OpenAPI/SDK generators then propagate API display metadata from the new source.
Run these dependency-heavy steps, lint, tests and builds through the shared resource runner
when working in this bounded delivery environment; the scripts do not create their own lock.
`GENERATED.json` records exact outputs. No customer content, ID, license, version, endpoint,
credential or host configuration is an input. `identity-contract.json` freezes the compatibility
contract: changing an identity requires a separate explicit migration and review.

Python, TypeScript and Rust load generated constants. Runtime API/UI configuration uses
`product_display_name` separately from the legacy `contextdb_name` slug. Names are case-sensitive,
header-safe ASCII, 1–80 characters, without surrounding whitespace. Slugs keep the old grammar.
Both services must be configured and restarted together; UI artifacts are reusable.

`/product-config` retains v1. `/product-config/v2` is additive. Legacy-only deployments preserve
v1 display behavior; new deployments default to the definition. A v2 UI does not silently downgrade
against an old API. No machine identity is inferred from display text.

The customer CLI command remains `agentstratum`, and packages, plugin IDs, directories, environment
variables, tool names and protocol headers retain their existing identities. Help and descriptions
identify the product using the generated display name. See `docs/contextbase-naming/NAMING-MAP.md` before migration.
