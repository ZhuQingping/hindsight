import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { ContextBaseClient } from "contextbase-client";
import { readFileSync } from "fs";
import type { PluginConfig } from "./types.js";
import {
  applyConfiguredBankDefaults,
  buildBankConfigApiUpdates,
  buildBankDefaults,
  hasConfiguredBankDefaults,
  normalizeDispositionTrait,
  normalizeEntityLabels,
  normalizeRetainExtractionMode,
  patchBankConfig,
} from "./bank-defaults.js";

const clientOpts = { baseUrl: "http://localhost:8888", apiKey: "test-token" };

describe("manifest schema defaults", () => {
  // OpenClaw validates plugin config with AJV applyDefaults, so every schema
  // `default` reaches the plugin as if the user had set it. A default on a
  // bank-stamped field would overwrite settings managed out-of-band on every
  // reload — the bankMission default did exactly that to reflect_mission (#5477).
  it("stamp nothing onto the bank when the user configured nothing", () => {
    const manifest = JSON.parse(
      readFileSync(new URL("../openclaw.plugin.json", import.meta.url), "utf-8")
    );
    const defaults = Object.fromEntries(
      Object.entries(manifest.configSchema.properties as Record<string, { default?: unknown }>)
        .filter(([, prop]) => "default" in prop)
        .map(([key, prop]) => [key, prop.default])
    );
    expect(buildBankDefaults(defaults as PluginConfig)).toEqual({});
    expect(buildBankConfigApiUpdates(defaults as PluginConfig)).toEqual({});
  });
});

describe("hasConfiguredBankDefaults", () => {
  it("returns false when no bank default options are set", () => {
    expect(hasConfiguredBankDefaults({})).toBe(false);
    expect(hasConfiguredBankDefaults({ autoRecall: true })).toBe(false);
  });

  it("returns true when any bank default or mission is configured", () => {
    expect(hasConfiguredBankDefaults({ retainMission: "Extract facts." })).toBe(true);
    expect(hasConfiguredBankDefaults({ retainExtractionMode: "verbose" })).toBe(true);
    expect(hasConfiguredBankDefaults({ enableAutoConsolidation: false })).toBe(true);
    expect(
      hasConfiguredBankDefaults({
        entityLabels: [{ name: "person", description: "A human" }],
      })
    ).toBe(true);
  });
});

describe("buildBankDefaults", () => {
  it("includes only explicitly set fields", () => {
    const config: PluginConfig = {
      retainExtractionMode: "verbose",
      enableObservations: true,
      dispositionSkepticism: 4,
      dispositionLiteralism: 2,
      dispositionEmpathy: 5,
    };
    expect(buildBankDefaults(config)).toEqual({
      retainExtractionMode: "verbose",
      enableObservations: true,
      dispositionSkepticism: 4,
      dispositionLiteralism: 2,
      dispositionEmpathy: 5,
    });
  });

  it("still includes missions when configured", () => {
    const config: PluginConfig = {
      bankMission: "Reflect mission.",
      retainMission: "Retain mission.",
      observationsMission: "Observations mission.",
      retainExtractionMode: "verbose",
    };
    expect(buildBankDefaults(config)).toEqual({
      reflectMission: "Reflect mission.",
      retainMission: "Retain mission.",
      observationsMission: "Observations mission.",
      retainExtractionMode: "verbose",
    });
  });
});

describe("buildBankConfigApiUpdates", () => {
  it("includes entityLabels and enableAutoConsolidation when set", () => {
    const labels = [
      { name: "person", description: "Human user" },
      { name: "project", description: "Software project" },
    ];
    const config: PluginConfig = {
      entityLabels: labels,
      enableAutoConsolidation: true,
    };
    expect(buildBankConfigApiUpdates(config)).toEqual({
      entity_labels: labels,
      enable_auto_consolidation: true,
    });
  });

  it("omits unset config-api fields", () => {
    expect(buildBankConfigApiUpdates({ retainExtractionMode: "verbose" })).toEqual({});
  });
});

describe("normalizers", () => {
  it("validates retain extraction mode", () => {
    expect(normalizeRetainExtractionMode("verbose")).toBe("verbose");
    expect(normalizeRetainExtractionMode("INVALID")).toBeUndefined();
  });

  it("validates disposition traits", () => {
    expect(normalizeDispositionTrait(3)).toBe(3);
    expect(normalizeDispositionTrait(0)).toBeUndefined();
    expect(normalizeDispositionTrait(6)).toBeUndefined();
    expect(normalizeDispositionTrait(2.5)).toBeUndefined();
  });

  it("passes through the server's entity label shapes", () => {
    const list = [{ name: "person", description: "Human" }];
    expect(normalizeEntityLabels(list)).toEqual(list);
    const wrapped = { attributes: list };
    expect(normalizeEntityLabels(wrapped)).toEqual(wrapped);
  });

  it("drops empty or malformed entity label shapes", () => {
    expect(normalizeEntityLabels([])).toBeUndefined();
    expect(normalizeEntityLabels({ attributes: [] })).toBeUndefined();
    // A plain keyed object is not the server's wrapper shape — it would be
    // silently ignored server-side, so it's dropped rather than sent.
    expect(normalizeEntityLabels({ person: { description: "Human" } })).toBeUndefined();
  });
});

