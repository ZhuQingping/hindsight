import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, expect, it } from "vitest";

const scanner = path.resolve("scripts/audit-browser-artifacts.mjs");
const directories: string[] = [];
afterEach(() =>
  directories.splice(0).forEach((directory) => rmSync(directory, { recursive: true }))
);

function fixture(filename: string, content: string) {
  const directory = mkdtempSync(path.join(tmpdir(), "browser-audit-"));
  directories.push(directory);
  writeFileSync(path.join(directory, filename), content);
  return directory;
}

it("accepts branded public content", () => {
  expect(
    execFileSync(process.execPath, [scanner, fixture("index.html", "ContextBase")], {
      encoding: "utf8",
    })
  ).toContain("passed");
});

it.each([
  ["chunk.js", 'window.dispatchEvent(new Event("hindsight:create-bank"))'],
  ["hindsight.css", "body{}"],
  ["chunk.js.map", '{"sources":["internal.ts"]}'],
  ["chunk.js", "//# sourceMappingURL=chunk.map"],
  ["index.html", "synthetic-private-marker"],
])("rejects leaked public artifact %s", (filename, content) => {
  const result = spawnSync(process.execPath, [scanner, fixture(filename, content)], {
    encoding: "utf8",
    env: { ...process.env, BROWSER_AUDIT_PRIVATE_MARKERS: "synthetic-private-marker" },
  });
  expect(result.status).toBe(1);
  expect(result.stderr).toContain(filename);
});
