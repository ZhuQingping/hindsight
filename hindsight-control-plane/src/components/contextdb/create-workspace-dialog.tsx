"use client";

import { useEffect, useId, useRef, useState, type RefObject, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ContextDBError, workspaceMutation, type ContextDBWorkspace } from "@/lib/contextdb-api";

import { restoreDialogFocus } from "./dialog-focus";

/** Both entry points share the same fields, validation, and synchronous request. */
export function ContextDBCreateWorkspaceDialog({
  open,
  onOpenChange,
  onCreated,
  onCheckResult,
  returnFocusRef,
}: {
  returnFocusRef?: RefObject<HTMLElement | null>;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (workspace: ContextDBWorkspace) => void;
  onCheckResult: (bankId: string) => void;
}) {
  const t = useTranslations("contextDB");
  const id = useId();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const validName = /^[A-Za-z][A-Za-z0-9_]{0,53}$/.test(name.trim());
  useEffect(() => () => controller.current?.abort(), []);
  useEffect(() => {
    if (!open) {
      controller.current?.abort();
      setBusy(false);
      setName("");
      setDescription("");
      setError("");
      setUnknown(false);
    }
  }, [open]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || unknown || !validName) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      const workspace = await workspaceMutation(
        "/workspaces",
        "POST",
        { name, description },
        abort.signal
      );
      // A closed/unmounted entry point must not navigate from a late success.
      if (abort.signal.aborted) return;
      onOpenChange(false);
      onCreated(workspace);
    } catch (err) {
      if (abort.signal.aborted) return;
      setError(err instanceof Error ? err.message : t("failed"));
      // A lost response can follow a committed create. Offer a directory check,
      // never an automatic replay or a claim that the server rolled it back.
      setUnknown(err instanceof ContextDBError && (err.status === 0 || err.status >= 500));
    } finally {
      if (!abort.signal.aborted) setBusy(false);
      if (controller.current === abort) controller.current = null;
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) onOpenChange(value);
      }}
    >
      <DialogContent
        className="w-[calc(100%-2rem)]"
        onCloseAutoFocus={(event) => restoreDialogFocus(event, returnFocusRef?.current ?? null)}
      >
        <form noValidate onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{t("createWorkspace")}</DialogTitle>
            <DialogDescription>{t("createWorkspaceHelp")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={`${id}-name`}>{t("workspaceName")}</Label>
            <Input
              id={`${id}-name`}
              value={name}
              maxLength={54}
              pattern="[A-Za-z][A-Za-z0-9_]{0,53}"
              aria-describedby={`${id}-help`}
              disabled={busy || unknown}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
            <p id={`${id}-help`} className="text-sm text-muted-foreground">
              {t("workspaceNameHelp")}
            </p>
          </div>
          <div className="space-y-2">
            <Label htmlFor={`${id}-description`}>{t("workspaceDescription")}</Label>
            <Textarea
              id={`${id}-description`}
              value={description}
              maxLength={512}
              disabled={busy || unknown}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          {busy && (
            <p role="status" className="text-sm">
              {t("workspaceSubmitting")}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              {t("cancel")}
            </Button>
            {unknown ? (
              <Button
                type="button"
                onClick={() => {
                  onOpenChange(false);
                  onCheckResult(name.normalize("NFKC").trim().toLowerCase());
                }}
              >
                {t("checkWorkspaceResult")}
              </Button>
            ) : (
              <Button type="submit" disabled={busy || !validName}>
                {t("createWorkspace")}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
