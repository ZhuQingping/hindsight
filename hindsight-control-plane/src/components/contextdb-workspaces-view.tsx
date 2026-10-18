"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useBank } from "@/lib/bank-context";
import { bankRoute } from "@/lib/bank-url";
import {
  contextDBRequest,
  managementRequestId,
  workspaceIntents,
  workspaceMutation,
  waitForWorkspaceOperation,
  removeWorkspaceIntent,
  replayWorkspaceIntent,
  canReplayWorkspaceIntent,
  type ContextDBWorkspace,
  type WorkspaceIntent,
  type Page,
} from "@/lib/contextdb-api";

export function ContextDBWorkspacesView() {
  const t = useTranslations("contextDB");
  const router = useRouter();
  const { setCurrentBank, loadBanks } = useBank();
  const [page, setPage] = useState<Page<ContextDBWorkspace>>({
    items: [],
    total: 0,
    limit: 20,
    offset: 0,
  });
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [intents, setIntents] = useState<WorkspaceIntent[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [deleting, setDeleting] = useState<ContextDBWorkspace | null>(null);
  const controller = useRef<AbortController | null>(null);
  const pollDeadline = useRef(0);
  const pollAttempt = useRef(0);
  const [pollExpired, setPollExpired] = useState(false);
  const sync = useCallback(() => {
    pollDeadline.current = 0;
    pollAttempt.current = 0;
    setPollExpired(false);
    setIntents(workspaceIntents());
    setRefresh((value) => value + 1);
  }, []);
  useEffect(() => {
    setIntents(workspaceIntents());
    return () => controller.current?.abort();
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    contextDBRequest<Page<ContextDBWorkspace>>(
      `/workspaces?limit=20&offset=${offset}&q=${encodeURIComponent(query)}`,
      { signal: abort.signal }
    )
      .then((result) => {
        if (abort.signal.aborted) return;
        if (offset > 0 && offset >= result.total) {
          setOffset(Math.max(0, Math.ceil(result.total / 20) * 20 - 20));
          return;
        }
        setPage(result);
        if (
          pollDeadline.current &&
          !result.items.some((workspace) => ["creating", "deleting"].includes(workspace.state))
        ) {
          pollDeadline.current = 0;
          pollAttempt.current = 0;
          void loadBanks();
        }
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [offset, query, refresh, loadBanks]);
  // Poll directory state, not one request per row. Refresh never resends writes.
  useEffect(() => {
    if (
      loading ||
      !page.items.some((workspace) => ["creating", "deleting"].includes(workspace.state))
    )
      return;
    if (!pollDeadline.current) pollDeadline.current = Date.now() + 120000;
    if (Date.now() >= pollDeadline.current) {
      setPollExpired(true);
      return;
    }
    const timer = setTimeout(
      () => setRefresh((value) => value + 1),
      Math.min(1000 * 2 ** pollAttempt.current++, 5000)
    );
    return () => clearTimeout(timer);
  }, [page.items, loading]);
  const run = async (action: (signal: AbortSignal) => Promise<unknown>) => {
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      await action(abort.signal);
      await loadBanks();
    } catch (err) {
      setError(
        abort.signal.aborted ? t("pollStopped") : err instanceof Error ? err.message : t("failed")
      );
    } finally {
      setBusy(false);
      controller.current = null;
      sync();
    }
  };
  // Restoring a page never resubmits POST/DELETE. Known operation IDs are queried
  // only; unknown outcomes require an explicit replay of the saved request.
  useEffect(() => {
    const known = workspaceIntents().filter((intent) => intent.operation_id);
    if (!known.length) return;
    const abort = new AbortController();
    void Promise.all(
      known.map(async (intent) => {
        try {
          const operation = await contextDBRequest<{ state: string }>(
            `/operations/${intent.operation_id}`,
            { signal: abort.signal }
          );
          if (!abort.signal.aborted && operation.state === "succeeded") {
            removeWorkspaceIntent(intent.idempotency_key);
            setIntents(workspaceIntents());
          }
        } catch {
          /* The directory retains the intent and offers explicit GET recovery. */
        }
      })
    );
    return () => abort.abort();
  }, [refresh]);
  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex justify-between">
        <h1 className="text-2xl font-bold">{t("workspaceDirectory")}</h1>
        <Button disabled={busy} onClick={() => setOpen(true)}>
          {t("createWorkspace")}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <Input
          aria-label={t("spaces")}
          value={query}
          maxLength={128}
          onChange={(event) => {
            setQuery(event.target.value);
            setOffset(0);
          }}
        />
        <Button variant="outline" disabled={loading} onClick={sync}>
          {t("refresh")}
        </Button>
        {busy && (
          <Button variant="outline" onClick={() => controller.current?.abort()}>
            {t("stopPolling")}
          </Button>
        )}
      </div>
      {pollExpired && <p role="status">{t("pollStopped")}</p>}
      {!!intents.length && (
        <section className="space-y-3 rounded border p-4">
          <h2>{t("pendingOperations")}</h2>
          {intents.map((intent) => (
            <div className="space-y-2 border-t py-2" key={intent.idempotency_key}>
              <p className="break-all font-mono text-sm">
                {intent.operation_id ?? intent.idempotency_key}
              </p>
              <p className="text-sm">
                {t(intent.operation_id ? "operationKnown" : "operationUnknown")}
              </p>
              <Button
                disabled={busy || (!intent.operation_id && !canReplayWorkspaceIntent(intent))}
                variant="outline"
                onClick={() =>
                  void run(async (signal) => {
                    if (intent.operation_id) {
                      await waitForWorkspaceOperation(intent.operation_id, signal);
                      removeWorkspaceIntent(intent.idempotency_key);
                    } else {
                      await workspaceMutation(
                        intent.path,
                        intent.method,
                        intent.idempotency_key,
                        intent.raw_body ? JSON.parse(intent.raw_body) : undefined,
                        signal,
                        intent.etag
                      );
                    }
                  })
                }
              >
                {t(intent.operation_id ? "checkOperation" : "continueOperation")}
              </Button>
              {!canReplayWorkspaceIntent(intent) && (
                <p className="text-sm">{t("recoveryExpired")}</p>
              )}
              {intent.operation_id && (
                <>
                  <p className="text-sm">{t("operationUnknown")}</p>
                  <Button
                    variant="outline"
                    disabled={busy || !canReplayWorkspaceIntent(intent)}
                    onClick={() => void run((signal) => replayWorkspaceIntent(intent, signal))}
                  >
                    {t("continueOperation")}
                  </Button>
                </>
              )}
            </div>
          ))}
        </section>
      )}
      {loading ? (
        <p>{t("loading")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left">
              <th>{t("name")}</th>
              <th>{t("workspaceDescription")}</th>
              <th>{t("workspaceState")}</th>
              <th>{t("actions")}</th>
            </tr>
          </thead>
          <tbody>
            {page.items.map((workspace) => (
              <tr className="border-b" key={workspace.workspace_id}>
                <td className="py-4" title={workspace.bank_id}>
                  {workspace.name}
                </td>
                <td>{workspace.description}</td>
                <td>
                  {["active", "creating", "deleting"].includes(workspace.state)
                    ? t(workspace.state)
                    : workspace.state === "failed"
                      ? t("failedState")
                      : workspace.state}
                </td>
                <td>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      disabled={workspace.state !== "active"}
                      onClick={() => {
                        setCurrentBank(workspace.bank_id);
                        router.push(bankRoute(workspace.bank_id));
                      }}
                    >
                      {t("openWorkspace")}
                    </Button>
                    {workspace.state === "failed" && workspace.latest_operation_id && (
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void run(async (signal) => {
                            const operation = await contextDBRequest<{
                              state: string;
                              error_code?: string | null;
                            }>(`/operations/${workspace.latest_operation_id}`, { signal });
                            setError(
                              operation.state === "failed"
                                ? t("workspaceOperationFailed")
                                : t("operationPending")
                            );
                          })
                        }
                      >
                        {t("viewFailure")}
                      </Button>
                    )}
                    <Button
                      variant="destructive"
                      disabled={busy || !["active", "frozen", "failed"].includes(workspace.state)}
                      onClick={() => setDeleting(workspace)}
                    >
                      {t("delete")}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!loading && !page.items.length && <p>{t("createWorkspaceFirst")}</p>}
      <div className="flex items-center gap-3">
        <Button
          variant="outline"
          disabled={!offset || loading}
          onClick={() => setOffset(Math.max(0, offset - 20))}
        >
          {t("previous")}
        </Button>
        <span>
          {page.total ? offset + 1 : 0}–{offset + page.items.length} / {page.total}
        </span>
        <Button
          variant="outline"
          disabled={loading || offset + 20 >= page.total}
          onClick={() => setOffset(offset + 20)}
        >
          {t("next")}
        </Button>
      </div>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("createWorkspace")}</DialogTitle>
            <DialogDescription>{t("operationPending")}</DialogDescription>
          </DialogHeader>
          <Label htmlFor="workspace-name">{t("workspaceName")}</Label>
          <Input
            id="workspace-name"
            value={name}
            maxLength={54}
            pattern="[A-Za-z][A-Za-z0-9_]{0,53}"
            aria-describedby="workspace-name-help"
            onChange={(event) => setName(event.target.value)}
          />
          <p id="workspace-name-help" className="text-sm text-muted-foreground">
            {t("workspaceNameHelp")}
          </p>
          <Label htmlFor="workspace-description">{t("workspaceDescription")}</Label>
          <Input
            id="workspace-description"
            value={description}
            maxLength={512}
            onChange={(event) => setDescription(event.target.value)}
          />
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={busy || !/^[A-Za-z][A-Za-z0-9_]{0,53}$/.test(name.trim())}
              onClick={() => {
                const body = { name, description };
                setOpen(false);
                void run((signal) =>
                  workspaceMutation("/workspaces", "POST", managementRequestId(), body, signal)
                );
              }}
            >
              {t("createWorkspace")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!deleting}
        onOpenChange={(value) => {
          if (!value && !busy) setDeleting(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("delete")}</DialogTitle>
            <DialogDescription>
              {t("deleteWorkspaceWarning", { name: deleting?.name ?? "" })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => {
                const target = deleting;
                setDeleting(null);
                if (target)
                  void run((signal) =>
                    workspaceMutation(
                      `/workspaces/${target.bank_id}`,
                      "DELETE",
                      managementRequestId(),
                      undefined,
                      signal,
                      target.etag
                    )
                  );
              }}
            >
              {t("delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
