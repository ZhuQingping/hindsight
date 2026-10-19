"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { client, type KnowledgeNode } from "@/lib/api";
import { bankRoute } from "@/lib/bank-url";
import { Constellation } from "./constellation";
import type { GraphData, GraphNode, GraphLink } from "./graph-data";
import { Button } from "@/components/ui/button";
import { Network, FileText, Layers, FilePlus, ArrowRight } from "lucide-react";
import { Spinner } from "@/components/ui/spinner";
import { formatRelativeTime, formatAbsoluteDateTime } from "@/lib/relative-time";
import { MemoryStoreCard, MemoriesActivityChart, type BankStats } from "./bank-stats-view";
import { TreeRow } from "./knowledge-base-view";
import { useFeatures } from "@/lib/features-context";

const FALLBACK_COLOR = "#0074d9";
// The dashboard constellation is a glanceable memory map, not the full graph
// explorer. Edge count grows super-linearly with nodes, so cap this preview;
// the Memories view offers a larger, filterable graph.
const GRAPH_NODE_CAP = 200;
// Cluster the memory constellation by fact type, matching the memories charts.
const TYPE_COLORS: Record<string, string> = {
  world: "#8b5cf6",
  experience: "#ec4899",
  observation: "#6366f1",
  entity: "#0ea5e9",
};

// Documents have no standard name field (metadata is free-form and varies by
// source), so recent-docs shows the document id.
type DocItem = { id?: string; created_at?: string | null };

function flattenPages(nodes: KnowledgeNode[], out: KnowledgeNode[] = []): KnowledgeNode[] {
  for (const n of nodes) {
    if (n.kind === "page") out.push(n);
    if (n.children?.length) flattenPages(n.children, out);
  }
  return out;
}

function flattenAll(nodes: KnowledgeNode[], out: KnowledgeNode[] = []): KnowledgeNode[] {
  for (const n of nodes) {
    out.push(n);
    if (n.children?.length) flattenAll(n.children, out);
  }
  return out;
}

