# ContextBase Memory Integration for Vercel AI SDK

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Give your AI agents persistent, human-like memory using [ContextBase](https://github.com/RSIXDB/hindsight) with the [Vercel AI SDK](https://ai-sdk.dev).

## Quick Start

```bash
npm install contextbase-ai-sdk contextbase-client ai zod
```

```typescript
import { ContextBaseClient } from "contextbase-client";
import { createContextBaseTools } from "contextbase-ai-sdk";
import { generateText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";

// 1. Initialize ContextBase client
const contextbaseClient = new ContextBaseClient({
  apiUrl: "http://localhost:8000",
});

// 2. Create memory tools
const tools = createContextBaseTools({ client: contextbaseClient });

// 3. Use with AI SDK
const result = await generateText({
  model: anthropic("claude-sonnet-4-20250514"),
  tools,
  system: `You have long-term memory. Use:
  - 'recall' to search past conversations
  - 'retain' to remember important information
  - 'reflect' to synthesize insights from memories`,
  prompt: "Remember that Alice loves hiking and prefers spicy food",
});

console.log(result.text);
```

## Features

✅ **Three Memory Tools**: `retain` (store), `recall` (retrieve), and `reflect` (reason over memories)
✅ **AI SDK 6 Native**: Works with `generateText`, `streamText`, and `ToolLoopAgent`
✅ **Multi-User Support**: Dynamic bank IDs per call for multi-user scenarios
✅ **Type-Safe**: Full TypeScript support with Zod schemas
✅ **Flexible Client**: Works with the official TypeScript client or custom HTTP clients

## Documentation

📖 **[Full Documentation](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs)**

The complete documentation includes:

- Detailed tool descriptions and parameters
- Advanced usage patterns (streaming, multi-user, ToolLoopAgent)
- HTTP client example (no dependencies)
- TypeScript types and API reference
- Best practices and system prompt examples

## Running ContextBase Locally

```bash
# Install and run with embedded mode (no setup required)
uvx hindsight-embed@latest -p myapp daemon start

# The API will be available at http://localhost:8000
```

## Examples

Full examples are available in the [GitHub repository](https://github.com/vectorize-io/hindsight/tree/main/examples/ai-sdk).

## Support

- [Documentation](https://github.com/RSIXDB/hindsight)
- [GitHub Issues](https://github.com/vectorize-io/hindsight/issues)
- Email: support@vectorize.io

## License

MIT
