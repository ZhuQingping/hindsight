import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { parse } from "yaml";
import { changedPaths, selectChanges } from "./detect-changes.mjs";

const filters = parse(readFileSync(new URL("./paths.yaml", import.meta.url), "utf8"));

test("root lockfiles do not match nested integration lockfiles", () => {
  assert.equal(selectChanges(filters, ["uv.lock"]).core, true);
  const result = selectChanges(filters, ["hindsight-integrations/hermes/uv.lock"]);
  assert.equal(result.core, false);
  assert.equal(result["integrations-hermes"], true);
});

test("system-only changes preserve the lone negation filter", () => {
  assert.equal(
    selectChanges(filters, ["hindsight-system-tests/tests/test_story.py"])["outside-system-tests"],
    false
  );
  assert.equal(selectChanges(filters, ["README.md"])["outside-system-tests"], true);
});

test("dotfiles and one-level integration manifests select the right jobs", () => {
  assert.equal(selectChanges(filters, [".env.example"]).core, true);
  assert.equal(selectChanges(filters, [".github/workflows/test.yml"]).ci, true);
  assert.equal(
    selectChanges(filters, ["hindsight-integrations/coding-agents/package.json"])[
      "integrations-lockfiles"
    ],
    true
  );
  assert.equal(
    selectChanges(filters, ["hindsight-integrations/coding-agents/example/package.json"])[
      "integrations-lockfiles"
    ],
    false
  );
});

test("all paginated files and both sides of a rename are considered", () => {
  const files = changedPaths([
    [{ filename: "README.md", status: "modified" }],
    [
      {
        filename: "archive/client.ts",
        previous_filename: "hindsight-clients/typescript/src/client.ts",
        status: "renamed",
      },
    ],
    [{ filename: "contextbase-control-plane/src/removed.ts", status: "removed" }],
  ]);
  const result = selectChanges(filters, files);
  assert.equal(result["clients-ts"], true);
  assert.equal(result["control-plane"], true);
});

test("manual runs select every filter and empty changes select none", () => {
  assert.ok(Object.values(selectChanges(filters, [], true)).every(Boolean));
  assert.ok(Object.values(selectChanges(filters, [])).every((value) => !value));
});

test("multiple unrelated paths do not select a package", () => {
  const result = selectChanges(filters, ["README.md", "LICENSE", "docs/guide.md"]);
  assert.equal(result.core, false);
  assert.equal(result["control-plane"], false);
  assert.equal(result["outside-system-tests"], true);
});

test("CI uses only organization-approved Actions and exports every filter", () => {
  const workflow = parse(readFileSync(new URL("../workflows/test.yml", import.meta.url), "utf8"));
  const allowed = new Set([
    "actions/checkout@v6",
    "actions/setup-node@v6",
    "actions/setup-python@v6",
    "actions/upload-artifact@v4",
    "dtolnay/rust-toolchain@stable",
    "taiki-e/install-action@v2",
  ]);
  for (const [name, job] of Object.entries(workflow.jobs)) {
    for (const step of job.steps ?? []) {
      if (step.uses) assert.ok(allowed.has(step.uses), `${name}: ${step.uses}`);
    }
  }
  const outputs = workflow.jobs["detect-changes"].outputs;
  assert.deepEqual(
    Object.keys(outputs)
      .filter((key) => key !== "has_secrets")
      .sort(),
    Object.keys(filters).sort()
  );
});
