import yaml from "js-yaml";
import type { SandboxPolicy } from "./types.js";
import { CONTEXTBASE_POLICY_NAME, OPENCLAW_BINARY } from "./types.js";

function networkPolicy(apiUrl: string) {
  const endpoint = new URL(apiUrl);
  if (endpoint.protocol !== "https:")
    throw new Error("NemoClaw network policy requires an HTTPS API URL");
  return {
    name: CONTEXTBASE_POLICY_NAME,
    endpoints: [
      {
        host: endpoint.hostname,
        port: Number(endpoint.port || 443),
        protocol: "rest",
        tls: "terminate",
        enforcement: "enforce",
        rules: [
          { allow: { method: "GET", path: "/**" } },
          { allow: { method: "POST", path: "/**" } },
          { allow: { method: "PUT", path: "/**" } },
        ],
      },
    ],
    binaries: [{ path: OPENCLAW_BINARY }],
  };
}

/**
 * Returns true if the policy already has a correct ContextBase network policy entry.
 */
export function hasContextBasePolicy(policy: SandboxPolicy, apiUrl: string): boolean {
  const np = policy.network_policies?.[CONTEXTBASE_POLICY_NAME];
  if (!np) return false;
  return (
    np.endpoints?.some(
      (e) => e.host === new URL(apiUrl).hostname && e.port === Number(new URL(apiUrl).port || 443)
    ) ?? false
  );
}

/**
 * Merge the ContextBase network policy block into a SandboxPolicy.
 * Idempotent — if the block already exists and is correct, returns policy unchanged.
 */
export function mergeContextBasePolicy(policy: SandboxPolicy, apiUrl: string): SandboxPolicy {
  const updated: SandboxPolicy = {
    ...policy,
    network_policies: {
      ...(policy.network_policies ?? {}),
      [CONTEXTBASE_POLICY_NAME]: networkPolicy(apiUrl),
    },
  };
  return updated;
}

/**
 * Serialize a SandboxPolicy to a YAML string suitable for `openshell policy set`.
 */
export function serializePolicy(policy: SandboxPolicy): string {
  return yaml.dump(policy, {
    indent: 2,
    lineWidth: -1,
    noRefs: true,
    quotingType: '"',
    forceQuotes: false,
  });
}
