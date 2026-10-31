// Real Chrome clipboard regression: run on macOS and Windows, without a live API.
// Set CLIPBOARD_PLAYWRIGHT_PATH to an isolated installation of playwright@1.57.0.
const assert = require("node:assert/strict");
const { randomUUID } = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { build } = require("esbuild");
const { chromium } = require(process.env.CLIPBOARD_PLAYWRIGHT_PATH || "playwright");

const root = path.resolve(__dirname, "../../../..");
const output = fs.mkdtempSync(path.join(os.tmpdir(), "contextdb-key-copy-"));
let secret;
const user = {
  user_id: "user-a",
  name: "Alice",
  status: "active",
  version: 1,
  created_at: "2026-10-28",
};
const key = {
  key_id: "a".repeat(32),
  user_id: user.user_id,
  name: "Agent",
  display_key: "synthetic-***tail",
  authorization: { mode: "all", permission: "read_write" },
  version: 1,
  created_at: "2026-10-28",
  last_used_at: null,
};
const pageData = (items) => ({ items, total: items.length, limit: 20, offset: 0 });
const entry = `import React from 'react';
import { createRoot } from 'react-dom/client';
import { NextIntlClientProvider } from 'next-intl';
import { ContextDBUserKeysPanel } from '@/components/contextdb/user-keys-panel';
import en from '@/messages/en.json';
import { withContextdbMessages } from '@/i18n/contextdb-messages';
createRoot(document.getElementById('root')).render(
  <NextIntlClientProvider locale="en" messages={withContextdbMessages(en, 'en')}>
    <ContextDBUserKeysPanel user={${JSON.stringify(user)}} />
  </NextIntlClientProvider>);
`;

async function main() {
  let server;
  let browser;
  try {
    await build({
      stdin: { contents: entry, resolveDir: root, loader: "tsx" },
      absWorkingDir: root,
      bundle: true,
      jsx: "automatic",
      platform: "browser",
      outfile: path.join(output, "bundle.js"),
      alias: { "@": path.join(root, "contextbase-control-plane/src") },
      define: { "process.env.NODE_ENV": '"development"', "process.env": "{}" },
    });
    server = http.createServer((req, res) => {
      if (req.url.startsWith("/api/contextdb/")) {
        res.setHeader("Content-Type", "application/json");
        if (req.method === "POST") {
          res.statusCode = 201;
          res.end(JSON.stringify({ ...key, secret }));
        } else res.end(JSON.stringify(pageData(req.url.includes("/workspaces") ? [] : [key])));
      } else if (req.url === "/bundle.js") {
        res.setHeader("Content-Type", "text/javascript");
        res.end(fs.readFileSync(path.join(output, "bundle.js")));
      } else {
        res.setHeader("Content-Type", "text/html");
        res.end(
          '<!doctype html><html lang="en"><body><div id="root"></div><label>Paste target<textarea id="paste-target"></textarea></label><script src="/bundle.js"></script></body></html>'
        );
      }
    });
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, "127.0.0.1", resolve);
    });
    browser = await chromium.launch({
      channel: "chrome",
      headless: true,
      args: ["--host-resolver-rules=MAP clipboard.test 127.0.0.1", "--no-proxy-server"],
    });
    for (const secure of [false, true]) {
      // A unique value per origin prevents an old clipboard from passing the test.
      secret = "synthetic-key-copy-" + randomUUID() + "abcdef1234567890".repeat(5);
      const page = await browser.newPage();
      page.setDefaultTimeout(10000);
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      await page.goto(
        `http://${secure ? "127.0.0.1" : "clipboard.test"}:${server.address().port}/`
      );
      assert.equal(await page.evaluate(() => isSecureContext), secure);
      assert.equal(await page.evaluate(() => typeof navigator.clipboard !== "undefined"), secure);
      // Exercise the real asynchronous fallback on a trustworthy origin too.
      if (secure)
        await page.evaluate(() => {
          document.execCommand = () => false;
        });
      await page.getByRole("button", { name: "Create API key", exact: true }).click();
      await page.getByRole("textbox", { name: "Name", exact: true }).fill("Copy test");
      await page.getByRole("combobox", { name: "Workspaces", exact: true }).click();
      await page.getByRole("option", { name: /All .*workspaces/ }).click();
      await page.getByRole("button", { name: "Create", exact: true }).click();
      const field = page.getByTestId("issued-secret");
      await field.waitFor();
      assert.equal(await field.inputValue(), secret);
      const selection = await field.evaluate((e) => [e.selectionStart, e.selectionEnd]);
      assert.equal(selection[0], selection[1], "opening must not select the secret");
      await field.click();
      assert.deepEqual(await field.evaluate((e) => [e.selectionStart, e.selectionEnd]), [
        0,
        secret.length,
      ]);
      await page.getByRole("button", { name: "Copy API key", exact: true }).click();
      await page.getByText("Copied", { exact: true }).waitFor();
      assert.equal(await field.inputValue(), secret);
      assert.deepEqual(await field.evaluate((e) => [e.selectionStart, e.selectionEnd]), [
        0,
        secret.length,
      ]);
      assert.equal(await page.evaluate(() => document.activeElement.textContent), "Copy API key");
      await page.getByRole("button", { name: "I saved it — close", exact: true }).click();
      // Radix restores focus in a deferred unmount callback. Let it finish
      // before focusing the paste target, so it cannot steal the shortcut.
      await page.waitForFunction(() => document.activeElement?.textContent === "Create API key");
      const paste = page.locator("#paste-target");
      await paste.fill("old clipboard placeholder");
      await paste.selectText();
      await paste.press("ControlOrMeta+V");
      // Sending the shortcut does not await native clipboard read/insertion.
      // Wait for the actual pasted value; never retry copying or populate it here.
      await page.waitForFunction(
        (expected) => document.querySelector("#paste-target").value === expected,
        secret
      );
      assert.equal(await paste.inputValue(), secret, "actual OS clipboard paste must match");
      assert.deepEqual(errors, []);
      console.log(
        JSON.stringify({
          os: process.platform,
          browser: await browser.version(),
          secureContext: secure,
          manualSelectAll: true,
          restoredFocusAndSelection: true,
          actualPasteMatches: true,
          pageErrors: errors,
        })
      );
      await page.close();
    }
  } finally {
    if (browser) await browser.close();
    if (server?.listening) await new Promise((resolve) => server.close(resolve));
    fs.rmSync(output, { recursive: true, force: true });
  }
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
