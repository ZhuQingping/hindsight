import { DynamicStructuredTool } from "@langchain/core/tools";
import { ContextBaseClient } from "contextbase-client";
import { z } from "zod";

import { ICommonObject, INode, INodeData, INodeParams } from "../../../src/Interface";
import { getBaseClasses, getCredentialData, getCredentialParam } from "../../../src/utils";

// Each node dir is copied into Flowise on its own, so there is no shared module or
// package.json to read a version from.
const USER_AGENT = "contextbase-flowise";

const RetainSchema = z.object({
  bankId: z.string().describe("The ContextBase memory bank to retain content into."),
  content: z
    .string()
    .describe("Free-text content to store. ContextBase extracts facts asynchronously."),
  tags: z
    .array(z.string())
    .optional()
    .describe("Optional list of tags to apply to the retained memory."),
});

class ContextBaseRetain_Tools implements INode {
  label: string;
  name: string;
  version: number;
  description: string;
  type: string;
  icon: string;
  category: string;
  baseClasses: string[];
  credential: INodeParams;
  inputs: INodeParams[];

  constructor() {
    this.label = "ContextBase Retain";
    this.name = "contextbaseRetain";
    this.version = 1.0;
    this.type = "ContextBaseRetain";
    this.icon = "contextbase.svg";
    this.category = "Tools";
    this.description =
      "Store free-text content as long-term memory in a ContextBase bank. ContextBase extracts facts asynchronously after the call returns.";
    this.credential = {
      label: "Connect Credential",
      name: "credential",
      type: "credential",
      credentialNames: ["contextbaseApi"],
    };
    this.inputs = [
      {
        label: "Default Bank ID",
        name: "bankId",
        type: "string",
        description:
          "Default memory bank to retain into when the agent does not pass one. Banks are created on first use.",
        placeholder: "user-123",
        optional: true,
      },
    ];
    this.baseClasses = [this.type, ...getBaseClasses(DynamicStructuredTool)];
  }

  async init(nodeData: INodeData, _: string, options: ICommonObject): Promise<unknown> {
    const credentialData = await getCredentialData(nodeData.credential ?? "", options);
    const apiUrl = getCredentialParam("apiUrl", credentialData, nodeData) || "";
    const apiKey = getCredentialParam("apiKey", credentialData, nodeData);

    const defaultBankId = (nodeData.inputs?.bankId as string) || "";

    if (!apiUrl.trim()) throw new Error("Configure the ContextBase API URL in credentials.");
    const client = new ContextBaseClient({
      baseUrl: apiUrl,
      ...(apiKey ? { apiKey } : {}),
      userAgent: USER_AGENT,
    });

    return new DynamicStructuredTool({
      name: "contextbase_retain",
      description:
        "Store free-text content into a ContextBase memory bank. Use this to retain facts about a user, decisions made, or anything else worth remembering across conversations. ContextBase extracts structured facts asynchronously.",
      schema: RetainSchema as any,
      func: async ({
        bankId,
        content,
        tags,
      }: {
        bankId: string;
        content: string;
        tags?: string[];
      }) => {
        const targetBank = bankId || defaultBankId;
        if (!targetBank) {
          return "Error: bankId is required (no default bank configured on the node).";
        }
        const opts = tags && tags.length ? { tags } : undefined;
        const response = await client.retain(targetBank, content, opts);
        return JSON.stringify({ bankId: targetBank, success: true, response });
      },
    });
  }
}

module.exports = { nodeClass: ContextBaseRetain_Tools };
