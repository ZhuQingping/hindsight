#!/usr/bin/env node
/** A full generator round-trip in a private fixture, including negative drift detection. */
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, copyFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = mkdtempSync(resolve(tmpdir(), "brand-roundtrip-"));
const ledger = JSON.parse(readFileSync(resolve(root, "brand/GENERATED.json"), "utf8"));
const paths = [
  ...new Set([
    ".prettierrc.json",
    "brand/definition.json",
    "brand/identity-contract.json",
    "brand/templates/install-cli.sh.in",
    "hindsight-clients/python/pyproject.toml",
    "hindsight-clients/typescript/package.json",
    "brand/text-targets.json",
    "hindsight-integrations/agent-plugin/mcp.json",
    "hindsight-integrations/claude-code/.mcp.json",
    ...JSON.parse(readFileSync(resolve(root, "brand/text-targets.json"), "utf8")).map(
      (entry) => entry.template
    ),
    ...ledger.entries.map((entry) => entry.path),
  ]),
];
for (const path of paths) {
  mkdirSync(dirname(resolve(fixture, path)), { recursive: true });
  copyFileSync(resolve(root, path), resolve(fixture, path));
}
const run = (check = false) =>
  spawnSync(
    process.execPath,
    [resolve(root, "scripts/generate-brand.mjs"), "--root", fixture, ...(check ? ["--check"] : [])],
    { encoding: "utf8" }
  );
assert.equal(run().status, 0);
assert.equal(run(true).status, 0);
const original = new Map(
  ledger.entries.map(({ path }) => [path, readFileSync(resolve(fixture, path), "utf8")])
);
const definition = JSON.parse(readFileSync(resolve(fixture, "brand/definition.json"), "utf8"));
writeFileSync(
  resolve(fixture, "brand/definition.json"),
  JSON.stringify(
    { ...definition, display_name: "Atlas Grove", deployment_slug: "atlas-grove" },
    null,
    2
  ) + "\n"
);
assert.equal(run(true).status, 1, "Changing only brand input must detect stale generated outputs");
assert.equal(run().status, 0);
assert.equal(run(true).status, 0);
for (const { path } of ledger.entries) {
  assert.ok(
    readFileSync(resolve(fixture, path), "utf8").includes("Atlas Grove"),
    `Display did not reach ${path}`
  );
}
writeFileSync(
  resolve(fixture, "brand/definition.json"),
  JSON.stringify(definition, null, 2) + "\n"
);
assert.equal(run().status, 0);
assert.equal(run(true).status, 0);
for (const [path, contents] of original)
  assert.equal(readFileSync(resolve(fixture, path), "utf8"), contents, `Restore drift: ${path}`);
for (const invalid of [undefined, null, true, 42, "a\n", "a/b"]) {
  writeFileSync(
    resolve(fixture, "brand/definition.json"),
    JSON.stringify({ ...definition, deployment_slug: invalid })
  );
  assert.notEqual(run().status, 0);
  for (const [path, contents] of original)
    assert.equal(readFileSync(resolve(fixture, path), "utf8"), contents);
}
for (const invalid of [null, "legacy", [null], [42], ["bad\n"]]) {
  writeFileSync(
    resolve(fixture, "brand/definition.json"),
    JSON.stringify({ ...definition, historical_display_names: invalid })
  );
  assert.notEqual(run().status, 0);
  for (const [path, contents] of original)
    assert.equal(readFileSync(resolve(fixture, path), "utf8"), contents);
}
writeFileSync(
  resolve(fixture, "brand/definition.json"),
  JSON.stringify(definition, null, 2) + "\n"
);
const mutations = [
  ...[
    "hindsight-integrations/coding-agents/package.json",
    "hindsight-integrations/coding-agents/plugin.json",
    "hindsight-integrations/agent-plugin/plugin.json",
    "hindsight-integrations/claude-code/.claude-plugin/plugin.json",
  ].map((path) => ({
    path,
    mutate: (value) => {
      value.name = "foreign-name";
    },
  })),
  {
    path: "hindsight-integrations/coding-agents/package.json",
    mutate: (value) => {
      delete value.bin[definition.identity.coding_agents];
    },
  },
  {
    path: "hindsight-integrations/coding-agents/package.json",
    mutate: (value) => {
      value.bin[definition.identity.coding_agents] = "dist/foreign.js";
    },
  },
  ...[
    "hindsight-integrations/coding-agents/plugin.json",
    "hindsight-integrations/agent-plugin/mcp.json",
    "hindsight-integrations/claude-code/.mcp.json",
  ].map((path) => ({
    path,
    mutate: (value) => {
      value.mcpServers = { foreign: {} };
    },
  })),
  {
    path: ".claude-plugin/marketplace.json",
    mutate: (value) => {
      value.plugins.find(
        (plugin) => plugin.source === "./hindsight-integrations/claude-code"
      ).name = "foreign-name";
    },
  },
];
for (const { path, mutate } of mutations) {
  const target = resolve(fixture, path);
  const saved = readFileSync(target, "utf8");
  const value = JSON.parse(saved);
  mutate(value);
  writeFileSync(target, JSON.stringify(value, null, 2) + "\n");
  const before = new Map(
    [...paths, "brand/GENERATED.json"].map((p) => [p, readFileSync(resolve(fixture, p), "utf8")])
  );
  for (const check of [false, true]) {
    assert.notEqual(run(check).status, 0, `Accepted identity drift: ${path}`);
    for (const [p, contents] of before)
      assert.equal(readFileSync(resolve(fixture, p), "utf8"), contents, `Partial write: ${p}`);
  }
  writeFileSync(target, saved);
}
const cargo = resolve(fixture, "hindsight-cli/Cargo.toml");
const savedCargo = readFileSync(cargo, "utf8");
writeFileSync(cargo, savedCargo.replace('name = "contextbase"', 'name = "foreign-name"'));
const savedLedger = readFileSync(resolve(fixture, "brand/GENERATED.json"), "utf8");
for (const check of [false, true]) {
  assert.notEqual(run(check).status, 0);
  assert.equal(readFileSync(resolve(fixture, "brand/GENERATED.json"), "utf8"), savedLedger);
}
writeFileSync(cargo, savedCargo);
assert.equal(run(true).status, 0);
console.log(
  JSON.stringify({
    status: "PASS",
    fixture,
    targets: original.size,
    manual_production_edits: [],
    restored: true,
  })
);
