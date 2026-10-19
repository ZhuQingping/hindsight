/** Versioned non-secret contracts. v1 remains accepted without relaxing its keys. */
interface LegacyProductConfig {
  product_config_version: 1;
  contextdb_name: string;
}
interface DisplayProductConfig {
  product_config_version: 2;
  contextdb_name: string;
  display_name: string;
}
type ProductConfig = LegacyProductConfig | DisplayProductConfig;

export function parseProductConfig(value: unknown): ProductConfig {
  if (!value || typeof value !== "object") throw new Error("PRODUCT_CONFIG_INVALID");
  const v = value as Record<string, unknown>;
  const keys = Object.keys(v).sort().join(",");
  if (
    typeof v.contextdb_name !== "string" ||
    v.contextdb_name.trim() !== v.contextdb_name ||
    !/^[a-z][a-z0-9-]{0,39}$/.test(v.contextdb_name)
  )
    throw new Error("PRODUCT_CONFIG_INVALID");
  if (v.product_config_version === 1 && keys === "contextdb_name,product_config_version") {
    return { product_config_version: 1, contextdb_name: v.contextdb_name };
  }
  if (
    v.product_config_version === 2 &&
    keys === "contextdb_name,display_name,product_config_version" &&
    typeof v.display_name === "string" &&
    v.display_name.trim() === v.display_name &&
    /^[A-Za-z0-9](?:[A-Za-z0-9 ._-]{0,78}[A-Za-z0-9])?$/.test(v.display_name)
  )
    return {
      product_config_version: 2,
      contextdb_name: v.contextdb_name,
      display_name: v.display_name,
    };
  throw new Error("PRODUCT_CONFIG_INVALID");
}

export function productDisplayName(config: ProductConfig): string {
  return config.product_config_version === 2 ? config.display_name : config.contextdb_name;
}
