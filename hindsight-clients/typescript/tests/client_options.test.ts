import { DEFAULT_USER_AGENT, ContextBaseClient } from "../src";

describe("ContextBaseClient options", () => {
  test("flattens custom headers into the generated client configuration", () => {
    const client = new ContextBaseClient({
      baseUrl: "http://localhost:8888",
      apiKey: "test-api-key",
      headers: {
        "X-Request-Source": "test-suite",
      },
    });
    const internalClient = client as unknown as {
      client: { getConfig: () => { headers: Headers } };
    };

    const headers = internalClient.client.getConfig().headers;

    expect(headers.get("X-Request-Source")).toBe("test-suite");
    expect(headers.get("Authorization")).toBe("Bearer test-api-key");
    expect(headers.get("User-Agent")).toBe(DEFAULT_USER_AGENT);
  });

  test("puts a caller's user agent in front of the client's own", () => {
    const client = new ContextBaseClient({
      baseUrl: "http://localhost:8888",
      userAgent: "contextbase-test/1.2.3",
    });
    const internalClient = client as unknown as {
      client: { getConfig: () => { headers: Headers } };
    };

    expect(internalClient.client.getConfig().headers.get("User-Agent")).toBe(
      `contextbase-test/1.2.3 ${DEFAULT_USER_AGENT}`
    );
  });
});
