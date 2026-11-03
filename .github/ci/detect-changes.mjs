import { execFileSync } from "node:child_process";
import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import picomatch from "picomatch";
import { parse } from "yaml";

export function selectChanges(filters, files, all = false) {
  return Object.fromEntries(
    Object.entries(filters).map(([name, patterns]) => [
      name,
      all ||
        patterns.some((pattern) => {
          const matches = picomatch(pattern, { dot: true });
          return files.some((file) => matches(file));
        }),
    ])
  );
}

export function changedPaths(pages) {
  // Include the old name too: moving a file out of a package can break it.
  return pages
    .flat()
    .flatMap((file) =>
      file.previous_filename ? [file.filename, file.previous_filename] : [file.filename]
    );
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const filters = parse(readFileSync(new URL("./paths.yaml", import.meta.url), "utf8"));
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
  const all = process.env.GITHUB_EVENT_NAME === "workflow_dispatch";
  let files = [];
  if (!all) {
    const number = event.pull_request?.number;
    if (!Number.isSafeInteger(number)) throw new Error("Missing pull request number");
    const pages = JSON.parse(
      execFileSync(
        "gh",
        [
          "api",
          "--paginate",
          "--slurp",
          `repos/${process.env.GITHUB_REPOSITORY}/pulls/${number}/files?per_page=100`,
        ],
        { encoding: "utf8", maxBuffer: 32 * 1024 * 1024 }
      )
    );
    files = changedPaths(pages);
    // GitHub caps this endpoint at 3000 files. Fail closed if it was truncated.
    if (pages.flat().length !== event.pull_request.changed_files) {
      throw new Error("Incomplete pull request file list; refusing to skip tests");
    }
  }
  const results = selectChanges(filters, files, all);
  appendFileSync(
    process.env.GITHUB_OUTPUT,
    Object.entries(results)
      .map(([name, value]) => `${name}=${value}\n`)
      .join("")
  );
}
