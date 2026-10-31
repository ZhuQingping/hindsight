"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { client, LLMRequestEntry } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { JsonViewer } from "@/components/ui/json-viewer";
import { Spinner } from "@/components/ui/spinner";

type TranslateFn = (key: string) => string;

function formatDurationMs(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

// Compact token count: 950 → "950", 1300 → "1.3k", 2_400_000 → "2.4M".
function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

// The API keeps total_tokens as input + visible output for compatibility.
// Add reported reasoning tokens when displaying a complete token total.
export function totalTokens(entry: LLMRequestEntry): number | null {
  if (entry.total_tokens == null) {
    return entry.thoughts_tokens && entry.thoughts_tokens > 0 ? entry.thoughts_tokens : null;
  }
  return entry.total_tokens + (entry.thoughts_tokens ?? 0);
}

// Pull a list of memory_unit ids out of trace metadata (memory_ids /
// source_memory_ids). Tolerates missing / non-array values.
function metadataIdList(
  metadata: Record<string, unknown> | null | undefined,
  key: string
): string[] {
  const raw = metadata?.[key];
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
}

// Trace-level mapping of the memory_units an operation produced/consumed,
// rendered as truncated mono chips with the full id on hover.
function MemoryIdList({ label, ids }: { label: string; ids: string[] }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="text-muted-foreground">{label}</span>
      {ids.map((id) => (
        <code key={id} title={id} className="font-mono text-xs text-foreground">
          {id.slice(0, 8)}
        </code>
      ))}
    </div>
  );
}

