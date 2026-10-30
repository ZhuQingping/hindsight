import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// Honor the existing dev PORT so an isolated audit need not claim a user's port.
// Next uses a matching port-scoped distDir outside the default 9999 port.
const port = process.env.PORT || "9999";
const origin = `http://127.0.0.1:${port}`;
const legacy = /hindsight|agentstratum|vectorize(?:-io|\.io)|retainai/i;
let logs = "";
const server = spawn(
  process.execPath,
  [
    path.join(root, "../node_modules/next/dist/bin/next"),
    "dev",
    "--turbopack",
    "--hostname",
    "127.0.0.1",
    "--port",
    port,
  ],
  {
    cwd: root,
    env: {
      ...process.env,
      NODE_ENV: "development",
      PORT: port,
      NEXT_TELEMETRY_DISABLED: "1",
      CONTEXTBASE_CP_AUTH_MODE: "bootstrap",
      CONTEXTBASE_CP_CONTEXTDB_ENABLED: "false",
    },
    stdio: ["ignore", "pipe", "pipe"],
  }
);
const exited = once(server, "exit");
server.stdout.on("data", (chunk) => (logs += chunk));
server.stderr.on("data", (chunk) => (logs += chunk));
try {
  const deadline = Date.now() + 90000;
  // Wait for this process to be ready before requesting anything, so a busy
  // port cannot silently make the audit inspect somebody else's dev server.
  while (!logs.includes("Ready in")) {
    assert.equal(server.exitCode, null, logs);
    assert(Date.now() < deadline, `Dev server startup timed out: ${logs}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  const assets = new Set();
  // Bank pages load the graph, entities and prompt-preview chunks that login
  // pages never request. Include those entrypoints so branding cannot hide in
  // a business-only bundle while the login audit stays green.
  const pages = [
    "/en/login",
    "/zh-CN/login",
    "/en",
    "/zh-CN",
    "/en/banks/browser_audit",
    "/zh-CN/banks/browser_audit",
    "/en/connect",
    "/en/settings",
    "/en/dashboard",
    "/en/guide",
  ];
  for (const page of pages) {
    const response = await fetch(origin + page, { signal: AbortSignal.timeout(60000) });
    assert.equal(response.status, 200, page);
    const html = await response.text();
    assert(!legacy.test(html), `${page}: legacy branding in HTML`);
    for (const match of html.matchAll(/(?:src|href)="([^"]*\/_next\/static\/[^"?#]+)(?:[^\"]*)"/g))
      assets.add(match[1]);
  }
  assert(assets.size > 0, "No development resources were inspected");
  assert([...assets].some((asset) => /contextbase-control-plane.*\.js$/.test(asset)));
  assert([...assets].some((asset) => /contextbase-control-plane.*\.css$/.test(asset)));
  for (const asset of assets) {
    assert(!legacy.test(decodeURIComponent(asset)), `${asset}: legacy resource name`);
    const response = await fetch(origin + asset, { signal: AbortSignal.timeout(30000) });
    assert.equal(response.status, 200, asset);
    let content = await response.text();
    // Next devtools embeds __NEXT_DIST_DIR to locate its diagnostics. Keep that
    // framework-owned value intact at runtime; only its exact generated path is
    // excluded from this development-only assertion. Resource URLs and all app
    // chunks remain strict. Production permits no such path exception.
    if (/\/node_modules_next_dist_compiled_next-devtools_/.test(asset)) {
      const diagnosticsPath = path.join(root, port === "9999" ? ".next" : `.next-${port}`, "dev");
      content = content
        .replaceAll(JSON.stringify(diagnosticsPath).slice(1, -1), "<development-output>")
        .replaceAll(diagnosticsPath, "<development-output>");
    }
    assert(!legacy.test(content), `${asset}: legacy branding in resource`);
  }
  console.log(
    `Development browser brand audit passed: ${pages.length} pages, ${assets.size} resources`
  );
} catch (error) {
  console.error(logs.slice(-4000));
  throw error;
} finally {
  if (server.exitCode === null) server.kill("SIGTERM");
  await exited;
}
