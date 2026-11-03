import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { MoltbotPluginAPI, ServiceConfig } from "./types.js";
const dirs: string[] = [];
afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  for (const dir of dirs.splice(0)) await rm(dir, { recursive: true, force: true });
});
describe("remote service connection", () => {
  it("requires an endpoint and preserves its API prefix", async () => {
    const { validateApiUrl } = await import("./index.js");
    for (const value of [
      undefined,
      "",
      "file:///tmp/db",
      "https://user:secret@example.com",
      "https://api.example.com?token=key",
    ]) {
      expect(() => validateApiUrl(value)).toThrow();
    }
    expect(validateApiUrl(" https://api.example.com/customer/ ")).toBe(
      "https://api.example.com/customer"
    );
  });
  it("a stopped service cannot publish an in-flight initialization or issue another probe", async () => {
    vi.resetModules();
    const { default: register } = await import("./index.js");
    const dir = await mkdtemp(join(tmpdir(), "contextbase-start-stop-"));
    dirs.push(dir);
    let answer: ((response: Response) => void) | undefined;
    const fetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        })
    );
    vi.stubGlobal("fetch", fetch);
    const services: ServiceConfig[] = [];
    const api: MoltbotPluginAPI = {
      config: {
        plugins: {
          entries: {
            "contextbase-openclaw": {
              config: {
                contextbaseApiUrl: "https://api.example.com",
                bankId: "team",
                retainQueuePath: join(dir, "queue.db"),
                logLevel: "off",
              },
            },
          },
        },
      },
      logger: { info() {}, warn() {}, error() {} },
      on() {},
      registerService(service) {
        services.push(service);
      },
    };
    register(api);
    const start = services[0].start();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await services[0].stop();
    answer!(new Response('{"status":"ok"}', { status: 200 }));
    await start;
    expect(fetch).toHaveBeenCalledTimes(1);
    const bridge = (globalThis as unknown as { __contextbaseClient: { getClient(): unknown } })
      .__contextbaseClient;
    expect(bridge.getClient()).toBeNull();
  });
});
