import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const apiKey = "synthetic-runtime-private-key";
const password = "synthetic-runtime-ui-password";
const brandPattern = /hindsight|vectorize(?:-io|\.io)|retainai/i;
const temp = await mkdtemp(path.join(tmpdir(), "contextbase-browser-"));
const backendRequests = [];
const backend = createServer((request, response) => {
  backendRequests.push({ url: request.url, authorization: request.headers.authorization });
  response.setHeader("Content-Type", "application/json");
  response.setHeader("X-Internal-Service", "Hindsight-private");
  if (request.url === "/product-config/v2")
    response.end(
      JSON.stringify({
        product_config_version: 2,
        contextdb_name: "contextbase",
        display_name: "ContextBase",
      })
    );
  else if (request.url.startsWith("/version"))
    response.end(JSON.stringify({ version: "test", features: {} }));
  else if (request.url.includes("/graph") || request.url.includes("/files/retain")) {
    response.statusCode = 503;
    response.end(JSON.stringify({ detail: "Hindsight /app/hindsight-api/server.py", key: apiKey }));
  } else response.end(JSON.stringify({ banks: [], total: 0 }));
});
backend.listen(0, "127.0.0.1");
await once(backend, "listening");
const backendUrl = `http://127.0.0.1:${backend.address().port}`;
const reservation = createServer();
reservation.listen(0, "127.0.0.1");
await once(reservation, "listening");
const port = reservation.address().port;
await new Promise((resolve) => reservation.close(resolve));
const origin = `http://127.0.0.1:${port}`;
let logs = "";
const server = spawn(process.execPath, [path.join(root, "standalone/server.js")], {
  cwd: root,
  env: {
    ...process.env,
    NODE_ENV: "production",
    HOSTNAME: "127.0.0.1",
    PORT: String(port),
    CONTEXTBASE_CP_AUTH_MODE: "local",
    CONTEXTBASE_CP_ACCESS_KEY: password,
    CONTEXTBASE_CP_PUBLIC_ORIGIN: origin,
    CONTEXTBASE_CP_SESSION_DIR: temp,
    CONTEXTBASE_CP_DATAPLANE_API_URL: backendUrl,
    CONTEXTBASE_CP_DATAPLANE_API_KEY: apiKey,
    CONTEXTBASE_CP_CONTEXTDB_ENABLED: "false",
  },
  stdio: ["ignore", "pipe", "pipe"],
});
server.stdout.on("data", (chunk) => {
  logs += chunk;
});
server.stderr.on("data", (chunk) => {
  logs += chunk;
});
const privateMarkers = [apiKey, password, backendUrl, "synthetic-private-api.invalid"];
let inspected = 0;
function inspect(content, label) {
  assert(!brandPattern.test(content), `${label}: legacy brand`);
  for (const marker of privateMarkers)
    assert(!content.includes(marker), `${label}: private config`);
  inspected++;
}
let cookie = "";
async function request(url, options = {}) {
  const response = await fetch(origin + url, {
    redirect: "manual",
    ...options,
    headers: { Cookie: cookie, Origin: origin, ...options.headers },
    signal: AbortSignal.timeout(15000),
  });
  inspect(JSON.stringify([...response.headers]), `${url} headers`);
  return response;
}

try {
  let ready = false;
  for (let attempt = 0; attempt < 100; attempt++) {
    if (server.exitCode !== null) throw new Error(`Standalone exited: ${logs}`);
    try {
      if ((await fetch(origin + "/api/auth/session")).ok) {
        ready = true;
        break;
      }
    } catch {
      /* Startup has not bound its socket yet. */
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert(ready, "Standalone startup timed out");
  assert.equal((await request("/api/banks")).status, 401);
  for (const locale of ["en", "zh-CN"]) {
    const response = await request("/login", { headers: { "Accept-Language": locale } });
    assert.equal(response.status, 200);
    const html = await response.text();
    assert(html.includes("ContextBase"));
    inspect(html, `${locale} login HTML/RSC`);
  }
  const login = await request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key: password }),
  });
  assert.equal(login.status, 200);
  cookie = login.headers.get("set-cookie").split(";")[0];
  const assets = new Set(["/product-icon.svg"]);
  for (const page of ["/dashboard", "/connect", "/settings", "/banks/audit-bank"]) {
    const response = await request(page);
    assert.equal(response.status, 200, page);
    const html = await response.text();
    inspect(html, `${page} HTML/RSC`);
    for (const match of html.matchAll(/(?:src|href)="([^"?#]+)"/g))
      if (match[1].startsWith("/_next/static/")) assets.add(match[1]);
  }
  for (const asset of assets) {
    const response = await request(asset);
    assert.equal(response.status, 200, asset);
    inspect(await response.text(), asset);
  }
  for (const asset of ["logo.png", "favicon.png"]) {
    const response = await request(`/${asset}`);
    assert.equal(response.status, 200);
    assert.deepEqual(
      Buffer.from(await response.arrayBuffer()),
      await readFile(path.join(root, "public", asset))
    );
  }
  const chunk = (await readdir(path.join(root, ".next/static/chunks"))).find((name) =>
    name.endsWith(".js")
  );
  const map = await request(`/_next/static/chunks/${chunk}.map`);
  assert.equal(map.status, 404);
  inspect(await map.text(), "absent public map response");
  const graph = await request("/api/graph?bank_id=audit-bank");
  assert.equal(graph.status, 503);
  inspect(await graph.text(), "proxied graph error");
  const form = new FormData();
  form.set("request", JSON.stringify({ bank_id: "audit-bank" }));
  form.set("files", new Blob(["customer data"]), "sample.txt");
  const upload = await request("/api/files/retain", { method: "POST", body: form });
  assert.equal(upload.status, 503);
  inspect(await upload.text(), "proxied file error");
  const banks = await request("/api/banks");
  assert.equal(banks.status, 200);
  inspect(await banks.text(), "successful API response");
  assert(backendRequests.some((entry) => entry.authorization === `Bearer ${apiKey}`));
  assert.equal((await request("/api/auth/logout", { method: "POST" })).status, 200);
  assert.equal((await request("/api/banks")).status, 401);
  console.log(
    `Production HTTP audit passed (${inspected} payload/header checks, ${assets.size} loaded assets; local stub backend).`
  );
} finally {
  server.kill("SIGTERM");
  await new Promise((resolve) => backend.close(resolve));
  await rm(temp, { recursive: true, force: true });
}
