# Privacy Policy

The ContextBase Dify plugin sends data to a ContextBase API instance (ContextBase remote service or self-hosted) configured by the workflow author.

## Data sent

- **Retain**: the content you pass to the tool, plus any tags, are sent to ContextBase to be stored as memories. ContextBase extracts facts from the content using an LLM.
- **Recall** / **Reflect**: the query string is sent to ContextBase; relevant memories from the configured bank are returned.

## What is stored

- All retained content, extracted facts, and metadata are stored in the ContextBase instance you configure.
- The plugin itself does not retain any data — it is a thin adapter to ContextBase's API.

## Where data goes

- **an explicitly configured service URL**: data is processed and stored by Vectorize, Inc. See [https://github.com/RSIXDB/hindsight/privacy](https://github.com/RSIXDB/hindsight/privacy).
- **Self-hosted ContextBase**: data stays inside your own infrastructure.

## Credentials

The API key you configure is stored as a Dify secret credential and is sent to ContextBase on each tool invocation in the `Authorization: Bearer` header.
