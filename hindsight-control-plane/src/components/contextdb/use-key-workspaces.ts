"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { contextDBRequest, type ContextDBWorkspace, type Page } from "@/lib/contextdb-api";

/** One editor owns its paged choices. Backend UUID/version checks decide saves. */
export function useContextDBKeyWorkspaces() {
  const [workspaces, setWorkspaces] = useState<ContextDBWorkspace[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const offset = useRef(0);
  const active = useRef<AbortController | null>(null);
  const load = useCallback(async (append = false) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setLoading(true);
    setError("");
    try {
      const start = append ? offset.current : 0;
      const page = await contextDBRequest<Page<ContextDBWorkspace>>(
        `/workspaces?limit=50&offset=${start}`,
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      setWorkspaces((previous) => [
        ...new Map(
          [...(append ? previous : []), ...page.items].map((workspace) => [
            workspace.workspace_id,
            workspace,
          ])
        ).values(),
      ]);
      offset.current = start + page.items.length;
      setTotal(page.total);
    } catch (err) {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void load();
    return () => active.current?.abort();
  }, [load]);
  return {
    workspaces,
    loading,
    error,
    hasMore: offset.current < total,
    loadMore: () => load(true),
  };
}
