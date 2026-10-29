import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
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
  ["chunk.js", 'window.productName="AgentStratum";'],
  ["agentstratum.css", "body{}"],
])("rejects leaked public artifact %s", (filename, content) => {
  const result = spawnSync(process.execPath, [scanner, fixture(filename, content)], {
    encoding: "utf8",
    env: { ...process.env, BROWSER_AUDIT_PRIVATE_MARKERS: "synthetic-private-marker" },
  });
  expect(result.status).toBe(1);
  expect(result.stderr).toContain(filename);
});

function packagedProject() {
  const directory = fixture("README.txt", "ContextBase");
  for (const name of [
    ".next/static",
    "public",
    ".next/server/app",
    "standalone/.next/static",
    "standalone/public",
    "standalone/.next/server/app",
  ])
    mkdirSync(path.join(directory, name), { recursive: true });
  return directory;
}

it("accepts a clean complete standalone package", () => {
  const directory = packagedProject();
  writeFileSync(path.join(directory, "standalone/.next/server/app/index.html"), "ContextBase");
  expect(spawnSync(process.execPath, [scanner, "--project-root", directory]).status).toBe(0);
});

it.each(["_not-found.html", "index.rsc"])(
  "rejects old branding present only in packaged %s",
  (filename) => {
    const directory = packagedProject();
    writeFileSync(path.join(directory, "standalone/.next/server/app", filename), "Hindsight");
    const result = spawnSync(process.execPath, [scanner, "--project-root", directory], {
      encoding: "utf8",
    });
    expect(result.status).toBe(1);
    expect(result.stderr).toContain(path.join("standalone/.next/server/app", filename));
  }
);

it("rejects an incomplete standalone package", () => {
  const directory = packagedProject();
  rmSync(path.join(directory, "standalone/.next/server/app"), { recursive: true });
  const result = spawnSync(process.execPath, [scanner, "--project-root", directory], {
    encoding: "utf8",
  });
  expect(result.status).toBe(1);
  expect(result.stderr).toContain("missing audit root");
});
