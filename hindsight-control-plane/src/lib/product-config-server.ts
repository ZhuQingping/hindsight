import "server-only";
import { parseProductConfig } from "./product-config";

export function localProductConfig() {
  return parseProductConfig({
    product_config_version: 1,
    contextdb_name: process.env.contextdb_name ?? "agentstratum",
  });
}

/** No cache: a restarted API must not accept a CP with a different product name. */
export async function verifiedProductConfig() {
  const local = localProductConfig();
  // Use the same native API target as hindsight-client.ts. Product naming must
  // work without the separate hosted user/key-management service.
  const base = (process.env.HINDSIGHT_CP_DATAPLANE_API_URL || "http://localhost:8888").replace(
    /\/$/,
    ""
  );
  const response = await fetch(base + "/product-config", {
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("PRODUCT_CONFIG_UNAVAILABLE");
  const remote = parseProductConfig(await response.json());
  if (remote.contextdb_name !== local.contextdb_name) throw new Error("PRODUCT_CONFIG_MISMATCH");
  return local;
}
