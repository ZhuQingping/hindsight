"use client";

import { useEffect, useState, type RefObject } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ContextDBError, contextDBRequest, type ContextDBWorkspace } from "@/lib/contextdb-api";

import { restoreDialogFocus } from "./dialog-focus";

export interface WorkspaceCheckTarget {
  bank_id: string;
  workspace_id?: string;
  etag?: string;
  reason?: "unknown" | "conflict";
}

/** Observation only: original identity/ETag are never exchanged for a new DELETE. */
export function ContextDBWorkspaceResultCheck({
  target,
  onClose,
  returnFocusRef,
}: {
  returnFocusRef?: RefObject<HTMLElement | null>;
  target: WorkspaceCheckTarget;
  onClose: () => void;
}) {
  const t = useTranslations("contextDB");
  const failedMessage = t("failed");
  const [workspace, setWorkspace] = useState<ContextDBWorkspace | null>(null);
  const [absent, setAbsent] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const abort = new AbortController();
    setLoading(true);
    setError("");
    setAbsent(false);
    setWorkspace(null);
    contextDBRequest<ContextDBWorkspace>(`/workspaces/${encodeURIComponent(target.bank_id)}`, {
      signal: abort.signal,
    })
      .then((result) => {
        if (!abort.signal.aborted) setWorkspace(result);
      })
      .catch((err) => {
        if (abort.signal.aborted) return;
        if (err instanceof ContextDBError && err.status === 404) setAbsent(true);
        else setError(err instanceof Error ? err.message : failedMessage);
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [target.bank_id, target.workspace_id, target.etag, refresh, failedMessage]);
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent
        onCloseAutoFocus={(event) => restoreDialogFocus(event, returnFocusRef?.current ?? null)}
      >
        <DialogHeader>
          <DialogTitle>{t("checkCurrentWorkspace")}</DialogTitle>
          <DialogDescription>
            {t(
              target.reason === "conflict"
                ? "workspaceDeleteConflict"
                : target.workspace_id
                  ? "workspaceDeleteUnknown"
                  : "workspaceCheckHelp"
            )}
          </DialogDescription>
        </DialogHeader>
        <p>{t("workspaceCheckTarget", { name: target.bank_id, id: target.workspace_id ?? "—" })}</p>
        {loading && <p role="status">{t("loading")}</p>}
        {error && <p role="alert">{error}</p>}
        {absent && <p role="status">{t("workspaceAbsent", { name: target.bank_id })}</p>}
        {workspace && (
          <p role="status">
            {target.workspace_id
              ? workspace.workspace_id === target.workspace_id
                ? t("workspaceOriginal", { state: workspace.state, id: workspace.workspace_id })
                : t("workspaceSuccessor", { id: workspace.workspace_id })
              : t("workspaceObserved", {
                  name: workspace.bank_id,
                  id: workspace.workspace_id,
                  state: workspace.state,
                })}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={loading} onClick={() => setRefresh((value) => value + 1)}>
            {t("refresh")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
