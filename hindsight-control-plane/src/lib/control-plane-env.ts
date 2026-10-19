/** Public deployment settings take precedence over the engine's internal keys. */
export function controlPlaneEnv(name: string): string | undefined {
  return process.env[`CONTEXTBASE_CP_${name}`] ?? process.env[`HINDSIGHT_CP_${name}`];
}
