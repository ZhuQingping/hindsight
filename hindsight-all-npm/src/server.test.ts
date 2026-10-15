import { describe, it, expect, vi } from "vitest";
import { EventEmitter } from "node:events";
import { AgentstratumServer } from "./server.js";

const spawnMock = vi.hoisted(() => vi.fn());
vi.mock("child_process", () => ({ spawn: spawnMock }));

describe("AgentstratumServer construction", () => {
  it("defaults base URL to http://127.0.0.1:8888", () => {
    const server = new AgentstratumServer();
    expect(server.getBaseUrl()).toBe("http://127.0.0.1:8888");
    expect(server.getProfile()).toBe("default");
  });

  it("honours custom profile, port, and host", () => {
    const server = new AgentstratumServer({ profile: "app", port: 9077, host: "0.0.0.0" });
    expect(server.getProfile()).toBe("app");
    expect(server.getBaseUrl()).toBe("http://0.0.0.0:9077");
  });

  it("accepts open env pass-through without complaining about unknown keys", () => {
    const server = new AgentstratumServer({
      env: {
        AGENTSTRATUM_API_LLM_PROVIDER: "openai",
        AGENTSTRATUM_API_LLM_MODEL: "gpt-4o-mini",
        // A field that does not exist today — should still be accepted
        AGENTSTRATUM_FUTURE_FLAG: "enabled",
      },
    });
    expect(server).toBeInstanceOf(AgentstratumServer);
  });

  it("exposes checkHealth that returns false when no daemon is running", async () => {
    // Random high port that nothing is listening on.
    const server = new AgentstratumServer({ port: 1, readyTimeoutMs: 100 });
    const healthy = await server.checkHealth();
    expect(healthy).toBe(false);
  });

  it("hides daemon command windows on Windows", async () => {
    const child = {
      stdout: { on: vi.fn() },
      stderr: { on: vi.fn() },
      on: vi.fn((event: string, handler: (code?: number) => void) => {
        if (event === "exit") handler(0);
        return child;
      }),
    };
    spawnMock.mockReturnValueOnce(child);

    const server = new AgentstratumServer({ embedPackage: "agentstratum-embed==0.5.0" });
    await server.stop();

    expect(spawnMock).toHaveBeenCalledWith(
      "uvx",
      [
        "--quiet",
        "--from",
        "agentstratum-embed==0.5.0",
        "agentstratum-embed",
        "daemon",
        "--profile",
        "default",
        "stop",
      ],
      expect.objectContaining({ stdio: "pipe", windowsHide: true })
    );
  });

  it("uses the same caller-supplied environment for startup and shutdown", async () => {
    const child = {
      stdout: { on: vi.fn() },
      stderr: { on: vi.fn() },
      on: vi.fn((event: string, handler: (code?: number) => void) => {
        if (event === "exit") handler(0);
        return child;
      }),
    };
    spawnMock.mockReset();
    spawnMock.mockReturnValue(child);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("ready")));
    try {
      const server = new AgentstratumServer({
        env: {
          PATH: "/caller-toolchain/bin",
          AGENTSTRATUM_EMBED_PACKAGE: "agentstratum-embed==0.5.0",
          AGENTSTRATUM_TEST_SENTINEL: "same-environment",
          AGENTSTRATUM_OMITTED: undefined,
        },
        platformCpuWorkaround: false,
      });
      await server.start();
      await server.stop();
      expect(spawnMock).toHaveBeenCalledTimes(3);
      for (const call of spawnMock.mock.calls) {
        expect(call[2].env).toEqual(
          expect.objectContaining({
            PATH: "/caller-toolchain/bin",
            AGENTSTRATUM_TEST_SENTINEL: "same-environment",
          })
        );
        expect(call[2].env.AGENTSTRATUM_OMITTED).toBeUndefined();
      }
    } finally {
      vi.unstubAllGlobals();
      spawnMock.mockReset();
    }
  });
});

it("preserves daemon diagnostics and customer output", async () => {
  const logger = { info: vi.fn(), warn: vi.fn(), debug: vi.fn() };
  const child = Object.assign(new EventEmitter(), {
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
  });
  spawnMock.mockReturnValueOnce(child);
  const server = new AgentstratumServer({ embedPackage: "agentstratum-embed==0.5.0", logger });
  const started = server.start();
  child.stdout.emit("data", Buffer.from("Created profile customer-hindsight-project\n"));
  child.stderr.emit(
    "data",
    Buffer.from("hindsight_embed failed to load HINDSIGHT_API_LLM_MODEL\n")
  );
  child.emit("exit", 1);
  await expect(started).rejects.toThrow("hindsight_embed failed to load HINDSIGHT_API_LLM_MODEL");
  expect(logger.warn.mock.calls.flat().join(" ")).toContain(
    "hindsight_embed failed to load HINDSIGHT_API_LLM_MODEL"
  );
  expect(logger.info.mock.calls.flat().join(" ")).toContain("customer-hindsight-project");
});
