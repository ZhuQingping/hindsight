"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ContextDBCreateWorkspaceDialog } from "@/components/contextdb/create-workspace-dialog";
import {
  ContextDBWorkspaceResultCheck,
  type WorkspaceCheckTarget,
} from "@/components/contextdb/workspace-result-check";
import { useBank } from "@/lib/bank-context";
import { bankRoute } from "@/lib/bank-url";
import {
  contextDBRequest,
  contextDBWriteOutcome,
  workspaceMutation,
  type ContextDBWorkspace,
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
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState<ContextDBWorkspace | null>(null);
  const [checkTarget, setCheckTarget] = useState<WorkspaceCheckTarget | null>(null);
  const [readError, setReadError] = useState("");
  const controller = useRef<AbortController | null>(null);
  const sync = useCallback(() => setRefresh((value) => value + 1), []);
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setReadError("");
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
      })
      .catch((err) => {
        if (!abort.signal.aborted) setReadError(err.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [offset, query, refresh]);

  const deleteWorkspace = async (target: ContextDBWorkspace) => {
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setDeleting(null);
    try {
      // Retain the identity shown at confirmation, even if the name is reused
      // while this request is waiting. A directory refresh never replays DELETE.
      await workspaceMutation(
        `/workspaces/${target.bank_id}`,
        "DELETE",
        undefined,
        abort.signal,
        target.etag
      );
      await loadBanks();
    } catch (err) {
      if (!abort.signal.aborted) {
        setError(err instanceof Error ? err.message : t("failed"));
        const outcome = contextDBWriteOutcome(err);
        if (outcome !== "failed") setCheckTarget({ ...target, reason: outcome });
      }
    } finally {
      if (!abort.signal.aborted) {
        setBusy(false);
        sync();
      }
      controller.current = null;
    }
  };

  return (
    <div className="w-full min-w-0 space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
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
      {readError && <p role="alert">{readError}</p>}
      {checkTarget && (
        <ContextDBWorkspaceResultCheck target={checkTarget} onClose={() => setCheckTarget(null)} />
      )}
      {busy && <p role="status">{t("workspaceSubmitting")}</p>}
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
      </div>
      {loading ? (
        <p>{t("loading")}</p>
      ) : (
        <div
          className="w-full overflow-x-auto rounded-md border"
          role="region"
          aria-label={t("workspaceDirectory")}
          tabIndex={0}
        >
          <table className="w-full min-w-[48rem] table-fixed text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th scope="col" className="w-[26%] px-4 py-3">
                  {t("name")}
                </th>
                <th scope="col" className="px-4 py-3">
                  {t("workspaceDescription")}
                </th>
                <th scope="col" className="w-28 px-4 py-3">
                  {t("workspaceState")}
                </th>
                <th scope="col" className="w-60 px-4 py-3">
                  {t("actions")}
                </th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((workspace) => (
                <tr className="border-b last:border-b-0" key={workspace.workspace_id}>
                  <th
                    scope="row"
                    className="whitespace-normal break-all px-4 py-4 text-left align-top font-medium"
                    title={workspace.bank_id}
                  >
                    {workspace.name}
                  </th>
                  <td className="whitespace-pre-wrap break-words px-4 py-4 align-top [overflow-wrap:anywhere]">
                    {workspace.description || "—"}
                  </td>
                  <td className="px-4 py-4 align-top">
                    {["active", "creating", "deleting"].includes(workspace.state)
                      ? t(workspace.state)
                      : workspace.state === "failed"
                        ? t("failedState")
                        : workspace.state}
                  </td>
                  <td className="px-4 py-4 align-top">
                    <div className="flex flex-wrap gap-2">
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
                      <Button
                        variant="destructive"
                        disabled={busy || !["active", "failed"].includes(workspace.state)}
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
        </div>
      )}
      {!loading && !page.items.length && <p>{t("createWorkspaceFirst")}</p>}
      <div className="flex flex-wrap items-center gap-3">
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
      <ContextDBCreateWorkspaceDialog
        open={open}
        onOpenChange={setOpen}
        onCreated={() => {
          setError("");
          sync();
          void loadBanks();
        }}
        onCheckResult={(bankId) => setCheckTarget({ bank_id: bankId })}
      />
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
                if (deleting) void deleteWorkspace(deleting);
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