describe("applyConfiguredBankDefaults", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("is a no-op when no defaults are configured", async () => {
    const updateBankConfig = vi.fn();
    const client = {
      updateBankConfig,
      getBankConfig: vi.fn().mockResolvedValue({}),
    } as unknown as ContextBaseClient;

    await applyConfiguredBankDefaults(client, "agent-slack-U123", {}, clientOpts);

    expect(updateBankConfig).not.toHaveBeenCalled();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("sends updateBankConfig and config patch for an existing configured bank", async () => {
    const updateBankConfig = vi.fn().mockResolvedValue({});
    const client = {
      updateBankConfig,
      getBankConfig: vi.fn().mockResolvedValue({}),
    } as unknown as ContextBaseClient;
    vi.mocked(global.fetch).mockResolvedValue(new Response("{}", { status: 200 }));

    const config: PluginConfig = {
      retainExtractionMode: "verbose",
      enableObservations: true,
      enableAutoConsolidation: true,
      entityLabels: ["person", "org"],
      retainMission: "Keep architectural decisions.",
    };

    await applyConfiguredBankDefaults(client, "agent-slack-U123", config, clientOpts);

    expect(updateBankConfig).toHaveBeenCalledWith("agent-slack-U123", {
      retainMission: "Keep architectural decisions.",
      retainExtractionMode: "verbose",
      enableObservations: true,
    });
    expect(global.fetch).toHaveBeenCalledWith(
      "http://localhost:8888/v1/default/banks/agent-slack-U123/config",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({
          updates: {
            entity_labels: ["person", "org"],
            enable_auto_consolidation: true,
          },
        }),
      })
    );
  });

  it("applies missions via updateBankConfig without config patch when only missions are set", async () => {
    const updateBankConfig = vi.fn().mockResolvedValue({});
    const client = {
      updateBankConfig,
      getBankConfig: vi.fn().mockResolvedValue({}),
    } as unknown as ContextBaseClient;

    await applyConfiguredBankDefaults(
      client,
      "openclaw",
      { bankMission: "Reflect.", retainMission: "Retain." },
      clientOpts
    );

    expect(updateBankConfig).toHaveBeenCalledWith("openclaw", {
      reflectMission: "Reflect.",
      retainMission: "Retain.",
    });
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

it.each([200, 404])(
  "checks Bank existence through the supported config API (%s)",
  async (status) => {
    const requests: string[] = [];
    const fetch = vi.spyOn(global, "fetch").mockImplementation(async (input, init) => {
      const request = new Request(input, init);
      const path = new URL(request.url).pathname;
      requests.push(`${request.method} ${path}`);
      expect(request.headers.get("Authorization")).toBe("Bearer test-token");
      // The service's retired /profile route returns 410, even for existing Banks.
      if (path.endsWith("/profile")) return Response.json({ detail: "Retired" }, { status: 410 });
      if (path !== "/customer/v1/default/banks/team/config")
        throw new Error(`Unexpected request: ${path}`);
      if (status === 404) return Response.json({ detail: "Bank not found" }, { status });
      return Response.json({ bank_id: "team", config: {}, overrides: {} });
    });
    try {
      const options = { ...clientOpts, baseUrl: "http://localhost:8888/customer" };
      const result = applyConfiguredBankDefaults(
        new ContextBaseClient(options),
        "team",
        { bankMission: "Reflect." },
        options
      );
      if (status === 404) await expect(result).rejects.toThrow("Bank not found");
      else await result;
      expect(requests).toEqual(
        status === 404
          ? ["GET /customer/v1/default/banks/team/config"]
          : [
              "GET /customer/v1/default/banks/team/config",
              "PATCH /customer/v1/default/banks/team/config",
            ]
      );
    } finally {
      fetch.mockRestore();
    }
  }
);

describe("patchBankConfig", () => {
  const originalFetch = global.fetch;

  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("throws on non-OK responses", async () => {
    vi.mocked(global.fetch).mockResolvedValue(new Response("nope", { status: 422 }));
    await expect(patchBankConfig("bank-a", { entity_labels: ["x"] }, clientOpts)).rejects.toThrow(
      /patchBankConfig failed \(422\)/
    );
  });
});
