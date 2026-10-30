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
const brandPattern = /hindsight|agentstratum|vectorize(?:-io|\.io)|retainai/i;
async function auditMode(contextdb) {
  const temp = await mkdtemp(path.join(tmpdir(), "contextbase-browser-"));
  const backendRequests = [];
  let adminAllowed = true;
  let managementFailed = false;
  const userId = "a".repeat(32);
  const keyId = "b".repeat(32);
  const workspaceId = "c".repeat(32);
  const issuedSecret = "synthetic-one-time-customer-key";
  const user = {
    user_id: userId,
    name: "Audit user",
    role: "user",
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
  };
  const key = {
    key_id: keyId,
    user_id: userId,
    name: "Audit key",
    authorization: { mode: "all", permission: "read_write" },
    display_key: null,
    version: 1,
    created_at: "2026-01-01T00:00:00Z",
  };
  let workspace;
  const page = (items) => ({ items, total: items.length, limit: 20, offset: 0 });
  const backend = createServer(async (request, response) => {
    const pathname = new URL(request.url, "http://backend.invalid").pathname;
    backendRequests.push({
      url: request.url,
      method: request.method,
      authorization: request.headers.authorization,
    });
    response.setHeader("Content-Type", "application/json");
    response.setHeader("X-Internal-Service", "Hindsight-private");
    const json = (value, status = 200) => {
      response.statusCode = status;
      response.end(JSON.stringify(value));
    };
    if (pathname === "/product-config/v2")
      return json({
        product_config_version: 2,
        contextdb_name: "contextbase",
        display_name: "ContextBase",
      });
    if (pathname.startsWith("/version")) return json({ version: "test", features: {} });
    // Managed writes use Bank REST; workspace endpoints are read-only metadata.
    if (contextdb && pathname === "/v1/default/banks/audit_workspace") {
      if (request.headers.authorization !== `Bearer ${apiKey}` || !adminAllowed)
        return json({ code: "admin_required", message: "Administrator access required" }, 403);
      response.setHeader("X-Request-ID", "bank-audit-request");
      if (managementFailed) {
        response.setHeader("Retry-After", "30");
        return json({ detail: "Hindsight private trace", secret: apiKey }, 503);
      }
      if (request.method === "PUT") {
        assert.equal(request.headers["if-none-match"], "*");
        if (workspace) return json({ code: "precondition_failed" }, 412);
        let raw = "";
        for await (const chunk of request) raw += chunk;
        const input = JSON.parse(raw);
        workspace = {
          workspace_id: workspaceId,
          bank_id: "audit_workspace",
          name: "audit_workspace",
          description: input.description,
          state: "active",
          version: 1,
          created_at: "2026-01-01T00:00:00Z",
          etag: `"${workspaceId}:1"`,
        };
        response.setHeader("X-ContextDB-Workspace-ETag", workspace.etag);
        return json({ bank_id: workspace.bank_id, name: input.name, mission: "" });
      }
      if (request.method === "DELETE") {
        if (!workspace) return json({ code: "not_found" }, 404);
        if (request.headers["if-match"] !== workspace.etag)
          return json({ code: "precondition_failed" }, 412);
        workspace = undefined;
        return json({ success: true, message: "Deleted", deleted_count: 0 });
      }
      return json({ code: "method_not_allowed" }, 405);
    }
    if (pathname.startsWith("/ext/contextdb/v1/")) {
      if (request.headers.authorization !== `Bearer ${apiKey}` || !adminAllowed)
        return json({ code: "admin_required", message: "Administrator access required" }, 403);
      if (pathname.endsWith("/admin/identity")) return json({ role: "admin", user_id: userId });
      response.setHeader("X-Request-ID", "management-audit-request");
      if (managementFailed) return json({ detail: "Hindsight private trace", secret: apiKey }, 503);
      let raw = "";
      for await (const chunk of request) raw += chunk;
      const input = raw ? JSON.parse(raw) : {};
      const resource = pathname.slice("/ext/contextdb/v1".length);
      if (resource === "/users")
        return json(
          request.method === "POST" ? { ...user, name: input.name } : page([user]),
          request.method === "POST" ? 201 : 200
        );
      if (resource === `/users/${userId}/keys`) {
        if (request.method === "POST") return json({ ...key, secret: issuedSecret }, 201);
        // The browser must not receive secrets/digests on metadata requests, even
        // if an upstream accidentally includes them. Creation is the one exception.
        return json(
          page([{ ...key, secret: issuedSecret, secret_digest: "synthetic-private-digest" }])
        );
      }
      if (resource === "/workspaces") {
        if (request.method !== "GET") return json({ code: "method_not_allowed" }, 405);
        return json(page(workspace ? [workspace] : []));
      }
      if (resource === "/workspaces/audit_workspace") {
        if (request.method !== "GET") return json({ code: "method_not_allowed" }, 405);
        if (!workspace) return json({ code: "not_found", message: "Workspace not found" }, 404);
        response.setHeader("ETag", workspace.etag);
        return json(workspace);
      }
      return json({ code: "not_found", message: "Unknown management route" }, 404);
    }
    if (pathname.includes("/graph") || pathname.includes("/files/retain"))
      return json({ detail: "Hindsight /app/hindsight-api/server.py", key: apiKey }, 503);
    return json({ banks: [], total: 0 });
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
      CONTEXTBASE_CP_CONTEXTDB_ENABLED: String(contextdb),
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
    for (const page of [
      "/dashboard",
      "/connect",
      "/settings",
      "/banks/audit_bank",
      ...(contextdb ? ["/users"] : []),
    ]) {
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
    if (contextdb) {
      for (const resource of ["users", "workspaces"]) {
        const response = await request(`/api/contextdb/${resource}?limit=20&offset=0`);
        assert.equal(response.status, 200);
        inspect(await response.text(), `${resource} directory`);
      }
      const createUser = await request("/api/contextdb/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: user.name, role: user.role }),
      });
      assert.equal(createUser.status, 201);
      const createdUser = await createUser.json();
      assert.equal(createdUser.user_id, userId);
      inspect(JSON.stringify(createdUser), "created user");
      const createKey = await request(`/api/contextdb/users/${userId}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: key.name, authorization: key.authorization }),
      });
      assert.equal(createKey.status, 201);
      const createdKey = await createKey.json();
      assert.equal(createdKey.secret, issuedSecret);
      inspect(JSON.stringify(createdKey), "one-time key creation");
      const keys = await request(`/api/contextdb/users/${userId}/keys`);
      assert.equal(keys.status, 200);
      const keyMetadata = await keys.text();
      assert(!keyMetadata.includes(issuedSecret));
      assert(!keyMetadata.includes("synthetic-private-digest"));
      inspect(keyMetadata, "key metadata without secrets");
      const requestsBeforeRetiredWrites = backendRequests.length;
      for (const [url, method] of [
        ["/api/contextdb/workspaces", "POST"],
        ["/api/contextdb/workspaces/audit_workspace", "DELETE"],
      ])
        assert.equal((await request(url, { method })).status, 404);
      assert(
        backendRequests.slice(requestsBeforeRetiredWrites).every((entry) => entry.method === "GET")
      );
      const createWorkspace = await request("/api/banks/audit_workspace", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "If-None-Match": "*" },
        body: JSON.stringify({ name: "audit_workspace", description: "Audit workspace" }),
      });
      assert.equal(createWorkspace.status, 200);
      const createdBank = await createWorkspace.json();
      assert.equal(createdBank.bank_id, "audit_workspace");
      const createdIdentity = createWorkspace.headers.get("x-contextdb-workspace-etag");
      assert.equal(createdIdentity, `"${workspaceId}:1"`);
      inspect(JSON.stringify(createdBank), "created Bank");
      const readWorkspace = await request("/api/contextdb/workspaces/audit_workspace");
      assert.equal(readWorkspace.status, 200);
      const createdWorkspace = await readWorkspace.json();
      assert.equal(readWorkspace.headers.get("etag"), createdIdentity);
      assert.equal(createdWorkspace.etag, createdIdentity);
      assert.equal(createdWorkspace.workspace_id, workspaceId);
      assert.equal(createdWorkspace.description, "Audit workspace");
      inspect(JSON.stringify(createdWorkspace), "workspace metadata");
      const deleteWorkspace = await request("/api/banks/audit_workspace", {
        method: "DELETE",
        headers: { "If-Match": createdIdentity },
      });
      assert.equal(deleteWorkspace.status, 200);
      const deletedBank = await deleteWorkspace.json();
      assert.equal(deletedBank.success, true);
      inspect(JSON.stringify(deletedBank), "deleted Bank");
      assert.equal((await request("/api/contextdb/workspaces/audit_workspace")).status, 404);
      managementFailed = true;
      const bankFailure = await request("/api/banks/audit_workspace", {
        method: "PUT",
        headers: { "Content-Type": "application/json", "If-None-Match": "*" },
        body: JSON.stringify({ name: "audit_workspace" }),
      });
      assert.equal(bankFailure.status, 503);
      assert.equal(bankFailure.headers.get("x-request-id"), "bank-audit-request");
      assert.equal(bankFailure.headers.get("retry-after"), "30");
      assert(bankFailure.headers.get("cache-control").includes("no-store"));
      inspect(await bankFailure.text(), "Bank error");
      const failure = await request("/api/contextdb/users");
      assert.equal(failure.status, 503);
      assert.equal(failure.headers.get("x-request-id"), "management-audit-request");
      assert(failure.headers.get("cache-control").includes("no-store"));
      inspect(await failure.text(), "management error");
      managementFailed = false;
      adminAllowed = false;
      const revoked = await request("/api/banks");
      assert.equal(revoked.status, 403);
      inspect(await revoked.text(), "revoked admin authority");
      adminAllowed = true;
      assert(
        backendRequests
          .filter(
            (entry) =>
              entry.url.startsWith("/ext/contextdb/") ||
              entry.url === "/v1/default/banks/audit_workspace"
          )
          .every((entry) => entry.authorization === `Bearer ${apiKey}`)
      );
    } else assert.equal((await request("/api/contextdb/users")).status, 404);
    const banks = await request("/api/banks");
    assert.equal(banks.status, 200);
    inspect(await banks.text(), "successful API response");
    assert(backendRequests.some((entry) => entry.authorization === `Bearer ${apiKey}`));
    assert.equal((await request("/api/auth/logout", { method: "POST" })).status, 200);
    assert.equal((await request("/api/banks")).status, 401);
    console.log(
      `Production HTTP audit passed (${contextdb ? "management" : "native"} mode, ${inspected} payload/header checks, ${assets.size} loaded assets; local stub backend).`
    );
  } finally {
    if (server.exitCode === null && server.signalCode === null) {
      const exited = once(server, "exit");
      server.kill("SIGTERM");
      await exited;
    }
    await new Promise((resolve) => backend.close(resolve));
    await rm(temp, { recursive: true, force: true });
  }
}

for (const contextdb of [false, true]) await auditMode(contextdb);
