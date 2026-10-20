"use client";

import { useEffect, useRef, useState } from "react";
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

const LIMIT = 20;
const emptyPage = (): Page<ContextDBKeyMetadata> => ({
  items: [],
  total: 0,
  limit: LIMIT,
  offset: 0,
});
const date = (value: string | null) => (value ? new Date(value).toLocaleString() : "—");

/** Mounted with key=user_id: requests, credentials and dialogs belong to one member. */
export function ContextDBUserKeysPanel({ user }: { user: ContextDBUser }) {
  const t = useTranslations("contextDB");
  const [keys, setKeys] = useState(emptyPage);
  const [keyOffset, setKeyOffset] = useState(0);
  const [keyRefresh, setKeyRefresh] = useState(0);
  const [keysLoading, setKeysLoading] = useState(true);
  const [keysLoaded, setKeysLoaded] = useState(false);
  const [error, setError] = useState("");
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
    setError("");
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
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : t("failed"));
      })
      .finally(() => {
        if (!controller.signal.aborted) setKeysLoading(false);
      });
    return () => controller.abort();
  }, [user.user_id, keyOffset, keyRefresh, t]);
  const allowSecret = useRef(true);
  useEffect(() => {
    const clear = () => {
      allowSecret.current = false;
      setSecret("");
    };
    const hidden = () => {
      if (document.hidden) clear();
    };
    // Also invalidate a pending issuance. A late response after pagehide must
    // not reintroduce a credential that navigation was meant to clear.
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", clear);
    return () => {
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", clear);
    };
  }, []);
  useEffect(() => {
    if (!secret) return;
    const timer = setTimeout(() => setSecret(""), 60000);
    return () => clearTimeout(timer);
  }, [secret]);
  const openEditor = (key: ContextDBKeyEditable | null) => {
    if (!key) allowSecret.current = !document.hidden;
    setEditor({ key });
  };

  const saved = (issued?: ContextDBKeyIssued) => {
    setEditor(null);
    refreshKeys();
    if (issued) {
      if (allowSecret.current && !document.hidden) setSecret(issued.secret);
      else {
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
  const pager = (
    page: Page<unknown>,
    start: number,
    change: (offset: number) => void,
    pending: boolean
  ) => (
    <div className="mt-3 flex items-center gap-3">
      <Button
        variant="outline"
        disabled={pending || start === 0}
        onClick={() => change(Math.max(0, start - LIMIT))}
      >
        {t("previous")}
      </Button>
      <span>
        {page.total ? start + 1 : 0}–{start + page.items.length} / {page.total}
      </span>
      <Button
        variant="outline"
        disabled={pending || start + LIMIT >= page.total}
        onClick={() => change(start + LIMIT)}
      >
        {t("next")}
      </Button>
    </div>
  );
  return (
    <div className="space-y-3 rounded bg-muted/20 p-4">
      {error && <p role="alert">{error}</p>}
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
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{t("userKeys", { name: user.name })}</h2>
        <div className="flex gap-2">
          <Button variant="outline" disabled={keysLoading || busy} onClick={() => refreshKeys()}>
            {t("refresh")}
          </Button>
          <Button
            disabled={busy || issueUnknown || user.status !== "active"}
            onClick={() => openEditor(null)}
          >
            {t("createKey")}
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">{t("keyHelp")}</p>
      {user.status === "disabled" && <p role="status">{t("disabledHelp")}</p>}
      {keysLoading ? (
        <p>{t("loading")}</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left">
              <th>{t("name")}</th>
              <th>{t("maskedKey")}</th>
              <th>
                {t("spaces")} / {t("permission")}
              </th>
              <th>{t("createdAt")}</th>
              <th>{t("lastUsed")}</th>
              <th>{t("actions")}</th>
            </tr>
          </thead>
          <tbody>
            {keys.items.map((key) => (
              <tr key={key.key_id} className="border-t">
                <td className="py-3">
                  {key.name}
                  <span className="block break-all text-xs text-muted-foreground">
                    {t("keyId", { id: key.key_id })}
                  </span>
                </td>
                <td className="font-mono">{displayKey(key)}</td>
                <td>
                  {key.authorization.mode === "all" ? (
                    `${t("allSpaces")} · ${t(key.authorization.permission === "read" ? "readOnly" : "readWrite")}`
                  ) : key.authorization.workspaces.length === 0 ? (
                    <span>{t("noAccessibleSpaces")}</span>
                  ) : (
                    <details>
                      <summary>
                        {t("spaceCount", { count: key.authorization.workspaces.length })}
                      </summary>
                      {key.authorization.workspaces.map((space) => (
                        <div key={space.workspace_id} title={space.workspace_id}>
                          {space.workspace_name ?? space.bank_id} ·{" "}
                          {t(space.permission === "read" ? "readOnly" : "readWrite")}
                        </div>
                      ))}
                    </details>
                  )}
                </td>
                <td>{date(key.created_at)}</td>
                <td>{date(key.last_used_at)}</td>
                <td>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => openEditor(key)}
                    >
                      {t("edit")}
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={busy}
                      onClick={() => {
                        setError("");
                        setRevokeUnknown(false);
                        setRevokingKey(key);
                      }}
                    >
                      {t("revoke")}
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {keysLoaded && !keysLoading && keys.items.length === 0 && <p>{t("emptyKeys")}</p>}
      {pager(keys, keyOffset, setKeyOffset, keysLoading)}

      {editor && (
        <ContextDBKeyEditorDialog
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
        <DialogContent>
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
          if (!open) setSecret("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("secretTitle")}</DialogTitle>
            <DialogDescription>{t("secretWarning")}</DialogDescription>
          </DialogHeader>
          <p className="break-all rounded border p-3 font-mono text-sm" data-testid="issued-secret">
            {secret}
          </p>
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                if (!navigator.clipboard?.writeText) {
                  setError(t("copyFailed"));
                  return;
                }
                void navigator.clipboard.writeText(secret).catch(() => setError(t("copyFailed")));
              }}
            >
              {t("copySecret")}
            </Button>
            <Button onClick={() => setSecret("")}>{t("closeSecret")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
