import { controlPlaneEnv } from "@/lib/control-plane-env";
import "server-only";
import { parseProductConfig, productDisplayName } from "./product-config";
import { DEPLOYMENT_SLUG, DISPLAY_NAME } from "./brand-defaults";

export function localProductConfig() {
  const legacy = process.env.contextdb_name;
  const display = process.env.product_display_name;
  // Explicit legacy-only deployments retain the v1 wire contract and old API compatibility.
  if (legacy !== undefined && display === undefined) {
    return parseProductConfig({ product_config_version: 1, contextdb_name: legacy });
  }
  return parseProductConfig({
    product_config_version: 2,
    contextdb_name: legacy ?? DEPLOYMENT_SLUG,
    display_name: display ?? DISPLAY_NAME,
  });
}

export function localProductName(): string {
  return productDisplayName(localProductConfig());
}

/** No cache or downgrade: a restarted API must match both display and deployment slug. */
export async function verifiedProductConfig() {
  const local = localProductConfig();
  const base = (controlPlaneEnv("DATAPLANE_API_URL") || "http://localhost:8888").replace(/\/$/, "");
  const path = local.product_config_version === 1 ? "/product-config" : "/product-config/v2";
  const response = await fetch(base + path, {
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error("PRODUCT_CONFIG_UNAVAILABLE");
  const remote = parseProductConfig(await response.json());
  const displayHeader = response.headers.get("X-Product-Display-Name");
  if (displayHeader !== null && displayHeader !== productDisplayName(local)) {
    throw new Error("PRODUCT_CONFIG_MISMATCH");
  }
  if (
    remote.product_config_version !== local.product_config_version ||
    remote.contextdb_name !== local.contextdb_name ||
    productDisplayName(remote) !== productDisplayName(local)
  ) {
    throw new Error("PRODUCT_CONFIG_MISMATCH");
  }
  return local;
}
