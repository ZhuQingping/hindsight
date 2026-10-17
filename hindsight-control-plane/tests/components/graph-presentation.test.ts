import { describe, expect, it } from "vitest";
import { escapeGraphHtml } from "@/components/constellation";
import { convertHindsightGraphData, graphLinkCategory } from "@/components/graph-data";

describe("graph presentation boundaries", () => {
  it("does not invent a semantic type for an untyped edge", () => {
    const graph = convertHindsightGraphData({
      nodes: [{ data: { id: "a" } }, { data: { id: "b" } }],
      edges: [{ data: { source: "a", target: "b", lineStyle: "solid" } }],
    });
    expect(graph.links[0].type).toBeUndefined();
    expect(graphLinkCategory(graph.links[0].type)).toBe("unknown");
    expect(graphLinkCategory("caused_by")).toBe("causal");
  });

  it("renders untrusted memory text as text inside a graph tooltip or SVG", () => {
    const payload = "<img src=x onerror=\"alert(1)\"> & 'quoted'";
    const escaped = escapeGraphHtml(payload);
    expect(escaped).toBe("&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;quoted&#39;");
    expect(escaped).not.toContain("<img");
  });
});
