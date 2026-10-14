# agentstratum-local-engine

Programmatic lifecycle manager for a local agentstratum daemon.

This package deliberately does **not** ship an HTTP client. Once the daemon is running, talk to it with [`@vectorize-io/hindsight-client`](https://www.npmjs.com/package/@vectorize-io/hindsight-client) against `server.getBaseUrl()`. The two packages compose — one owns the daemon process, the other owns the HTTP API surface.

## Requirements

- **Node.js >= 22** — uses global `fetch` and `AbortSignal.timeout`.
- **`uv` / `uvx`** on `PATH` — used to download and run the underlying `agentstratum-embed` daemon on first use. Install via <https://docs.astral.sh/uv/>.

## Distribution

The workspace package is private until the release namespace is approved. Set `AGENTSTRATUM_EMBED_PACKAGE` to the approved Python embed distribution spec and `AGENTSTRATUM_EMBED_API_PACKAGE` to the approved engine distribution spec. There is no implicit public registry package or production domain. A local checkout can be used through `embedPackagePath`.

## Install

```bash
npm install --save agentstratum-local-engine="file:../hindsight-all-npm" @vectorize-io/hindsight-client
```

## Example

```ts
import { AgentstratumServer, consoleLogger } from "agentstratum-local-engine";
import { HindsightClient } from "@vectorize-io/hindsight-client";

const server = new AgentstratumServer({
  embedPackage: process.env.AGENTSTRATUM_EMBED_PACKAGE,
  profile: "my-app",
  port: 9077,
  env: {
    AGENTSTRATUM_API_LLM_PROVIDER: "anthropic",
    AGENTSTRATUM_API_LLM_API_KEY: process.env.ANTHROPIC_API_KEY,
    AGENTSTRATUM_API_LLM_MODEL: "claude-sonnet-4-20250514",
  },
  logger: consoleLogger,
});

await server.start();

const client = new HindsightClient({ baseUrl: server.getBaseUrl() });

await client.retain("user-123", "User prefers dark mode and concise answers.", {
  documentId: "pref-2026-04-01",
});

const recall = await client.recall("user-123", "what are the user preferences?");
console.log(recall.results);

await server.stop();
```

For a remote Agentstratum API, skip `AgentstratumServer` entirely and just point `HindsightClient` at the remote URL.

## Open config — forward-compatible with new daemon flags

`AgentstratumServerOptions` is designed so every new environment variable or CLI flag in the underlying Agentstratum daemon can be used without waiting for a wrapper release:

- **`env`** accepts an arbitrary `Record<string, string>`. Every entry is exported into the daemon process and written into the profile config via `--env KEY=VALUE`.
- **`extraProfileCreateArgs`** / **`extraDaemonStartArgs`** append raw args to the respective commands.

## Development against a local checkout

If you're hacking on the Python `agentstratum-embed` package in the same monorepo, point the server at the local path — it'll use `uv run --directory <path>` instead of `uvx`:

```ts
new AgentstratumServer({
  embedPackagePath: "/path/to/agentstratum-embed",
  // ...
});
```

## API surface

- `AgentstratumServer` — daemon lifecycle (`start`, `stop`, `checkHealth`, `getBaseUrl`, `getProfile`).
- `Logger` interface plus `silentLogger` (default) and `consoleLogger` helpers.
- `getEmbedCommand(opts)` — low-level helper that returns the `[cmd, ...args]` tuple used to invoke the underlying Python CLI.

For memory operations (retain, recall, reflect, bank management, stats) use [`@vectorize-io/hindsight-client`](https://www.npmjs.com/package/@vectorize-io/hindsight-client).

## License

MIT
