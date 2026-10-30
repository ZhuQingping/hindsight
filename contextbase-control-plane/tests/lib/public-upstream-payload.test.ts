import { describe, expect, it } from "vitest";
import { publicUpstreamPayload } from "@/lib/public-upstream-payload";

describe("public upstream payloads", () => {
  it.each([500, 502, 503, 504])("hides server diagnostics for %i", (status) => {
    const data = {
      detail: "Hindsight failed at /app/hindsight-api/internal.py",
      stack: "internal trace",
      api_key: "synthetic-private-key",
    };
    expect(publicUpstreamPayload(data, status)).toEqual({ detail: "Failed" });
    expect(data.detail).toContain("Hindsight");
  });

  it.each([200, 201, 400, 401, 403, 409, 422, 429])(
    "preserves customer data and actionable client errors for %i",
    (status) => {
      const data = { detail: [{ msg: "Invalid Hindsight-review", input: "hindsight" }] };
      expect(publicUpstreamPayload(data, status)).toBe(data);
    }
  );
});
