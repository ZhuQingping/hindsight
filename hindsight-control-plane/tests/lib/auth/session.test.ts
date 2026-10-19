import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { NextRequest } from "next/server";
import {
  createSessionToken,
  verifySessionToken,
  revokeSessionToken,
  SESSION_MAX_AGE_SECONDS,
  isSecureRequest,
  trustedMutation,
  authConfigured,
  sessionCookieName,
} from "@/lib/auth/session";

let directory: string;
const key = "local-login-secret";
beforeEach(async () => {
  directory = await mkdtemp(path.join(os.tmpdir(), "m2-session-"));
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", directory);
  vi.stubEnv("HINDSIGHT_CP_ACCESS_KEY", key);
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "local");
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "https://memory.example.test");
});
afterEach(async () => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
  await rm(directory, { recursive: true, force: true });
});

describe("durable local sessions", () => {
  it("issues unique sessions and revokes only the session logged out", async () => {
    const first = await createSessionToken(key);
    const second = await createSessionToken(key);
    expect(first).not.toBe(second);
    expect(await verifySessionToken(first, key)).toBe(true);
    await revokeSessionToken(first);
    expect(await verifySessionToken(first, key)).toBe(false);
    expect(await verifySessionToken(second, key)).toBe(true);
    await revokeSessionToken(first);
  });
  it("survives module reload and retains revocation across reload", async () => {
    const token = await createSessionToken(key);
    vi.resetModules();
    const otherWorker = await import("@/lib/auth/session");
    expect(await otherWorker.verifySessionToken(token, key)).toBe(true);
    await otherWorker.revokeSessionToken(token);
    expect(await verifySessionToken(token, key)).toBe(false);
  });
  it("rejects wrong keys, tampering, legacy tokens, and missing storage", async () => {
    const token = await createSessionToken(key);
    expect(await verifySessionToken(token, "rotated-key")).toBe(false);
    expect(
      await verifySessionToken(token.slice(0, -1) + (token.endsWith("a") ? "b" : "a"), key)
    ).toBe(false);
    for (const malformed of [undefined, "authenticated", "123.sig", "../secret", ""])
      expect(await verifySessionToken(malformed, key)).toBe(false);
    await rm(directory, { recursive: true });
    expect(await verifySessionToken(token, key)).toBe(false);
  });
  it("expires at the deadline and rejects future sessions", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
    const token = await createSessionToken(key);
    vi.setSystemTime(new Date("2025-12-31T23:00:00Z"));
    expect(await verifySessionToken(token, key)).toBe(false);
    vi.setSystemTime(new Date(Date.parse("2026-01-01T00:00:00Z") + SESSION_MAX_AGE_SECONDS * 1000));
    expect(await verifySessionToken(token, key)).toBe(false);
  });
});

it("uses configured public origin for cookie security, ignoring forwarded proto", () => {
  const request = new NextRequest("http://internal/", { headers: { "x-forwarded-proto": "http" } });
  expect(isSecureRequest(request)).toBe(true);
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "http://127.0.0.1:28901");
  expect(
    isSecureRequest(
      new NextRequest("https://forged/", { headers: { "x-forwarded-proto": "https" } })
    )
  ).toBe(false);
});
it("requires exact origin and host for browser mutations", () => {
  const req = (origin: string, host = "memory.example.test") =>
    new NextRequest("http://internal/api/banks", { headers: { origin, host } });
  expect(trustedMutation(req("https://memory.example.test"))).toBe(true);
  expect(trustedMutation(req("https://evil.example.test"))).toBe(false);
  expect(trustedMutation(req("https://memory.example.test", "evil.example.test"))).toBe(false);
});
it("fails closed for incomplete or unknown protected configuration", () => {
  expect(authConfigured()).toBe(true);
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", "relative");
  expect(authConfigured()).toBe(false);
  vi.stubEnv("HINDSIGHT_CP_SESSION_DIR", directory);
  vi.stubEnv("HINDSIGHT_CP_AUTH_MODE", "typo");
  expect(authConfigured()).toBe(false);
});

it("binds sessions and cookie names to the configured instance origin", async () => {
  const originalName = sessionCookieName();
  const token = await createSessionToken(key);
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_ORIGIN", "https://another.example.test");
  expect(sessionCookieName()).not.toBe(originalName);
  expect(await verifySessionToken(token, key)).toBe(false);
});
