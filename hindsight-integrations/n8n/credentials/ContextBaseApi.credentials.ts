import type {
  IAuthenticateGeneric,
  ICredentialTestRequest,
  ICredentialType,
  INodeProperties,
} from "n8n-workflow";

/**
 * Credentials for the ContextBase memory API.
 *
 * Requires your ContextBase service URL. Set the API URL
 * to your deployment (e.g. http://localhost:8888).
 */
export class ContextBaseApi implements ICredentialType {
  name = "contextbaseApi";
  displayName = "ContextBase API";
  documentationUrl = "https://hindsight.vectorize.io/developer/api/quickstart";
  properties: INodeProperties[] = [
    {
      displayName: "API URL",
      name: "apiUrl",
      type: "string",
      default: "",
      description: "Base URL of the ContextBase API. Set this to your deployment URL.",
      required: true,
    },
    {
      displayName: "API Key",
      name: "apiKey",
      type: "string",
      typeOptions: { password: true },
      default: "",
      description:
        "API key issued by your deployment administrator. Leave blank for unauthenticated self-hosted instances.",
    },
  ];

  authenticate: IAuthenticateGeneric = {
    type: "generic",
    properties: {
      headers: {
        Authorization: '={{ $credentials.apiKey ? "Bearer " + $credentials.apiKey : "" }}',
        // Applied to every request made with this credential, so the node needs no header of
        // its own. No version: the source and compiled files sit at different depths from
        // package.json, so there is no single relative path to read it from.
        "User-Agent": "contextbase-n8n",
      },
    },
  };

  // Test against /health — works for both Cloud and self-hosted
  test: ICredentialTestRequest = {
    request: {
      baseURL: "={{ $credentials.apiUrl }}",
      url: "/health",
      method: "GET",
    },
  };
}
