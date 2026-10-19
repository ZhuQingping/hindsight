import { describe, expect, it } from "vitest";

import * as credModule from "../credentials/ContextBaseApi.credential";

const ContextBaseApi = (credModule as any).credClass;

describe("ContextBaseApi credential", () => {
  const cred = new ContextBaseApi();

  it("declares the expected name and label", () => {
    expect(cred.name).toBe("contextbaseApi");
    expect(cred.label).toBe("ContextBase API");
    expect(cred.version).toBe(1.0);
  });

  it("exposes apiUrl and apiKey inputs", () => {
    const names = cred.inputs.map((i: { name: string }) => i.name);
    expect(names).toContain("apiUrl");
    expect(names).toContain("apiKey");
  });

  it("requires an explicitly configured API URL", () => {
    const apiUrl = cred.inputs.find((i: { name: string }) => i.name === "apiUrl");
    expect(apiUrl.default).toBe("");
  });

  it("marks apiKey as a password input", () => {
    const apiKey = cred.inputs.find((i: { name: string }) => i.name === "apiKey");
    expect(apiKey.type).toBe("password");
  });

  it("marks apiKey as optional (self-hosted unauthenticated case)", () => {
    const apiKey = cred.inputs.find((i: { name: string }) => i.name === "apiKey");
    expect(apiKey.optional).toBe(true);
  });
});
