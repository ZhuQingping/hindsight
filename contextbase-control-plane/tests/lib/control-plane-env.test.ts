import { afterEach, expect, it, vi } from "vitest";
import { controlPlaneEnv } from "@/lib/control-plane-env";

afterEach(() => vi.unstubAllEnvs());

it("uses public deployment settings ahead of internal defaults", () => {
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_URL", "http://internal.invalid");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_URL", "https://customer.example/api");
  expect(controlPlaneEnv("DATAPLANE_API_URL")).toBe("https://customer.example/api");
});

it("does not resurrect an internal credential when the public setting clears it", () => {
  vi.stubEnv("HINDSIGHT_CP_DATAPLANE_API_KEY", "internal-key");
  vi.stubEnv("CONTEXTBASE_CP_DATAPLANE_API_KEY", "");
  expect(controlPlaneEnv("DATAPLANE_API_KEY")).toBe("");
});

it("retains the internal deployment configuration when no public override exists", () => {
  vi.stubEnv("CONTEXTBASE_CP_AUTH_MODE", undefined);
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
  expect(controlPlaneEnv("AUTH_MODE")).toBe("local");
});
