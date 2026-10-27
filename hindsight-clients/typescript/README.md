# ContextBase Node.js SDK

Install the downloaded package (Node.js 18+):

```sh
npm install ./contextbase-client-1.0.0.tgz
```

Set `CONTEXTBASE_API_URL`, `CONTEXTBASE_API_TOKEN` and `CONTEXTBASE_BANK_ID` to the values supplied by your service provider, then use:

```typescript
import { ContextBaseClient } from "contextbase-client";

const client = new ContextBaseClient({
  baseUrl: process.env.CONTEXTBASE_API_URL!,
  apiKey: process.env.CONTEXTBASE_API_TOKEN!,
});
const bank = process.env.CONTEXTBASE_BANK_ID!;
await client.retain(bank, "The project uses PostgreSQL 16.");
const result = await client.recall(bank, "Which database does the project use?");
console.log(result);
```

CommonJS is also supported:

```javascript
const { ContextBaseClient, ContextBaseError } = require("contextbase-client");
```

The package includes TypeScript declarations. Pass the API Endpoint including any service path prefix. The SDK connects to your configured service; it does not install a server or create your Bank automatically.
