"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { withBasePath } from "@/lib/base-path";
import { parseProductConfig, productDisplayName } from "@/lib/product-config";

import { DISPLAY_NAME } from "@/lib/brand-defaults";

const ProductNameContext = createContext(DISPLAY_NAME);
export function useProductName() {
  return useContext(ProductNameContext);
}

export function ProductRuntime({
  name,
  locale,
  children,
}: {
  name: string;
  locale: string;
  children: React.ReactNode;
}) {
  const [problem, setProblem] = useState<"changed" | "unavailable" | null>(null);
  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const response = await fetch(withBasePath("/api/product-config"), {
          cache: "no-store",
          signal: AbortSignal.timeout(5000),
        });
        const value = await response.json();
        if (!active) return;
        if (!response.ok) {
          setProblem("unavailable");
          return;
        }
        setProblem(productDisplayName(parseProductConfig(value)) === name ? null : "changed");
      } catch {
        if (active) setProblem("unavailable");
      }
    };
    void check();
    const timer = window.setInterval(check, 30000);
    window.addEventListener("focus", check);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener("focus", check);
    };
  }, [name]);
  const zh = locale === "zh-CN";
  return (
    <ProductNameContext.Provider value={name}>
      {locale !== "en" && !zh && (
        <p role="status" className="border-b bg-muted px-4 py-2 text-sm">
          This product currently provides complete main flows in English and Simplified Chinese.
          English is shown for this language.
        </p>
      )}
      {problem && (
        <div role="alert" className="sticky top-0 z-50 border-b bg-amber-100 p-3 text-amber-950">
          {problem === "changed"
            ? zh
              ? "产品名称已更新。请先保留当前输入，再手动刷新。提交结果不明确时，请先核对结果，避免重复提交。"
              : "The product name changed. Preserve your input, then refresh manually. If a submission outcome is unclear, check its result before submitting again."
            : zh
              ? "产品配置不一致或服务不可用。请联系运维修复配置。当前输入保留，不会自动重发。"
              : "Product configuration differs or a service is unavailable. Ask operations to repair the configuration. Your input is retained; nothing is automatically resubmitted."}
        </div>
      )}
      {children}
    </ProductNameContext.Provider>
  );
}
