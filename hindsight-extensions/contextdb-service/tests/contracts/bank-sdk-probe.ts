/** Run against fixture-owned services; credentials enter on stdin, never argv. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ContextBaseClient } from "../../../../hindsight-clients/typescript/src/index";
import { createClient } from "../../../../hindsight-clients/typescript/generated/client";
import { deleteBank } from "../../../../hindsight-clients/typescript/generated/sdk.gen";

async function main() {
  const input: { base: string; key: string; bank: string; plugin: boolean } = JSON.parse(
    readFileSync(0, "utf8")
  );
  const headers = input.key ? { Authorization: `Bearer ${input.key}` } : {};
  const client = new ContextBaseClient({ baseUrl: input.base, apiKey: input.key });
  assert.equal(
    (await client.createBank(input.bank, { name: "First TS label" })).name,
    "First TS label"
  );
  assert.equal(
    (await client.createBank(input.bank, { name: "Second TS label" })).name,
    "Second TS label"
  );
  if (!input.plugin) {
    await client.deleteBank(input.bank);
  } else {
    await assert.rejects(client.deleteBank(input.bank), /precondition_required/);
    const detail = await fetch(`${input.base}/ext/contextdb/v1/workspaces/${input.bank}`, {
      headers,
    });
    assert.equal(detail.status, 200);
    const etag = detail.headers.get("etag");
    assert.ok(etag);
    const response = await deleteBank({
      client: createClient({ baseUrl: input.base }),
      path: { bank_id: input.bank },
      headers: { ...headers, "If-Match": etag },
    });
    assert.equal(response.response.status, 200);
    assert.equal(response.error, undefined);
  }
  process.stdout.write("TypeScript high-level create/upsert and deletion contract verified\n");
}

main().catch((error) => {
  // A failing SDK can include request context. Report only the class, not secrets.
  process.stderr.write(`Bank SDK probe failed: ${error.constructor.name}\n`);
  process.exitCode = 1;
});
