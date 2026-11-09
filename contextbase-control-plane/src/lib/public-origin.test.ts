import { afterEach, expect, it, vi } from "vitest";
import { derivedApiUrl, normalizedHttpOrigin, requestUiOrigin } from "./public-origin";

afterEach(() => vi.unstubAllEnvs());

it.each([
  ["http://EXAMPLE.test:80/", "http://example.test"],
  ["https://example.test:443", "https://example.test"],
  ["http://[::1]:9999", "http://[::1]:9999"],
])("normalizes an actual HTTP origin %s", (value, expected) => {
  expect(normalizedHttpOrigin(value)).toBe(expected);
});

it.each([
  undefined,
  "",
  " http://example.test",
  "http://example.test ",
  "http://evil\\path",
  "http://one,two",
  "http:evil.example",
  "https:/evil.example",
  "https:///evil.example",
  "https://user:secret@example.test",
  "https://example.test/path",
  "https://example.test/a/..",
  "https://example.test?",
  "https://example.test?q=1",
  "https://example.test#",
  "https://example.test/#fragment",
  "http://.",
  "http://..",
  "http://%2e",
  "file:///tmp/ui",
])("rejects an invalid origin %s before URL repair", (value) => {
  expect(normalizedHttpOrigin(value)).toBeUndefined();
});

it.each([undefined, "", "0", "65536", "-1", "1.2", " 8888", "8888 ", "abc", "000080"])(
  "refuses an invalid public port %s",
  (port) => {
    vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", port);
    vi.stubEnv("HINDSIGHT_CP_PUBLIC_API_PORT", undefined);
    expect(derivedApiUrl("http://public.test:9999")).toBeUndefined();
  }
);

it.each([
  ["http://public.test:9999", "80", "http://public.test"],
  ["https://public.test:9999", "443", "https://public.test"],
  ["http://[::1]:9999", "8888", "http://[::1]:8888"],
  ["http://public.test:9999", "65535", "http://public.test:65535"],
])("derives %s using published port %s", (origin, port, expected) => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", port);
  expect(derivedApiUrl(origin)).toBe(expected);
});

it("preserves explicit empty port alias precedence", () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_API_PORT", "");
  vi.stubEnv("HINDSIGHT_CP_PUBLIC_API_PORT", "8888");
  expect(derivedApiUrl("http://public.test")).toBeUndefined();
});

it("trusts gateway data only behind the gateway and never falls back to loopback", () => {
  vi.stubEnv("CONTEXTBASE_CP_PUBLIC_ORIGIN", "http://127.0.0.1:9999");
  const headers = new Headers({ "X-ContextDB-External-Origin": "http://192.0.2.10:9999" });
  for (const marker of [undefined, "0", "true", ""]) {
    vi.stubEnv("CONTEXTBASE_CP_TRUST_EXTERNAL_ORIGIN", marker);
    vi.stubEnv("HINDSIGHT_CP_TRUST_EXTERNAL_ORIGIN", undefined);
    expect(requestUiOrigin(headers)).toBe("http://127.0.0.1:9999");
  }
  vi.stubEnv("CONTEXTBASE_CP_TRUST_EXTERNAL_ORIGIN", "1");
  expect(requestUiOrigin(headers)).toBe("http://192.0.2.10:9999");
  expect(requestUiOrigin(new Headers())).toBeUndefined();
  expect(
    requestUiOrigin(new Headers({ "X-ContextDB-External-Origin": "invalid" }))
  ).toBeUndefined();
});
