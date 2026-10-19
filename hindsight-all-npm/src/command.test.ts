import { describe, it, expect, vi, afterEach } from "vitest";
import { getEmbedCommand } from "./command.js";
afterEach(() => vi.unstubAllEnvs());
describe("getEmbedCommand", () => {
  it("requires an approved distribution when no checkout is configured", () => {
    vi.stubEnv("AGENTSTRATUM_EMBED_PACKAGE", "");
    expect(() => getEmbedCommand()).toThrow("AGENTSTRATUM_EMBED_PACKAGE");
  });
  it("passes a complete distribution spec without shell interpolation", () => {
    expect(getEmbedCommand({ embedPackage: "agentstratum-embed==0.5.0" })).toEqual([
      "uvx",
      "--quiet",
      "--from",
      "agentstratum-embed==0.5.0",
      "agentstratum-embed",
    ]);
  });
  it("accepts the configured environment distribution", () => {
    vi.stubEnv("AGENTSTRATUM_EMBED_PACKAGE", "agentstratum-embed==0.6.0");
    expect(getEmbedCommand()[3]).toBe("agentstratum-embed==0.6.0");
  });
  it("uses a checkout without requiring a public distribution", () => {
    expect(getEmbedCommand({ embedPackagePath: "/abs/path" })).toEqual([
      "uv",
      "run",
      "--directory",
      "/abs/path",
      "agentstratum-embed",
    ]);
  });
});
