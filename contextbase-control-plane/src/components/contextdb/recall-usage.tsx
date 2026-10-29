"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { useRecallUsageEnabled } from "./usage-capabilities";
import { contextDBRequest } from "@/lib/contextdb-api";
import { useProductName } from "@/components/product-runtime";

type ObjectType = "memory" | "knowledge_page";
interface UsageItem {
  object_id: string;
  recall_count: number;
  last_recalled_at: string | null;
}
interface UsageState {
  key: string;
  status: "loading" | "ready" | "error";
  items: Map<string, UsageItem>;
}
const UsageContext = createContext<UsageState | null>(null);

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

/** Missing objects stay missing; a bad/unavailable response must never become zero. */
function parseReport(value: unknown, bankId: string, type: ObjectType, ids: string[]) {
  if (
    !object(value) ||
    value.bank_id !== bankId ||
    value.object_type !== type ||
    !Array.isArray(value.items)
  )
    throw new Error("Invalid usage response");
  const items = new Map<string, UsageItem>();
  for (const item of value.items) {
    if (
      !object(item) ||
      typeof item.object_id !== "string" ||
      !ids.includes(item.object_id) ||
      items.has(item.object_id) ||
      typeof item.recall_count !== "number" ||
      !Number.isSafeInteger(item.recall_count) ||
      item.recall_count < 0 ||
      (item.last_recalled_at !== null &&
        (typeof item.last_recalled_at !== "string" ||
          !Number.isFinite(Date.parse(item.last_recalled_at)))) ||
      (item.recall_count === 0) !== (item.last_recalled_at === null)
    )
      throw new Error("Invalid usage item");
    items.set(item.object_id, {
      object_id: item.object_id,
      recall_count: item.recall_count,
      last_recalled_at: typeof item.last_recalled_at === "string" ? item.last_recalled_at : null,
    });
  }
  return items;
}

/** A visible page owns one bounded request. Content renders before this effect runs. */
export function ContextDBUsageProvider({
  bankId,
  objectType,
  ids,
  children,
}: {
  bankId: string;
  objectType: ObjectType;
  ids: string[];
  children: ReactNode;
}) {
  const enabled = useRecallUsageEnabled();
  const product = useProductName();
  const t = useTranslations("contextDB");
  const idKey = JSON.stringify([...new Set(ids)].sort());
  const key = JSON.stringify([product, bankId, objectType, idKey]);
  const [state, setState] = useState<UsageState | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!enabled || !bankId) return;
    const requested: string[] = JSON.parse(idKey);
    if (requested.length === 0) return;
    if (requested.length > 100) {
      setState({ key, status: "error", items: new Map() });
      return;
    }
    let active = true;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 10000);
    setState({ key, status: "loading", items: new Map() });
    const params = new URLSearchParams({ object_type: objectType });
    requested.forEach((id) => params.append("ids", id));
    void contextDBRequest<unknown>(`/workspaces/${encodeURIComponent(bankId)}/usage?${params}`, {
      signal: controller.signal,
    })
      .then((report) => {
        const items = parseReport(report, bankId, objectType, requested);
        if (active) setState({ key, status: "ready", items });
      })
      .catch(() => {
        if (active) setState({ key, status: "error", items: new Map() });
      })
      .finally(() => window.clearTimeout(timeout));
    return () => {
      active = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [enabled, bankId, objectType, idKey, key, revision]);
  // Mask the previous page/bank synchronously, before effect cleanup/next fetch.
  const current: UsageState =
    state?.key === key ? state : { key, status: "loading", items: new Map() };
  if (!enabled || !bankId || ids.length === 0) return children;
  return (
    <UsageContext.Provider value={current}>
      <div className="my-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span role={current.status === "error" ? "status" : undefined}>
          {current.status === "error" ? t("usageUnavailable") : t("usageHint")}
        </span>
        <button
          type="button"
          className="underline underline-offset-2"
          disabled={current.status === "loading"}
          onClick={() => setRevision((value) => value + 1)}
        >
          {t(current.status === "error" ? "usageRetry" : "usageRefresh")}
        </button>
      </div>
      {children}
    </UsageContext.Provider>
  );
}

export function ContextDBUsageFields({ objectId }: { objectId: string }) {
  const state = useContext(UsageContext);
  if (!state) return null;
  return <UsageValues state={state} objectId={objectId} />;
}

function UsageValues({ state, objectId }: { state: UsageState; objectId: string }) {
  const t = useTranslations("contextDB");
  const locale = useLocale();
  const item = state.items.get(objectId);
  const placeholder = state.status === "loading" ? t("usageLoading") : t("usageMissing");
  const time = item?.last_recalled_at;
  return (
    <div
      className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground"
      aria-busy={state.status === "loading"}
    >
      <span>
        {t("usageCount")}: {item ? item.recall_count.toLocaleString(locale) : placeholder}
      </span>
      <span>
        {t("usageLast")}:{" "}
        {item ? (
          time ? (
            <time dateTime={time} title={time}>
              {new Date(time).toLocaleString(locale)}
            </time>
          ) : (
            t("usageNever")
          )
        ) : (
          placeholder
        )}
      </span>
    </div>
  );
}

export function ContextDBRecallUsage({
  bankId,
  objectType,
  objectId,
}: {
  bankId: string;
  objectType: ObjectType;
  objectId: string;
}) {
  return (
    <ContextDBUsageProvider bankId={bankId} objectType={objectType} ids={[objectId]}>
      <ContextDBUsageFields objectId={objectId} />
    </ContextDBUsageProvider>
  );
}
