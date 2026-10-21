"use client";

import { useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ChevronRight } from "lucide-react";
import { DirectoryPagination } from "./directory-pagination";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ContextDBKeyEditorDialog } from "@/components/contextdb/key-editor-dialog";
import {
  contextDBRequest,
  contextDBWriteOutcome,
  type ContextDBUser,
  type ContextDBKeyMetadata,
  type ContextDBKeyEditable,
  type ContextDBKeyIssued,
  type Page,
} from "@/lib/contextdb-api";

import { restoreDialogFocus } from "./dialog-focus";

const LIMIT = 20;
const emptyPage = (): Page<ContextDBKeyMetadata> => ({
  items: [],
  total: 0,
  limit: LIMIT,
  offset: 0,
});

/** Mounted with key=user_id: requests, credentials and dialogs belong to one member. */
export function ContextDBUserKeysPanel({ user }: { user: ContextDBUser }) {
  const t = useTranslations("contextDB");
  const locale = useLocale();
  const date = (value: string | null) => (value ? new Date(value).toLocaleString(locale) : "—");
  const createButton = useRef<HTMLButtonElement>(null);
  const editorTrigger = useRef<HTMLButtonElement | null>(null);
  const revokeTrigger = useRef<HTMLButtonElement | null>(null);
  const [keys, setKeys] = useState(emptyPage);
  const [keyOffset, setKeyOffset] = useState(0);
  const [keyRefresh, setKeyRefresh] = useState(0);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysLoaded, setKeysLoaded] = useState(false);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const shownSecret = useRef("");
  const copyAttempt = useRef(0);
  const [busy, setBusy] = useState(false);
  const [editor, setEditor] = useState<{ key: ContextDBKeyEditable | null } | null>(null);
  const [revokingKey, setRevokingKey] = useState<ContextDBKeyMetadata | null>(null);
  const [revokeUnknown, setRevokeUnknown] = useState(false);
  const [issueUnknown, setIssueUnknown] = useState(false);
  const [notice, setNotice] = useState("");
  const [secret, setSecret] = useState("");
  const writeController = useRef<AbortController | null>(null);
  useEffect(() => () => writeController.current?.abort(), []);
  const refreshKeys = () => setKeyRefresh((value) => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setKeysLoading(true);
    setReadError("");
    contextDBRequest<Page<ContextDBKeyMetadata>>(
      `/users/${user.user_id}/keys?limit=${LIMIT}&offset=${keyOffset}`,
      { signal: controller.signal }
    )
      .then((page) => {
        if (controller.signal.aborted) return;
        if (keyOffset > 0 && keyOffset >= page.total) {
          setKeyOffset(Math.max(0, Math.ceil(page.total / LIMIT) * LIMIT - LIMIT));
          return;
        }
        setKeys(page);
        setKeysLoaded(true);
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setReadError(err instanceof Error ? err.message : t("failed"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setKeysLoading(false);
      });
    return () => controller.abort();
  }, [user.user_id, keyOffset, keyRefresh, t]);
  const allowSecret = useRef(true);
  const clearSecret = () => {
    shownSecret.current = "";
    copyAttempt.current += 1;
    setSecret("");
    setCopied(false);
    setCopyError("");
  };
  useEffect(() => {
    const leave = () => {
      allowSecret.current = false;
      clearSecret();
    };
    window.addEventListener("pagehide", leave);
    return () => {
      allowSecret.current = false;
      shownSecret.current = "";
      copyAttempt.current += 1;
      window.removeEventListener("pagehide", leave);
    };
  }, []);
  const openEditor = (key: ContextDBKeyEditable | null) => {
    if (!key) allowSecret.current = true;
    setEditor({ key });
  };
  const copySecret = async () => {
    const value = shownSecret.current;
    const attempt = ++copyAttempt.current;
    setCopyError("");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      if (shownSecret.current === value && copyAttempt.current === attempt) setCopied(true);
    } catch {
      if (shownSecret.current === value && copyAttempt.current === attempt) {
        setCopied(false);
        setCopyError(t("copyFailed"));
      }
    }
  };

  const saved = (issued?: ContextDBKeyIssued) => {
    setEditor(null);
    refreshKeys();
    if (issued) {
      if (allowSecret.current) {
        clearSecret();
        shownSecret.current = issued.secret;
        setSecret(issued.secret);
      } else {
        setIssueUnknown(true);
        setNotice(t("keySecretNotShown", { id: issued.key_id }));
      }
    }
  };
  const checkKeys = (issued: boolean) => {
    const targetId = editor?.key?.key_id ?? revokingKey?.key_id;
    setEditor(null);
    setRevokingKey(null);
    setRevokeUnknown(false);
    if (issued) setIssueUnknown(true);
    setNotice(
      issued
        ? t("keyIssueUnknown")
        : t("keyRecordsCheck") + (targetId ? ` ${t("keyId", { id: targetId })}` : "")
    );
    setKeyOffset(0);
    refreshKeys();
  };
  const revoke = async () => {
    if (!revokingKey || busy || revokeUnknown) return;
    const abort = new AbortController();
    writeController.current = abort;
    setBusy(true);
    setError("");
    try {
      await contextDBRequest(`/users/${user.user_id}/keys/${revokingKey.key_id}`, {
        method: "DELETE",
        signal: abort.signal,
      });
      if (!abort.signal.aborted) {
        setRevokingKey(null);
        refreshKeys();
      }
    } catch (err) {
      if (!abort.signal.aborted) {
        setError(err instanceof Error ? err.message : t("failed"));
        setRevokeUnknown(contextDBWriteOutcome(err) !== "failed");
      }
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  };
  const displayKey = (key: ContextDBKeyMetadata) =>
    key.display_key ?? t("historicalKey", { id: key.key_id });
  return (
    <section
      aria-label={t("userKeys", { name: user.name })}
      className="min-w-0 space-y-3 rounded-lg bg-muted/20 p-3 md:p-4"
    >
      {error && <p role="alert">{error}</p>}
      {readError && <p role="alert">{readError}</p>}
      {notice && <p role="status">{notice}</p>}
      {issueUnknown && user.status === "active" && (
        <Button
          variant="outline"
          onClick={() => {
            setIssueUnknown(false);
            openEditor(null);
          }}
        >
          {t("newKeyAttempt")}
        </Button>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">
          {t("keyListTitle")}
          {keysLoaded && !keysLoading && !readError && keys.total > 0 && ` (${keys.total})`}
        </h2>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={keysLoading || busy}
            onClick={() => refreshKeys()}
          >
            {t("refresh")}
          </Button>
          <Button
            size="sm"
            disabled={busy || issueUnknown || user.status !== "active"}
            ref={createButton}
            onClick={(event) => {
              editorTrigger.current = event.currentTarget;
              openEditor(null);
            }}
          >
            {t("createKey")}
          </Button>
        </div>
      </div>
      {user.status === "disabled" && <p role="status">{t("disabledHelp")}</p>}
      {keysLoading ? (
        <p>{t("loading")}</p>
      ) : readError ? (
        <p>{t(keysLoaded ? "staleResults" : "readUnavailable")}</p>
      ) : keys.items.length === 0 ? (
        <p>{t("emptyKeys")}</p>
      ) : (
        <ul aria-label={t("keyListTitle")} className="divide-y divide-border">
          {keys.items.map((key) => (
            <li key={key.key_id} className="min-w-0 space-y-2 py-3 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                  <p className="font-medium">{key.name}</p>
                  <p className="break-all font-mono text-xs text-muted-foreground">
                    {displayKey(key)}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={(event) => {
                      editorTrigger.current = event.currentTarget;
                      openEditor(key);
                    }}
                  >
                    {t("edit")}
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busy}
                        aria-label={`${t("more")}: ${key.name}`}
                        onFocus={(event) => {
                          revokeTrigger.current = event.currentTarget;
                        }}
                      >
                        {t("more")}
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem
                        className="text-destructive focus:text-destructive"
                        onSelect={() => {
                          setError("");
                          setRevokeUnknown(false);
                          setRevokingKey(key);
                        }}
                      >
                        {t("revoke")}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
              <div className="min-w-0 text-sm [overflow-wrap:anywhere]">
                {key.authorization.mode === "all" ? (
                  `${t("allSpaces")} · ${t(key.authorization.permission === "read" ? "readOnly" : "readWrite")}`
                ) : key.authorization.workspaces.length === 0 ? (
                  <span>{t("noAccessibleSpaces")}</span>
                ) : key.authorization.workspaces.length === 1 ? (
                  <p title={key.authorization.workspaces[0].workspace_id}>
                    {key.authorization.workspaces[0].workspace_name ??
                      key.authorization.workspaces[0].bank_id}
                    {" · "}
                    {t(
                      key.authorization.workspaces[0].permission === "read"
                        ? "readOnly"
                        : "readWrite"
                    )}
                  </p>
                ) : (
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden">
                      <ChevronRight
                        aria-hidden="true"
                        className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                      />
                      {t("spaceCount", { count: key.authorization.workspaces.length })}
                    </summary>
                    {key.authorization.workspaces.map((space) => (
                      <div
                        key={space.workspace_id}
                        title={space.workspace_id}
                        className="break-words"
                      >
                        {space.workspace_name ?? space.bank_id} ·{" "}
                        {t(space.permission === "read" ? "readOnly" : "readWrite")}
                      </div>
                    ))}
                  </details>
                )}
              </div>
              <details className="group min-w-0 text-xs text-muted-foreground">
                <summary className="flex cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden">
                  <ChevronRight
                    aria-hidden="true"
                    className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90"
                  />
                  {t("keyDetails")}
                </summary>
                <span className="block break-all select-all">{t("keyId", { id: key.key_id })}</span>
                <span className="block">
                  {t("createdAt")}: {date(key.created_at)}
                </span>
                <span className="block">
                  {t("lastUsed")}: {date(key.last_used_at)}
                </span>
              </details>
            </li>
          ))}
        </ul>
      )}
      {keysLoaded && !keysLoading && !readError && keys.total > LIMIT && (
        <DirectoryPagination
          total={keys.total}
          count={keys.items.length}
          offset={keyOffset}
          limit={LIMIT}
          loading={keysLoading}
          onChange={setKeyOffset}
        />
      )}

      {editor && (
        <ContextDBKeyEditorDialog
          onCloseAutoFocus={(event) =>
            restoreDialogFocus(event, editorTrigger.current, createButton.current)
          }
          userId={user.user_id}
          userName={user.name}
          editingKey={editor.key}
          onClose={(unknown) => {
            setEditor(null);
            if (unknown) {
              setIssueUnknown(true);
              setNotice(t("keyIssueUnknown"));
            }
          }}
          onSaved={saved}
          onCheckResult={(issued) => void checkKeys(issued)}
        />
      )}
      <Dialog
        open={!!revokingKey}
        onOpenChange={(open) => {
          if (!open && !busy) {
            if (revokeUnknown) setNotice(t("keyRecordsCheck"));
            setRevokingKey(null);
          }
        }}
      >
        <DialogContent
          className="w-[calc(100%-2rem)]"
          onCloseAutoFocus={(event) =>
            restoreDialogFocus(event, revokeTrigger.current, createButton.current)
          }
        >
          <DialogHeader>
            <DialogTitle>{t("revokeTitle")}</DialogTitle>
            <DialogDescription>
              {user.name} · {revokingKey?.name} · {revokingKey ? displayKey(revokingKey) : ""}.{" "}
              {t("revokeWarning")}
            </DialogDescription>
          </DialogHeader>
          {error && <p role="alert">{error}</p>}
          {revokeUnknown && <p role="status">{t("keyRecordsCheck")}</p>}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                if (revokeUnknown) setNotice(t("keyRecordsCheck"));
                setRevokingKey(null);
              }}
            >
              {t("cancel")}
            </Button>
            {revokeUnknown ? (
              <Button onClick={() => void checkKeys(false)}>{t("checkKeys")}</Button>
            ) : (
              <Button variant="destructive" disabled={busy} onClick={() => void revoke()}>
                {t("revoke")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!secret}
        onOpenChange={(open) => {
          if (!open) clearSecret();
        }}
      >
        <DialogContent
          className="w-[calc(100%-2rem)]"
          onCloseAutoFocus={(event) => restoreDialogFocus(event, createButton.current)}
        >
          <DialogHeader>
            <DialogTitle>{t("secretTitle")}</DialogTitle>
            <DialogDescription>{t("secretWarning")}</DialogDescription>
          </DialogHeader>
          <p className="break-all rounded border p-3 font-mono text-sm" data-testid="issued-secret">
            {secret}
          </p>
          {copyError && <p role="alert">{copyError}</p>}
          {copied && <p role="status">{t("copied")}</p>}
          <DialogFooter>
            <Button onClick={() => void copySecret()}>{t("copySecret")}</Button>
            <Button variant="outline" onClick={clearSecret}>
              {t("closeSecret")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