function formatDateTime(ts: string | null): string {
  if (!ts) return "—";
  const date = new Date(ts);
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    success: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
    error: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status] || styles.success}`}
    >
      {status}
    </span>
  );
}

// ---- Trace dialog (Langsmith-style: span waterfall + selected-span details) ----

// One span in the left-hand waterfall: name, status dot, duration/tokens, and a
// timeline bar positioned by its offset within the trace.
function SpanRow({
  span,
  traceStart,
  traceSpan,
  selected,
  onClick,
}: {
  span: LLMRequestEntry;
  traceStart: number;
  traceSpan: number;
  selected: boolean;
  onClick: () => void;
}) {
  const start = span.started_at ? new Date(span.started_at).getTime() : traceStart;
  const end = span.ended_at ? new Date(span.ended_at).getTime() : start;
  const left = Math.min(98, Math.max(0, ((start - traceStart) / traceSpan) * 100));
  const width = Math.max(2, Math.min(100 - left, ((end - start) / traceSpan) * 100));
  const isError = span.status === "error";
  const spanTokens = totalTokens(span);
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left rounded-md px-2 py-1.5 transition-colors ${
        selected ? "bg-muted" : "hover:bg-muted/50"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <span
            className={`w-1.5 h-1.5 rounded-full shrink-0 ${isError ? "bg-red-500" : "bg-green-500"}`}
          />
          <span className="text-xs font-mono truncate">
            {span.scope || span.operation || "call"}
          </span>
        </span>
        <span className="text-[10px] text-muted-foreground font-mono shrink-0">
          {formatDurationMs(span.duration_ms)}
          {spanTokens != null ? ` · ${formatTokens(spanTokens)}` : ""}
        </span>
      </div>
      <div className="relative h-1.5 mt-1 rounded bg-muted/40">
        <div
          className={`absolute top-0 h-full rounded ${isError ? "bg-red-500/70" : "bg-primary/70"}`}
          style={{ left: `${left}%`, width: `${width}%` }}
        />
      </div>
    </button>
  );
}

// Right-hand detail panel for the selected span.
function SpanDetails({ entry, t }: { entry: LLMRequestEntry; t: TranslateFn }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
        <div>
          <span className="text-muted-foreground">{t("detailScope")}</span>{" "}
          <span className="font-mono">{entry.scope || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailStatus")}</span>{" "}
          <StatusBadge status={entry.status} />
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailProvider")}</span>{" "}
          <span className="font-mono">{entry.provider || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailModel")}</span>{" "}
          <span className="font-mono">{entry.model || "—"}</span>
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailStarted")}</span>{" "}
          <span className="font-mono">{formatDateTime(entry.started_at)}</span>
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailDuration")}</span>{" "}
          <span className="font-mono">{formatDurationMs(entry.duration_ms)}</span>
        </div>
      </div>

      {(entry.total_tokens !== null ||
        entry.input_tokens !== null ||
        entry.output_tokens !== null ||
        entry.thoughts_tokens != null) && (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm border-t border-border pt-3">
          <div>
            <span className="text-muted-foreground">{t("tokensInput")}:</span>{" "}
            <span className="font-mono">{entry.input_tokens ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">{t("tokensOutput")}:</span>{" "}
            <span className="font-mono">{entry.output_tokens ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">{t("tokensThoughts")}:</span>{" "}
            <span className="font-mono">{entry.thoughts_tokens ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">{t("tokensCached")}:</span>{" "}
            <span className="font-mono">{entry.cached_tokens ?? "—"}</span>
          </div>
          <div>
            <span className="text-muted-foreground">{t("tokensTotal")}:</span>{" "}
            <span className="font-mono font-medium">{totalTokens(entry) ?? "—"}</span>
          </div>
        </div>
      )}

      <div className="border-t border-border pt-3 space-y-1 text-sm">
        <div>
          <span className="text-muted-foreground">{t("detailSpan")}</span>{" "}
          <code className="font-mono text-xs">{entry.span_id || "—"}</code>
        </div>
        <div>
          <span className="text-muted-foreground">{t("detailParentSpan")}</span>{" "}
          <code className="font-mono text-xs">{entry.parent_span_id || "—"}</code>
        </div>
      </div>

      {entry.error && (
        <div>
          <h4 className="text-sm font-semibold mb-2">{t("detailError")}</h4>
          <JsonViewer
            value={entry.error}
            className="bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-300 max-h-[240px] overflow-y-auto"
          />
        </div>
      )}
      {entry.input !== null && entry.input !== undefined && (
        <div>
          <h4 className="text-sm font-semibold mb-2">{t("detailInput")}</h4>
          <JsonViewer value={entry.input} className="bg-muted max-h-[320px] overflow-y-auto" />
        </div>
      )}
      {entry.output !== null && entry.output !== undefined && (
        <div>
          <h4 className="text-sm font-semibold mb-2">{t("detailOutput")}</h4>
          <JsonViewer value={entry.output} className="bg-muted max-h-[320px] overflow-y-auto" />
        </div>
      )}
      {entry.llm_info && Object.keys(entry.llm_info).length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">{t("detailLlmInfo")}</h4>
          <JsonViewer value={entry.llm_info} />
        </div>
      )}
      {entry.metadata && Object.keys(entry.metadata).length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">{t("detailMetadata")}</h4>
          <JsonViewer value={entry.metadata} />
        </div>
      )}
    </div>
  );
}

// Full trace view: fetches every call sharing the entry's trace_id and shows the
// operation run as parent (header) → child LLM calls (waterfall) → details.
export function TraceDialog({
  bankId,
  entry,
  open,
  onOpenChange,
}: {
  bankId: string;
  entry: LLMRequestEntry | null;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const t = useTranslations("llmRequestsView");
  const [spans, setSpans] = useState<LLMRequestEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open || !entry) return;
    let cancelled = false;
    const load = async () => {
      if (!entry.trace_id) {
        setSpans([entry]);
        setSelectedId(entry.id);
        return;
      }
      setLoading(true);
      try {
        const data = await client.listLLMRequests(bankId, {
          trace_id: entry.trace_id,
          limit: 500,
        });
        const rows = (data.items || [])
          .slice()
          .sort((a, b) => (a.started_at || "").localeCompare(b.started_at || ""));
        if (!cancelled) {
          setSpans(rows.length ? rows : [entry]);
          setSelectedId(entry.id);
        }
      } catch {
        if (!cancelled) {
          setSpans([entry]);
          setSelectedId(entry.id);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [open, entry, bankId]);

  const selected = spans.find((s) => s.id === selectedId) ?? entry;
  const startTimes = spans
    .map((s) => (s.started_at ? new Date(s.started_at).getTime() : NaN))
    .filter((n) => !isNaN(n));
  const endTimes = spans
    .map((s) => (s.ended_at ? new Date(s.ended_at).getTime() : NaN))
    .filter((n) => !isNaN(n));
  const traceStart = startTimes.length ? Math.min(...startTimes) : 0;
  const traceEnd = endTimes.length ? Math.max(...endTimes) : 0;
  const traceSpan = Math.max(1, traceEnd - traceStart);
  const inputTokens = spans.reduce((sum, r) => sum + (r.input_tokens ?? 0), 0);
  const outputTokens = spans.reduce((sum, r) => sum + (r.output_tokens ?? 0), 0);
  const thoughtsTokens = spans.reduce((sum, r) => sum + (r.thoughts_tokens ?? 0), 0);
  const anyError = spans.some((s) => s.status === "error");
  const op = entry?.operation ?? spans[0]?.operation ?? "—";
  // memory_ids / source_memory_ids are attached identically to every row of a
  // trace, so read them from whichever row carries them.
  const traceMeta =
    spans.find(
      (s) =>
        metadataIdList(s.metadata, "memory_ids").length ||
        metadataIdList(s.metadata, "source_memory_ids").length
    )?.metadata ?? entry?.metadata;
  const createdMemoryIds = metadataIdList(traceMeta, "memory_ids");
  const sourceMemoryIds = metadataIdList(traceMeta, "source_memory_ids");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl w-[92vw] h-[85vh] flex flex-col gap-3">
        <DialogHeader className="shrink-0">
          <DialogTitle className="flex items-center gap-2">
            <span className="font-mono">{op}</span>
            <StatusBadge status={anyError ? "error" : "success"} />
          </DialogTitle>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
            <span>{t("entryCount", { count: spans.length })}</span>
            <span>
              {t("tokensInput")}{" "}
              <span className="font-mono text-foreground">{formatTokens(inputTokens)}</span>
              {" · "}
              {t("tokensOutput")}{" "}
              <span className="font-mono text-foreground">{formatTokens(outputTokens)}</span>
              {spans.some((s) => s.thoughts_tokens != null) && (
                <>
                  {" · "}
                  {t("tokensThoughts")}{" "}
                  <span className="font-mono text-foreground">{formatTokens(thoughtsTokens)}</span>
                </>
              )}
            </span>
            <span>
              {t("detailDuration")}{" "}
              <span className="font-mono text-foreground">{formatDurationMs(traceSpan)}</span>
            </span>
            {entry?.trace_id && <code className="font-mono">{entry.trace_id.slice(0, 8)}</code>}
          </div>
        </DialogHeader>
        {(createdMemoryIds.length > 0 || sourceMemoryIds.length > 0) && (
          <div className="shrink-0 flex flex-col gap-1 border-t border-border pt-2 text-xs">
            {createdMemoryIds.length > 0 && (
              <MemoryIdList
                label={t("memoriesCreated", { count: createdMemoryIds.length })}
                ids={createdMemoryIds}
              />
            )}
            {sourceMemoryIds.length > 0 && (
              <MemoryIdList
                label={t("memoriesSource", { count: sourceMemoryIds.length })}
                ids={sourceMemoryIds}
              />
            )}
          </div>
        )}
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[minmax(240px,5fr)_7fr] gap-4">
          <div className="overflow-y-auto md:border-r border-border md:pr-3 space-y-0.5">
            {loading ? (
              <div className="py-4 flex flex-col items-center gap-2 text-sm text-muted-foreground">
                <Spinner size="md" />
                <span>{t("chartLoading")}</span>
              </div>
            ) : (
              spans.map((s) => (
                <SpanRow
                  key={s.id}
                  span={s}
                  traceStart={traceStart}
                  traceSpan={traceSpan}
                  selected={selected?.id === s.id}
                  onClick={() => setSelectedId(s.id)}
                />
              ))
            )}
          </div>
          <div className="overflow-y-auto pr-1">
            {selected && <SpanDetails entry={selected} t={t} />}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
