import { describe, it, expect } from "vitest";
import { hasContextBasePolicy, mergeContextBasePolicy, serializePolicy } from "./policy-writer.js";
import { parseSandboxPolicy } from "./policy-reader.js";
import type { SandboxPolicy } from "./types.js";
import { OPENCLAW_BINARY } from "./types.js";

const CONTEXTBASE_HOST = "memory.example.com";
const API_URL = `https://${CONTEXTBASE_HOST}:8443`;

const BASE_POLICY: SandboxPolicy = {
  version: 1,
  filesystem_policy: {
    include_workdir: true,
    read_only: ["/usr", "/lib"],
    read_write: ["/sandbox", "/tmp"],
  },
  network_policies: {
    claude_code: {
      name: "claude_code",
      endpoints: [
        {
          host: "api.anthropic.com",
          port: 443,
          rules: [{ allow: { method: "*", path: "/**" } }],
        },
      ],
      binaries: [{ path: "/usr/local/bin/claude" }],
    },
  },
};

describe("hasContextBasePolicy", () => {
  it("returns false when no contextbase policy exists", () => {
    expect(hasContextBasePolicy(BASE_POLICY, API_URL)).toBe(false);
  });

  it("returns false when network_policies is undefined", () => {
    expect(hasContextBasePolicy({ version: 1 }, API_URL)).toBe(false);
  });

  it("returns true when contextbase policy is present", () => {
    const withContextBase = mergeContextBasePolicy(BASE_POLICY, API_URL);
    expect(hasContextBasePolicy(withContextBase, API_URL)).toBe(true);
  });
});

describe("mergeContextBasePolicy", () => {
  it("adds the contextbase network policy block", () => {
    const result = mergeContextBasePolicy(BASE_POLICY, API_URL);
    expect(result.network_policies?.contextbase).toBeDefined();
    expect(result.network_policies?.contextbase?.endpoints[0].host).toBe(CONTEXTBASE_HOST);
  });

  it("preserves all existing network policies", () => {
    const result = mergeContextBasePolicy(BASE_POLICY, API_URL);
    expect(result.network_policies?.claude_code).toBeDefined();
    expect(result.network_policies?.claude_code?.name).toBe("claude_code");
  });

  it("sets the correct binary path", () => {
    const result = mergeContextBasePolicy(BASE_POLICY, API_URL);
    const binaries = result.network_policies?.contextbase?.binaries ?? [];
    expect(binaries.some((b) => b.path === OPENCLAW_BINARY)).toBe(true);
  });

  it("includes GET, POST, and PUT rules", () => {
    const result = mergeContextBasePolicy(BASE_POLICY, API_URL);
    const rules = result.network_policies?.contextbase?.endpoints[0].rules ?? [];
    const methods = rules.map((r) => r.allow.method);
    expect(methods).toContain("GET");
    expect(methods).toContain("POST");
    expect(methods).toContain("PUT");
  });

  it("is idempotent — merging twice yields the same result", () => {
    const once = mergeContextBasePolicy(BASE_POLICY, API_URL);
    const twice = mergeContextBasePolicy(once, API_URL);
    expect(JSON.stringify(twice.network_policies?.contextbase)).toBe(
      JSON.stringify(once.network_policies?.contextbase)
    );
  });

  it("does not mutate the original policy", () => {
    const original = JSON.parse(JSON.stringify(BASE_POLICY)) as SandboxPolicy;
    mergeContextBasePolicy(BASE_POLICY, API_URL);
    expect(BASE_POLICY.network_policies?.contextbase).toBeUndefined();
    expect(JSON.stringify(BASE_POLICY)).toBe(JSON.stringify(original));
  });
});

describe("serializePolicy", () => {
  it("produces valid YAML that round-trips through parseSandboxPolicy", () => {
    const merged = mergeContextBasePolicy(BASE_POLICY, API_URL);
    const yamlStr = serializePolicy(merged);
    // Wrap in Policy: header as parseSandboxPolicy expects
    const wrapped =
      "Policy:\n" +
      yamlStr
        .split("\n")
        .map((l) => `  ${l}`)
        .join("\n");
    const reparsed = parseSandboxPolicy(wrapped);
    expect(reparsed.version).toBe(merged.version);
    expect(reparsed.network_policies?.contextbase?.endpoints[0].host).toBe(CONTEXTBASE_HOST);
    expect(reparsed.network_policies?.claude_code).toBeDefined();
  });

  it("includes all network policies in output", () => {
    const merged = mergeContextBasePolicy(BASE_POLICY, API_URL);
    const yaml = serializePolicy(merged);
    expect(yaml).toContain("claude_code:");
    expect(yaml).toContain("contextbase:");
    expect(yaml).toContain(CONTEXTBASE_HOST);
  });
});

it("authorizes only the configured deployment host and port", () => {
  const policy = mergeContextBasePolicy(BASE_POLICY, API_URL);
  expect(policy.network_policies?.contextbase?.endpoints[0]).toMatchObject({
    host: "memory.example.com",
    port: 8443,
  });
  expect(hasContextBasePolicy(policy, "https://other.example.com:8443")).toBe(false);
  expect(hasContextBasePolicy(policy, "https://memory.example.com")).toBe(false);
});
