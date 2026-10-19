import { INodeParams, INodeCredential } from "../src/Interface";

class ContextBaseApi implements INodeCredential {
  label: string;
  name: string;
  version: number;
  description: string;
  inputs: INodeParams[];

  constructor() {
    this.label = "ContextBase API";
    this.name = "contextbaseApi";
    this.version = 1.0;
    this.description = "Credentials for the ContextBase memory API. Requires your deployment URL.";
    this.inputs = [
      {
        label: "API URL",
        name: "apiUrl",
        type: "string",
        default: "",
        description:
          "Base URL of the ContextBase API. Set this to your deployment URL (e.g. http://localhost:8888).",
      },
      {
        label: "API Key",
        name: "apiKey",
        type: "password",
        description:
          "API key issued by your deployment administrator. Leave blank for unauthenticated self-hosted instances.",
        optional: true,
      },
    ];
  }
}

module.exports = { credClass: ContextBaseApi };
