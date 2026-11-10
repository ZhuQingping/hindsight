// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CompactMarkdown } from "@/components/compact-markdown";

function render(markdown: string) {
  const container = document.createElement("div");
  container.innerHTML = renderToStaticMarkup(<CompactMarkdown>{markdown}</CompactMarkdown>);
  return container;
}

describe("CompactMarkdown CJK emphasis", () => {
  it.each([
    ["**结论。**下一句", "结论。", "结论。下一句"],
    [
      "**结论：测试完成。**下一步核对结果。",
      "结论：测试完成。",
      "结论：测试完成。下一步核对结果。",
    ],
    ["**结论。** 下一句", "结论。", "结论。 下一句"],
    ["**结论**。下一句", "结论", "结论。下一句"],
    ["**结论。**\n\n下一句", "结论。", "结论。\n下一句"],
    ["**结论。**", "结论。", "结论。"],
    ["**結論。**次の文", "結論。", "結論。次の文"],
    ["**결론.**다음 문장", "결론.", "결론.다음 문장"],
  ])("renders emphasis in %s", (markdown, emphasized, text) => {
    const container = render(markdown);
    expect(container.querySelectorAll("strong")).toHaveLength(1);
    expect(container.querySelector("strong")?.textContent).toBe(emphasized);
    expect(container.textContent).toBe(text);
  });

  it.each([
    "\\*\\*结论。\\*\\*下一句",
    "`**结论。**下一句`",
    "```text\n**结论。**下一句\n```",
    "    **结论。**下一句",
  ])("preserves literal markers in %s", (markdown) => {
    const container = render(markdown);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent?.trim()).toBe("**结论。**下一句");
  });

  it("preserves the English delimiter rule", () => {
    const container = render("**Conclusion.**Next sentence");
    expect(container.querySelector("strong")).toBeNull();
    expect(container.textContent).toBe("**Conclusion.**Next sentence");
  });

  it("keeps table normalization and renders CJK emphasis inside cells", () => {
    const container = render(
      "前文\n  | 项目 | 状态 |\n  | --- | --- |\n  | 示例 | **结论。**下一句 |\n后文"
    );
    expect(container.querySelectorAll("table")).toHaveLength(1);
    expect(container.querySelector("tbody td:last-child strong")?.textContent).toBe("结论。");
    expect(container.querySelector("tbody td:last-child")?.textContent).toBe("结论。下一句");
    expect(container.querySelectorAll("p")).toHaveLength(2);
  });

  it("preserves GFM tasks, links, and ordinary strikethrough", () => {
    const container = render("- [x] [完成](https://example.com) ~~删除~~");
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
    expect(container.querySelector("a")?.getAttribute("href")).toBe("https://example.com");
    expect(container.querySelector("del")?.textContent).toBe("删除");
  });

  it("does not extend CJK strikethrough delimiter rules", () => {
    const container = render("~~删除。~~下一句");
    expect(container.querySelector("del")).toBeNull();
    expect(container.textContent).toBe("~~删除。~~下一句");
  });

  it("preserves nested emphasis", () => {
    const container = render("**重点和 *斜体***。后续");
    expect(container.querySelector("strong")?.textContent).toBe("重点和 斜体");
    expect(container.querySelector("strong em")?.textContent).toBe("斜体");
    expect(container.textContent).toBe("重点和 斜体。后续");
  });
});
