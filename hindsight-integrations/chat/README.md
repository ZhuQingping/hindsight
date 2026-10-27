# contextbase-chat

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Give your [Vercel Chat SDK](https://github.com/vercel/chat) bots persistent, per-user memory with a single handler wrapper. Works with Slack, Discord, Teams, Google Chat, GitHub, and Linear.

## Setup

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.
>
> Self-hosting alternative: [installation guide](https://github.com/RSIXDB/hindsight/tree/main/hindsight-docs).

## Quick Start

```bash
npm install contextbase-chat
```

```typescript
import { Chat } from "chat";
import { ContextBaseClient } from "contextbase-client";
import { withContextBaseChat } from "contextbase-chat";
import { streamText } from "ai";
import { openai } from "@ai-sdk/openai";

const chat = new Chat({
  connectors: [
    /* your connectors */
  ],
});
const contextbase = new ContextBaseClient({ apiKey: process.env.CONTEXTBASE_API_KEY });

chat.onNewMention(
  withContextBaseChat(
    {
      client: contextbase,
      bankId: (msg) => msg.author.userId, // per-user memory
    },
    async (thread, message, ctx) => {
      await thread.subscribe();

      const result = await streamText({
        model: openai("gpt-4o"),
        system: ctx.memoriesAsSystemPrompt(),
        messages: [{ role: "user", content: message.text }],
      });

      // Stream the response
      const chunks: string[] = [];
      for await (const chunk of result.textStream) {
        chunks.push(chunk);
      }
      const fullResponse = chunks.join("");
      await thread.post(fullResponse);

      // Store the conversation in memory
      await ctx.retain(`User: ${message.text}\nAssistant: ${fullResponse}`);
    }
  )
);
```

## Configuration

### `withContextBaseChat(options, handler)`

Returns a standard Chat SDK handler `(thread, message) => Promise<void>`.

#### Options

| Option                   | Type                        | Default     | Description                           |
| ------------------------ | --------------------------- | ----------- | ------------------------------------- |
| `client`                 | `ContextBaseClient`           | _required_  | ContextBase client instance             |
| `bankId`                 | `string \| (msg) => string` | _required_  | Memory bank ID or resolver function   |
| `recall.enabled`         | `boolean`                   | `true`      | Auto-recall memories before handler   |
| `recall.budget`          | `'low' \| 'mid' \| 'high'`  | `'mid'`     | Processing budget for recall          |
| `recall.maxTokens`       | `number`                    | API default | Max tokens for recall results         |
| `recall.types`           | `FactType[]`                | all         | Filter to specific fact types         |
| `recall.tags`            | `string[]`                  | –           | Tags used to filter recalled memories |
| `recall.includeEntities` | `boolean`                   | `true`      | Include entity observations           |
| `retain.enabled`         | `boolean`                   | `false`     | Auto-retain inbound messages          |
| `retain.async`           | `boolean`                   | `true`      | Fire-and-forget retain                |
| `retain.tags`            | `string[]`                  | –           | Tags for retained memories            |
| `retain.metadata`        | `Record<string, string>`    | –           | Metadata for retained memories        |

### Context (`ctx`)

The third argument passed to your handler:

| Property/Method                        | Description                           |
| -------------------------------------- | ------------------------------------- |
| `ctx.bankId`                           | Resolved bank ID                      |
| `ctx.memories`                         | Array of recalled memories            |
| `ctx.entities`                         | Entity observations (or null)         |
| `ctx.memoriesAsSystemPrompt(options?)` | Format memories for LLM system prompt |
| `ctx.retain(content, options?)`        | Store content in memory               |
| `ctx.recall(query, options?)`          | Search memories                       |
| `ctx.reflect(query, options?)`         | Reason over memories                  |

## Examples

### Subscribed Message Handler

```typescript
chat.onSubscribedMessage(
  withContextBaseChat(
    {
      client: contextbase,
      bankId: (msg) => msg.author.userId,
      recall: { budget: "high", maxTokens: 1000 },
    },
    async (thread, message, ctx) => {
      const result = await generateText({
        model: openai("gpt-4o"),
        system: ctx.memoriesAsSystemPrompt(),
        messages: [{ role: "user", content: message.text }],
      });
      await thread.post(result.text);
    }
  )
);
```

### Auto-Retain Inbound Messages

```typescript
chat.onNewMention(
  withContextBaseChat(
    {
      client: contextbase,
      bankId: (msg) => msg.author.userId,
      retain: { enabled: true, tags: ["slack", "inbound"] },
    },
    async (thread, message, ctx) => {
      // Inbound message is already being retained automatically
      const result = await generateText({
        model: openai("gpt-4o"),
        system: ctx.memoriesAsSystemPrompt(),
        messages: [{ role: "user", content: message.text }],
      });
      await thread.post(result.text);

      // Retain the assistant response separately
      await ctx.retain(`Assistant: ${result.text}`, {
        tags: ["slack", "outbound"],
      });
    }
  )
);
```

### Static Bank ID (Shared Memory)

```typescript
// All users share the same memory bank
chat.onNewMention(
  withContextBaseChat(
    { client: contextbase, bankId: "shared-team-memory" },
    async (thread, message, ctx) => {
      // ...
    }
  )
);
```

## Error Handling

Memory failures never break your bot. Auto-recall and auto-retain errors are logged as warnings and the handler continues with empty memories. Manual `ctx.retain()`, `ctx.recall()`, and `ctx.reflect()` calls propagate errors normally so you can handle them as needed.

## License

MIT
