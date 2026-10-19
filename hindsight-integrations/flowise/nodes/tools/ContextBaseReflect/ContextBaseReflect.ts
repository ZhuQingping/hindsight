import { DynamicStructuredTool } from "@langchain/core/tools";
import { HindsightClient } from "@vectorize-io/hindsight-client";
import { z } from "zod";

import { ICommonObject, INode, INodeData, INodeParams } from "../../../src/Interface";
import { getBaseClasses, getCredentialData, getCredentialParam } from "../../../src/utils";

// Each node dir is copied into Flowise on its own, so there is no shared module or
// package.json to read a version from.
const USER_AGENT = "contextbase-flowise";

const ReflectSchema = z.object({
  bankId: z.string().describe("The ContextBase memory bank to reflect on."),
  query: z.string().describe("Question to answer using the bank."),
  budget: z
    .enum(["low", "mid", "high"])
    .optional()
    .describe("Reflect budget: low/mid/high. Higher values consider more memories at higher cost."),
});

class ContextBaseReflect_Tools implements INode {
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
    this.label = "ContextBase Reflect";
    this.name = "contextbaseReflect";
    this.version = 1.0;
    this.type = "ContextBaseReflect";
    this.icon = "contextbase.svg";
    this.category = "Tools";
    this.description =
      'Get an LLM-synthesized answer over a ContextBase memory bank. Useful for "what do we know about X?" style questions.';
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
          "Default memory bank to reflect on when the agent does not pass one. Banks are created on first use.",
        placeholder: "user-123",
        optional: true,
      },
      {
        label: "Default Budget",
        name: "budget",
        type: "options",
        options: [
          { label: "Low", name: "low" },
          { label: "Mid", name: "mid" },
          { label: "High", name: "high" },
        ],
        default: "mid",
        optional: true,
        description: "Default reflect budget when the agent does not pass one.",
      },
    ];
    this.baseClasses = [this.type, ...getBaseClasses(DynamicStructuredTool)];
  }

  async init(nodeData: INodeData, _: string, options: ICommonObject): Promise<unknown> {
    const credentialData = await getCredentialData(nodeData.credential ?? "", options);
    const apiUrl = getCredentialParam("apiUrl", credentialData, nodeData) || "";
    const apiKey = getCredentialParam("apiKey", credentialData, nodeData);

    const defaultBankId = (nodeData.inputs?.bankId as string) || "";
    const defaultBudget = ((nodeData.inputs?.budget as string) || "mid") as "low" | "mid" | "high";

    if (!apiUrl.trim()) throw new Error("Configure the ContextBase API URL in credentials.");
    const client = new HindsightClient({
      baseUrl: apiUrl,
      ...(apiKey ? { apiKey } : {}),
      userAgent: USER_AGENT,
    });

    return new DynamicStructuredTool({
      name: "contextbase_reflect",
      description:
        'Ask a question over a ContextBase memory bank and get an LLM-synthesized answer that pulls from many memories. Use for open-ended "what do we know about X?" or "what should we do?" questions.',
      schema: ReflectSchema as any,
      func: async ({
        bankId,
        query,
        budget,
      }: {
        bankId: string;
        query: string;
        budget?: "low" | "mid" | "high";
      }) => {
        const targetBank = bankId || defaultBankId;
        if (!targetBank) {
          return "Error: bankId is required (no default bank configured on the node).";
        }
        const response = await client.reflect(targetBank, query, {
          budget: budget || defaultBudget,
        });
        return JSON.stringify(response);
      },
    });
  }
}

module.exports = { nodeClass: ContextBaseReflect_Tools };
