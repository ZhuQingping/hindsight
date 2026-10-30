"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { routing } from "@/i18n/routing";
import { useContextDBMode } from "@/lib/contextdb-mode";
import { contextDBRequest } from "@/lib/contextdb-api";
import { useProductName } from "@/components/product-runtime";

const RecallUsageEnabled = createContext(false);

/** One capability read per product/app mount; old servers fail closed without hiding content. */
export function ContextDBUsageCapabilities({ children }: { children: ReactNode }) {
  const mode = useContextDBMode();
  const path = usePathname();
  const login = path === "/login" || routing.locales.some((locale) => path === `/${locale}/login`);
  const product = useProductName();
  const [state, setState] = useState<{ product: string; enabled: boolean } | null>(null);
  useEffect(() => {
    setState(null);
    if (!mode || login) return;
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 5000);
    void contextDBRequest<unknown>("/admin/identity", { signal: controller.signal })
      .then((value) => {
        const enabled =
          value !== null &&
          typeof value === "object" &&
          "capabilities" in value &&
          value.capabilities !== null &&
          typeof value.capabilities === "object" &&
          "recall_usage" in value.capabilities &&
          value.capabilities.recall_usage === true;
        if (active) setState({ product, enabled });
      })
      .catch(() => {
        if (active) setState({ product, enabled: false });
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [mode, product, login]);
  return (
    <RecallUsageEnabled.Provider
      value={mode && !login && state?.product === product && state.enabled}
    >
      {children}
    </RecallUsageEnabled.Provider>
  );
}

export function useRecallUsageEnabled() {
  return useContext(RecallUsageEnabled);
}