export function HomeView({
  bankId,
  onNavigate,
}: {
  bankId: string;
  onNavigate: (tab: string) => void;
}) {
  const t = useTranslations("home");
  const tb = useTranslations("bank");
  const tk = useTranslations("knowledgeBase");
  const router = useRouter();
  const { features } = useFeatures();
  const observationsEnabled = features?.observations ?? false;
  const [stats, setStats] = useState<BankStats | null>(null);
  const [graph, setGraph] = useState<{
    nodes?: unknown[];
    edges?: unknown[];
    table_rows?: Array<{ id: string; fact_type?: string }>;
    total_units?: number;
  } | null>(null);
  const [graphLoading, setGraphLoading] = useState(true);
  const [roots, setRoots] = useState<KnowledgeNode[]>([]);
  const [pages, setPages] = useState<KnowledgeNode[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [loading, setLoading] = useState(true);

  const toggleFolder = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // The light panels (stats, pages, docs) gate the page — they're small and
    // fast, so the dashboard paints immediately.
    Promise.allSettled([
      client.getBankStats(bankId),
      client.getKnowledgeTree(bankId),
      client.listDocuments({ bank_id: bankId, limit: 6 }),
    ]).then(([s, k, d]) => {
      if (cancelled) return;
      if (s.status === "fulfilled") setStats(s.value as BankStats);
      if (k.status === "fulfilled") {
        const r = (k.value as { roots?: KnowledgeNode[] }).roots || [];
        setRoots(r);
        const flat = flattenPages(r);
        setPages(flat);
        // Expand all folders so the Home card shows the full structure at a glance.
        setExpanded(
          new Set(
            flattenAll(r)
              .filter((n) => n.kind === "folder")
              .map((n) => n.id)
          )
        );
      }
      if (d.status === "fulfilled") setDocs((d.value as { items?: DocItem[] }).items || []);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [bankId]);

  // The memory constellation is heavy (edges scale super-linearly with nodes),
  // so it loads on its own — never blocking the dashboard — with a modest node
  // cap. The full memory graph lives in the Memories view.
  useEffect(() => {
    let cancelled = false;
    setGraphLoading(true);
    client
      .getGraph({ bank_id: bankId, limit: GRAPH_NODE_CAP })
      .then((g) => {
        if (!cancelled)
          setGraph(
            g as {
              nodes?: unknown[];
              edges?: unknown[];
              table_rows?: Array<{ id: string; fact_type?: string }>;
              total_units?: number;
            }
          );
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setGraphLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bankId]);

  // The dataplane graph is cytoscape-style ({ data: {...} } per node/edge); map
  // it to the Constellation's flat GraphData, clustering by fact type.
  const constellationData = useMemo<GraphData>(() => {
    if (!graph) return { nodes: [], links: [] };
    const factTypeById = new Map((graph.table_rows || []).map((row) => [row.id, row.fact_type]));
    const nodes: GraphNode[] = (graph.nodes || []).map((raw) => {
      const n =
        (raw as { data?: Record<string, unknown> }).data ?? (raw as Record<string, unknown>);
      return {
        id: String(n.id),
        label: (n.label as string) ?? undefined,
        color: (n.color as string) ?? undefined,
        group: (n.type as string) ?? factTypeById.get(String(n.id)),
      };
    });
    const links: GraphLink[] = (graph.edges || []).map((raw) => {
      const e =
        (raw as { data?: Record<string, unknown> }).data ?? (raw as Record<string, unknown>);
      return {
        source: String(e.source),
        target: String(e.target),
        type: typeof e.linkType === "string" ? e.linkType : undefined,
        color: typeof e.color === "string" ? e.color : undefined,
        weight: typeof e.weight === "number" ? (e.weight as number) : undefined,
      };
    });
    return { nodes, links };
  }, [graph]);

  const nodeWeights = useMemo(() => {
    const w = new Map<string, number>();
    for (const l of constellationData.links) {
      const v = typeof l.weight === "number" && l.weight > 0 ? l.weight : 1;
      w.set(l.source, (w.get(l.source) || 0) + v);
      w.set(l.target, (w.get(l.target) || 0) + v);
    }
    return w;
  }, [constellationData]);
  const maxWeight = useMemo(() => Math.max(1, ...nodeWeights.values()), [nodeWeights]);
  const nodeSizeFn = useCallback(
    (node: GraphNode) => 4 + Math.sqrt((nodeWeights.get(node.id) || 0) / maxWeight) * 9,
    [nodeWeights, maxWeight]
  );
  const clusterKeyFn = useCallback((node: GraphNode) => node.group ?? null, []);
  const clusterColorFn = useCallback((key: string) => TYPE_COLORS[key] || FALLBACK_COLOR, []);
  const clusterLabelFn = useCallback(
    (key: string) =>
      key === "world"
        ? tb("worldFacts")
        : key === "experience"
          ? tb("experience")
          : key === "observation"
            ? tb("observations")
            : key,
    [tb]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-32">
        <Spinner size="lg" variant="jump" />
      </div>
    );
  }

  return (
    <div>
      <h1 className="text-3xl font-bold mb-2 text-foreground">{t("title")}</h1>
      <p className="text-muted-foreground mb-6">
        {t("subtitle")} <span className="font-mono text-foreground">{bankId}</span>
      </p>

      {stats && (
        <div className="mb-4 space-y-3">
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            {stats.pending_operations > 0 && (
              <span className="rounded-full border border-border px-3 py-1">
                {t("pendingOps", { count: stats.pending_operations })}
              </span>
            )}
            {stats.failed_operations > 0 && (
              <span className="rounded-full border border-destructive/30 px-3 py-1 text-destructive">
                {t("failedOps", { count: stats.failed_operations })}
              </span>
            )}
            {stats.pending_consolidation > 0 && (
              <span className="rounded-full border border-border px-3 py-1">
                {t("pendingConsolidation", { count: stats.pending_consolidation })}
              </span>
            )}
            {stats.pending_operations === 0 &&
              stats.failed_operations === 0 &&
              stats.pending_consolidation === 0 && <span>{t("allUpToDate")}</span>}
          </div>
          <MemoryStoreCard stats={stats} observationsEnabled={observationsEnabled} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4">
        {/* Recent work reads as a pair of compact cards, without fixed half-screen blanks. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="bg-card border border-border border-solid rounded-[16px] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
              <h2 className="text-sm font-semibold text-foreground">{t("pagesTitle")}</h2>
              {pages.length > 0 && (
                <button
                  onClick={() => onNavigate("knowledge")}
                  className="text-xs text-primary hover:underline flex items-center gap-1"
                >
                  {t("viewAll")} <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </div>
            {pages.length > 0 ? (
              // Same folder/page tree (TOC) as the Pages tab, read-only: shows the
              // structure + freshness badges; clicking a page opens the Knowledge tab.
              <ul className="max-h-56 overflow-y-auto py-2">
                {roots.map((node) => (
                  <TreeRow
                    key={node.id}
                    node={node}
                    depth={0}
                    readOnly
                    expanded={expanded}
                    selectedId={null}
                    onToggle={toggleFolder}
                    onOpenPage={(pageId) =>
                      router.push(
                        bankRoute(bankId, `?view=knowledge&knowledgeTab=pages&page=${pageId}`)
                      )
                    }
                    t={tk}
                  />
                ))}
              </ul>
            ) : (
              <div className="px-4 py-8 text-center">
                <Layers className="w-7 h-7 mx-auto mb-2 text-muted-foreground opacity-60" />
                <p className="text-sm text-muted-foreground mb-3">{t("pagesEmpty")}</p>
                <Button size="sm" onClick={() => onNavigate("knowledge")}>
                  <FilePlus className="w-4 h-4 mr-2" />
                  {t("pagesEmptyCta")}
                </Button>
              </div>
            )}
          </div>

          <div className="bg-card border border-border border-solid rounded-[16px] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
              <h2 className="text-sm font-semibold text-foreground">{t("recentDocsTitle")}</h2>
              {docs.length > 0 && (
                <button
                  onClick={() => onNavigate("documents")}
                  className="text-xs text-primary hover:underline flex items-center gap-1"
                >
                  {t("viewAll")} <ArrowRight className="w-3 h-3" />
                </button>
              )}
            </div>
            {docs.length > 0 ? (
              <ul className="max-h-56 overflow-y-auto p-2">
                {docs.map((d, i) => (
                  <li key={`${d.id}-${i}`}>
                    <button
                      onClick={() => onNavigate("documents")}
                      className="w-full flex items-center justify-between gap-2 px-2 py-1 rounded hover:bg-muted text-left"
                    >
                      <span className="inline-flex items-center gap-1.5 min-w-0">
                        <FileText className="w-3 h-3 text-muted-foreground flex-shrink-0" />
                        <span className="text-xs font-mono truncate" title={d.id}>
                          {d.id}
                        </span>
                      </span>
                      {d.created_at && (
                        <span
                          className="text-[11px] text-muted-foreground flex-shrink-0"
                          title={formatAbsoluteDateTime(d.created_at)}
                        >
                          {formatRelativeTime(d.created_at)}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                {t("recentDocsEmpty")}
              </div>
            )}
          </div>
        </div>
        {/* Memory graph remains available as a focused preview after work status. */}
        <div className="bg-card border border-border border-solid rounded-[16px] overflow-hidden flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
            <div className="flex items-center gap-2">
              <Network className="w-4 h-4 text-muted-foreground" />
              <h2 className="text-sm font-semibold text-foreground">{t("constellationTitle")}</h2>
            </div>
            <button
              onClick={() => onNavigate("data")}
              className="text-xs text-primary hover:underline flex items-center gap-1"
            >
              {t("viewAll")} <ArrowRight className="w-3 h-3" />
            </button>
          </div>
          <p className="px-4 pt-2 text-xs text-muted-foreground">
            {t("graphScope")}
            {typeof graph?.total_units === "number" &&
            graph.total_units > constellationData.nodes.length
              ? ` · ${t("graphSample", { shown: constellationData.nodes.length, total: graph.total_units })}`
              : null}
          </p>
          {constellationData.nodes.length > 0 ? (
            <Constellation
              data={constellationData}
              height={320}
              onNodeClick={() => onNavigate("data")}
              nodeSizeFn={nodeSizeFn}
              clusterKeyFn={clusterKeyFn}
              clusterColorFn={clusterColorFn}
              clusterLabelFn={clusterLabelFn}
            />
          ) : graphLoading ? (
            <div className="flex flex-1 items-center justify-center">
              <Spinner size="lg" variant="jump" />
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              {t("constellationEmpty")}
            </div>
          )}
        </div>
      </div>

      {/* Memories by ingested time — reuse the bank-profile activity chart. */}
      <div className="mt-4">
        <MemoriesActivityChart bankId={bankId} observationsEnabled={observationsEnabled} />
      </div>
    </div>
  );
}
