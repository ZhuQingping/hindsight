/** Select an explicitly configured distribution or a local development checkout. */
export interface EmbedCommandOptions {
  /** Retained version metadata; the complete distribution spec controls installation. */
  embedVersion?: string;
  /** Complete Python distribution spec, e.g. an approved wheel URL or package pin. */
  embedPackage?: string;
  embedPackagePath?: string;
}

export function getEmbedCommand(opts: EmbedCommandOptions = {}): string[] {
  if (opts.embedPackagePath) {
    return ["uv", "run", "--directory", opts.embedPackagePath, "agentstratum-embed"];
  }
  const distribution = opts.embedPackage ?? process.env.AGENTSTRATUM_EMBED_PACKAGE;
  if (!distribution?.trim()) {
    throw new Error(
      "Set AGENTSTRATUM_EMBED_PACKAGE to the approved local engine distribution, or configure embedPackagePath."
    );
  }
  return ["uvx", "--quiet", "--from", distribution, "agentstratum-embed"];
}
