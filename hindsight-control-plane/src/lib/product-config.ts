/** One fixed deployment key; never use NEXT_PUBLIC_* for runtime product names. */
export interface ProductConfig {
  product_config_version: 1;
  contextdb_name: string;
}

export function parseProductConfig(value: unknown): ProductConfig {
  if (!value || typeof value !== "object") throw new Error("PRODUCT_CONFIG_INVALID");
  const v = value as Record<string, unknown>;
  if (
    Object.keys(v).sort().join(",") !== "contextdb_name,product_config_version" ||
    v.product_config_version !== 1 ||
    typeof v.contextdb_name !== "string" ||
    v.contextdb_name.trim() !== v.contextdb_name ||
    !/^[a-z][a-z0-9-]{0,39}$/.test(v.contextdb_name)
  )
    throw new Error("PRODUCT_CONFIG_INVALID");
  return { product_config_version: 1, contextdb_name: v.contextdb_name };
}
