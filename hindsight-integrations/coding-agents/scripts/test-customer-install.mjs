// Packaged-client smoke test against a business-key-only HTTP fixture.
// Run after npm run build; no live service, LLM, or customer credentials are used.
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { createServer } from "node:http";
import assert from "node:assert/strict";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const home = mkdtempSync(join(tmpdir(), "contextbase-customer-smoke-"));
const project = join(home, "customer project");
mkdirSync(project);
const received = [];
let saved = "";
const server = createServer(async (req, res) => {
  let body = "";
  for await (const chunk of req) body += chunk;
  received.push({ method: req.method, url: req.url, auth: req.headers.authorization });
  res.setHeader("Content-Type", "application/json");
  if (req.headers.authorization !== "Bearer customer-key") {
    res.writeHead(401).end("{}");
    return;
  }
  if (req.url === "/v1/default/banks/customer-bank/memories" && req.method === "POST") {
    saved = JSON.parse(body).items[0].content;
    res.end("{}");
  } else if (req.url === "/v1/default/banks/customer-bank/reflect" && req.method === "POST")
    res.end(JSON.stringify({ text: saved }));
  else {
    res.writeHead(403).end('{"detail":"business key cannot administer banks"}');
  }
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const env = {
  ...process.env,
  HOME: home,
  CONTEXTBASE_CONFIG: join(home, "coding-agent.json"),
  CONTEXTBASE_API_TOKEN: "customer-key",
  CONTEXTBASE_CODING_AGENTS_PACKAGE: "",
  CONTEXTBASE_LOG_LEVEL: "debug",
  CONTEXTBASE_LOG_FILE: join(home, "plugin.log"),
};
let client;
try {
  const packed = JSON.parse(
    execFileSync("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", home], {
      cwd: root,
      encoding: "utf8",
      maxBuffer: 1024 * 1024,
    })
  );
  execFileSync(
    "npm",
    [
      "exec",
      "--yes",
      "--cache",
      join(home, "npm-cache"),
      "--package=" + join(home, packed[0].filename),
      "--",
      "contextbase-coding-agents",
      "install",
      "codex",
      "--api-url",
      `http://127.0.0.1:${server.address().port}`,
      "--bank-id",
      "customer-bank",
      "--project-path",
      project,
    ],
    { env, cwd: project, stdio: "pipe", timeout: 60000 }
  );
  const cfg = JSON.parse(readFileSync(env.CONTEXTBASE_CONFIG));
  assert.equal(cfg.mapPathToBank[project], "customer-bank");
  assert.equal(cfg.banks["customer-bank"].autoSeed, false);
  // Inspect the customer's installed runtime, not just source files: bundling preserves class
  // names and source-path comments that are otherwise easy to miss during a brand rename.
  const dist = join(home, ".contextbase", "coding-agents", "dist");
  // package.json is copied alongside dist into the customer's runtime, including devDependencies.
  // A build-only file: reference can therefore leak repository internals even when npm omits it.
  const manifestText = readFileSync(join(dist, "..", "package.json"), "utf8");
  assert(!/hindsight|contextbase-local-engine/i.test(manifestText), "installed package metadata");
  const manifest = JSON.parse(manifestText);
  for (const field of [
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
  ]) {
    for (const version of Object.values(manifest[field] ?? {})) {
      assert(
        !/^(file:|link:|workspace:)/.test(version),
        `${field} must not reference the source checkout`
      );
    }
  }
  assert(!readdirSync(dist).some((file) => file.startsWith("daemon-start")));
  for (const file of readdirSync(dist)) {
    if (file.endsWith(".js") || file.endsWith(".d.ts")) {
      assert(!/hindsight/i.test(readFileSync(join(dist, file), "utf8")), file);
    }
  }
  for (const harness of ["claude-code", "codex"]) {
    client = new Client({ name: "customer-smoke", version: "1.0" });
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [join(home, ".contextbase", "coding-agents", "dist", "mcp-server.js")],
      env: { ...env, CONTEXTBASE_MCP_HARNESS: harness },
      cwd: project,
      stderr: "pipe",
    });
    await client.connect(transport);
    const list = await client.listTools();
    assert(list.tools.some((t) => t.name === "contextbase_ingest_document"));
    const diagnosed = await client.callTool({ name: "contextbase_diagnose", arguments: {} });
    assert(!diagnosed.isError);
    const diagnosis = JSON.parse(diagnosed.content.find((c) => c.type === "text").text);
    assert.equal(diagnosis.bank_id, "customer-bank");
    assert.equal(diagnosis.harness, harness);
    assert.equal(diagnosis.workspace, project);
    if (harness === "claude-code") {
      const ingested = await client.callTool({
        name: "contextbase_ingest_document",
        arguments: { title: "Customer decision", content: "CB-SMOKE-7429: keep rollback scripts" },
      });
      assert(!ingested.isError);
    } else {
      const answer = await client.callTool({
        name: "contextbase_reflect",
        arguments: { query: "What was the decision?" },
      });
      assert(!answer.isError);
      assert(answer.content.some((c) => c.type === "text" && c.text.includes("CB-SMOKE-7429")));
    }
    await client.close();
    client = undefined;
  }
  assert.deepEqual(
    received.map((r) => r.url),
    ["/v1/default/banks/customer-bank/memories", "/v1/default/banks/customer-bank/reflect"]
  );
  assert(received.every((r) => r.auth === "Bearer customer-key"));
  // Exercise the installed hook's logger without issuing another memory request.
  const disabledConfig = join(home, "disabled-hook.json");
  writeFileSync(disabledConfig, JSON.stringify({ ...cfg, disabled: true, logLevel: "debug" }));
  execFileSync(process.execPath, [join(dist, "claude-hook.js")], {
    env: { ...env, CONTEXTBASE_CONFIG: disabledConfig },
    cwd: project,
    input: JSON.stringify({ prompt: "Check installed logging", cwd: project, session_id: "smoke" }),
    encoding: "utf8",
    timeout: 10000,
  });
  const lines = readFileSync(env.CONTEXTBASE_LOG_FILE, "utf8").trimEnd().split("\n");
  assert(lines.length > 0);
  assert(lines.every((line) => /\[contextbase\] \[/.test(line)));
  console.log(
    "PASS: packed tgz install -> branded runtime/logs -> MCP diagnosis -> Claude write -> Codex reflect; only business-key memory endpoints called (HTTP fixture, no real model)."
  );
} finally {
  await client?.close();
  await new Promise((r) => server.close(r));
  rmSync(home, { recursive: true, force: true });
}
