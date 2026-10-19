import { beforeEach, describe, expect, it, vi } from "vitest";
import { createContextBaseProvider } from "../src/index.js";
import type { HindsightClient } from "../src/index.js";
import { USER_ID, mockClient, runtime, userMessage } from "./helpers.js";

describe("createContextBaseProvider", () => {
  let client: HindsightClient;

  beforeEach(() => {
    client = mockClient();
  });

  it("exposes the elizaOS provider contract", () => {
    const provider = createContextBaseProvider(client, undefined);
    expect(provider.name).toBe("CONTEXTBASE_MEMORY");
    expect(provider.dynamic).toBe(false);
    expect(typeof provider.description).toBe("string");
  });

  it("renders the default heading above recalled memories", async () => {
    const provider = createContextBaseProvider(client, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text.startsWith("# Relevant long-term memories\n")).toBe(true);
    expect(result.text).toContain("- User prefers dark mode");
    expect(result.text).toContain("- User lives in Berlin");
  });

  it("honours a custom heading", async () => {
    const provider = createContextBaseProvider(client, undefined, { heading: "## Memory" });
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text.startsWith("## Memory\n")).toBe(true);
  });

  it("returns empty text (no heading) when there are no results", async () => {
    const empty = mockClient({ results: [] });
    const provider = createContextBaseProvider(empty, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text).toBe("");
    expect(result.values?.contextbaseMemoryCount).toBe(0);
  });

  it("filters out results whose text is empty or whitespace", async () => {
    const noisy = mockClient({
      results: [
        { id: "1", text: "keep me" },
        { id: "2", text: "   " },
        { id: "3", text: "" },
        { id: "4", text: "keep me too" },
      ],
    });
    const provider = createContextBaseProvider(noisy, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text).toBe("# Relevant long-term memories\n- keep me\n- keep me too");
    // The count reflects the raw recall size, not the rendered lines.
    expect(result.values?.contextbaseMemoryCount).toBe(4);
  });

  it("trims whitespace around each memory line", async () => {
    const padded = mockClient({ results: [{ id: "1", text: "  spaced out  " }] });
    const provider = createContextBaseProvider(padded, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text).toBe("# Relevant long-term memories\n- spaced out");
  });

  it("skips recall and returns empty text when the message has no content text", async () => {
    const provider = createContextBaseProvider(client, undefined);
    const result = await provider.get(runtime, userMessage(undefined), {} as never);
    expect(client.recall).not.toHaveBeenCalled();
    expect(result.text).toBe("");
  });

  it("resolves the bank via a resolver function", async () => {
    const provider = createContextBaseProvider(client, (m) => `room:${m.roomId}`);
    const message = userMessage("hi");
    await provider.get(runtime, message, {} as never);
    expect(client.recall).toHaveBeenCalledWith(`room:${message.roomId}`, "hi", expect.any(Object));
  });

  it("carries the full recall response through on data.contextbase", async () => {
    const provider = createContextBaseProvider(client, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.data?.contextbase).toEqual({
      results: [
        { id: "1", text: "User prefers dark mode" },
        { id: "2", text: "User lives in Berlin" },
      ],
    });
  });

  it("swallows recall errors and reports a zero count with the error message", async () => {
    (client.recall as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("upstream 503"));
    const provider = createContextBaseProvider(client, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.text).toBe("");
    expect(result.values?.contextbaseMemoryCount).toBe(0);
    expect(result.data?.contextbaseError).toBe("upstream 503");
  });

  it("stringifies non-Error recall failures", async () => {
    (client.recall as ReturnType<typeof vi.fn>).mockRejectedValueOnce("plain string failure");
    const provider = createContextBaseProvider(client, undefined);
    const result = await provider.get(runtime, userMessage("q"), {} as never);
    expect(result.data?.contextbaseError).toBe("plain string failure");
  });

  it("uses the message entityId as the default bank", async () => {
    const provider = createContextBaseProvider(client, undefined);
    await provider.get(runtime, userMessage("hi"), {} as never);
    expect(client.recall).toHaveBeenCalledWith(USER_ID, "hi", expect.any(Object));
  });
});
