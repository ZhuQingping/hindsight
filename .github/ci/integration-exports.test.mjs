import assert from "node:assert/strict";
import { existsSync, globSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const root = fileURLToPath(new URL("../../", import.meta.url));

test("every Python integration imports error classes that its errors module defines", () => {
  // These adapters share the same layout but have independent exports. Check
  // the whole family before optional framework dependencies are installed.
  const files = globSync("hindsight-integrations/*/contextbase_*/*.py", { cwd: root });
  let imports = 0;
  for (const file of files) {
    const source = readFileSync(join(root, file), "utf8");
    for (const match of source.matchAll(/^from \.errors import (\w+)$/gm)) {
      const errorsPath = join(root, dirname(file), "errors.py");
      assert.ok(existsSync(errorsPath), `${file}: missing errors.py`);
      const definitions = readFileSync(errorsPath, "utf8");
      assert.match(definitions, new RegExp(`^class ${match[1]}\\b`, "m"), `${file}: ${match[1]}`);
      imports++;
    }
  }
  assert.ok(imports > 0, "no integration error imports were checked");
});
