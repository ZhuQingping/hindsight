"use strict";

const { baseUrl, DEFAULT_API_URL } = require("./utils");

/**
 * Custom API-key authentication.
 *
 * Mirrors the n8n `contextbaseApi` credential: an API key plus an explicit base
 * URL for the deployment. The key is
 * sent as a Bearer token by the shared `beforeRequest` middleware; the `test`
 * call below exercises the credential against a real authenticated endpoint.
 */

// `limit=1`: the call only has to prove the key authenticates, so don't pull a
// full page of banks on every credential test.
const test = (z, bundle) =>
  z.request({ url: `${baseUrl(bundle)}/v1/default/banks`, params: { limit: 1 } });

const connectionLabel = (z, bundle) => {
  const host = ((bundle.authData && bundle.authData.apiUrl) || DEFAULT_API_URL).replace(
    /^https?:\/\//,
    ""
  );
  return `ContextBase (${host})`;
};

module.exports = {
  type: "custom",
  test,
  connectionLabel,
  fields: [
    {
      key: "apiKey",
      label: "API Key",
      type: "password",
      // Optional so you can connect to a self-hosted instance running without
      // auth (leave blank). For ContextBase Cloud a key is required — a blank key
      // there fails the connection test (401), as expected.
      required: false,
      helpText:
        "Your ContextBase API key (starts with `hsk_`). Required for ContextBase Cloud; leave blank for a self-hosted instance running without authentication. Create one at http://localhost:9999",
    },
    {
      key: "apiUrl",
      label: "API URL",
      type: "string",
      required: true,
      helpText: "Your ContextBase API base URL (e.g. https://api.example.com).",
    },
  ],
};
