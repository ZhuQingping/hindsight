// Packaged-client smoke test against a business-key-only HTTP fixture.
// Run after npm run build; no live service, LLM, or customer credentials are used.
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
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
  // Release checks pass the audited public tarball; local tests can still pack the checkout.
  const tarball = process.argv[2]
    ? resolve(process.argv[2])
    : join(
        home,
        JSON.parse(
          execFileSync("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", home], {
            cwd: root,
            encoding: "utf8",
            maxBuffer: 1024 * 1024,
          })
        )[0].filename
      );
  execFileSync(
    "npm",
    [
      "exec",
      "--yes",
      "--cache",
      join(home, "npm-cache"),
      "--package=" + tarball,
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
  // Exercise the registrations the installer writes, including the CLI's different schema.
  const codeartsIdePath = join(home, "CodeArts settings", "mcp_settings.json");
  for (const harness of ["codearts-agent", "codearts-cli"]) {
    execFileSync(
      process.execPath,
      [
        join(home, ".contextbase", "coding-agents", "dist", "installer.js"),
        "install",
        harness,
        "--api-url",
        `http://127.0.0.1:${server.address().port}`,
        "--bank-id",
        "customer-bank",
        ...(harness === "codearts-agent" ? ["--mcp-config", codeartsIdePath] : []),
      ],
      { env, cwd: project, stdio: "pipe", timeout: 60000 }
    );
  }
  const cfg = JSON.parse(readFileSync(env.CONTEXTBASE_CONFIG));
  assert.equal(cfg.bankId, "customer-bank");
  assert.equal(cfg.mapPathToBank, undefined);
  assert.equal(cfg.banks["customer-bank"].autoSeed, false);
  // Inspect the customer's installed runtime, not just source files: bundling preserves class
  // names and source-path comments that are otherwise easy to miss during a brand rename.
  const dist = join(home, ".contextbase", "coding-agents", "dist");
  // package.json is copied alongside dist into the customer's runtime, including devDependencies.
  // A build-only file: reference can therefore leak repository internals even when npm omits it.
  const manifestText = readFileSync(join(dist, "..", "package.json"), "utf8");
  assert(!/contextbase|contextbase-local-engine/i.test(manifestText), "installed package metadata");
  const manifest = JSON.parse(manifestText);
  if (process.argv[2]) {
    const sourceManifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
    assert.equal(manifest.name, "@huaweicloud/contextbase-coding-agents");
    assert.equal(manifest.name, sourceManifest.name);
    assert.equal(manifest.bin["contextbase-coding-agents"], "dist/installer.js");
    assert.equal(manifest.version, sourceManifest.version);
    for (const field of [
      "private",
      "repository",
      "bugs",
      "homepage",
      "gitHead",
      "scripts",
      "devDependencies",
    ]) {
      assert(!(field in manifest), `public manifest must omit ${field}`);
    }
    assert(!readdirSync(join(dist, "..")).includes("LICENSE"));
  }
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
      assert(!/contextbase/i.test(readFileSync(join(dist, file), "utf8")), file);
    }
  }
  for (const harness of [
    "claude-code",
    "codex",
    "cursor-cli",
    "dsh",
    "opencode",
    "opencode2",
    "pi",
    "workbuddy",
    "codearts-agent",
    "codearts-cli",
  ]) {
    client = new Client({ name: "customer-smoke", version: "1.0" });
    let registration;
    if (harness === "codearts-agent") {
      registration = JSON.parse(readFileSync(codeartsIdePath, "utf8")).mcpServers.contextbase;
    } else if (harness === "codearts-cli") {
      const entry = JSON.parse(
        readFileSync(join(home, ".codeartsdoer", "codearts_cli.jsonc"), "utf8")
      ).mcp.contextbase;
      assert.equal(entry.type, "local");
      registration = {
        command: entry.command[0],
        args: entry.command.slice(1),
        env: entry.environment,
      };
    }
    const transport = new StdioClientTransport({
      command: registration?.command ?? process.execPath,
      args: registration?.args ?? [
        join(home, ".contextbase", "coding-agents", "dist", "mcp-server.js"),
      ],
      env: registration
        ? { ...env, ...registration.env }
        : { ...env, CONTEXTBASE_MCP_HARNESS: harness },
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
    if (harness === "claude-code" || harness === "codearts-agent") {
      const ingested = await client.callTool({
        name: "contextbase_ingest_document",
        arguments: { title: "Customer decision", content: "CB-SMOKE-7429: keep rollback scripts" },
      });
      assert(!ingested.isError);
    } else if (harness === "codex" || harness === "codearts-cli") {
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
    [
      "/v1/default/banks/customer-bank/memories",
      "/v1/default/banks/customer-bank/reflect",
      "/v1/default/banks/customer-bank/memories",
      "/v1/default/banks/customer-bank/reflect",
    ]
  );
  assert(received.every((r) => r.auth === "Bearer customer-key"));
  const switched = execFileSync(
    process.execPath,
    [join(dist, "installer.js"), "bank", "use", "next-workspace"],
    { env, cwd: home, encoding: "utf8" }
  );
  assert.match(switched, /next-workspace/);
  const switchedConfig = JSON.parse(readFileSync(env.CONTEXTBASE_CONFIG, "utf8"));
  assert.equal(switchedConfig.bankId, "next-workspace");
  assert.equal(switchedConfig.apiUrl, cfg.apiUrl);
  assert.equal(switchedConfig.apiToken, cfg.apiToken);
  assert.equal(received.length, 4, "switching must not call workspace administration APIs");

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
    "PASS: packed tgz install -> branded runtime/logs -> MCP diagnosis -> Claude/CodeArts IDE write -> Codex/CodeArts CLI reflect; only business-key memory endpoints called (HTTP fixture, no real model)."
  );
} finally {
  await client?.close();
  await new Promise((r) => server.close(r));
  rmSync(home, { recursive: true, force: true });
}
