import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values, positionals: explicitRoots } = parseArgs({
  options: { "project-root": { type: "string" } },
  allowPositionals: true,
});
const root = path.resolve(
  values["project-root"] || path.join(path.dirname(fileURLToPath(import.meta.url)), "..")
);
const roots = explicitRoots.length
  ? explicitRoots.map((value) => ({ directory: path.resolve(value), htmlOnly: false }))
  : [
      { directory: path.join(root, ".next/static"), htmlOnly: false },
      { directory: path.join(root, "public"), htmlOnly: false },
      { directory: path.join(root, ".next/server/app"), htmlOnly: true },
      // Scan the packaged HTML/RSC that the standalone server actually serves.
      // If packaging has started, missing output is a failure, not an exemption.
      ...(existsSync(path.join(root, "standalone"))
        ? [
            { directory: path.join(root, "standalone/.next/static"), htmlOnly: false },
            { directory: path.join(root, "standalone/public"), htmlOnly: false },
            { directory: path.join(root, "standalone/.next/server/app"), htmlOnly: true },
          ]
        : []),
    ];
const oldBrand = /hindsight|agentstratum|vectorize(?:-io|\.io)|retainai/i;
// Raster images cannot be audited by searching decoded text. Reject the exact
// retired upstream logo/icon too, including copies saved under another name.
const retiredImages = new Set([
  "ebfe1d20274e354fa017cc55c8b6cf431b1226ef1d1d7c6d80333f5dc9c376d3",
  "6a9f82908ded489a9b86777e9bde54efb3652384abf87dc299616b45fdc915cb",
]);
const failures = [];
let scanned = 0;

function scan(directory, htmlOnly, relative = "") {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const filename = path.join(directory, entry.name);
    const localPath = path.join(relative, entry.name);
    if (entry.isDirectory()) scan(filename, htmlOnly, localPath);
    else if (entry.isFile()) {
      if (htmlOnly && !/\.(html|rsc)$/.test(entry.name)) continue;
      scanned++;
      // Inspect relative public URLs, not the repository's private directory name.
      if (oldBrand.test(localPath)) failures.push(`${filename}: legacy resource name`);
      const bytes = readFileSync(filename);
      if (retiredImages.has(createHash("sha256").update(bytes).digest("hex")))
        failures.push(`${filename}: retired brand image`);
      if (/\.(html|rsc|js|mjs|css|svg|json|txt|xml|webmanifest|map)$/i.test(entry.name)) {
        const content = bytes.toString("utf8");
        if (oldBrand.test(content)) failures.push(`${filename}: legacy brand text`);
        if (/sourceMappingURL|sourceURL\s*=/.test(content))
          failures.push(`${filename}: public source reference`);
        // Set only synthetic markers in CI; never print actual config values.
        for (const marker of (process.env.BROWSER_AUDIT_PRIVATE_MARKERS || "")
          .split(",")
          .filter(Boolean))
          if (content.includes(marker)) failures.push(`${filename}: private config marker`);
      }
      if (/\.map$/i.test(entry.name)) failures.push(`${filename}: public source map`);
    }
  }
}

for (const { directory, htmlOnly } of roots) {
  if (!existsSync(directory)) failures.push(`${directory}: missing audit root`);
  else scan(directory, htmlOnly);
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exitCode = 1;
} else console.log(`Browser artifact audit passed (${scanned} files).`);
