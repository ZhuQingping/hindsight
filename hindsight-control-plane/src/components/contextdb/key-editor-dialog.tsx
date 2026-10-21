"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useContextDBKeyWorkspaces } from "@/components/contextdb/use-key-workspaces";
import {
  contextDBRequest,
  contextDBWriteOutcome,
  createContextDBKey,
  type ContextDBKeyEditable,
  type ContextDBKeyIssued,
  type KeyAuthorization,
  type KeyAuthorizationInput,
  type KeyPermission,
} from "@/lib/contextdb-api";

/** Display names can change independently; edits compare immutable identities. */
function keyAuthorizationSnapshot(value: KeyAuthorization): string {
  return JSON.stringify(
    value.mode === "all"
      ? value
      : {
          mode: value.mode,
          workspaces: value.workspaces
            .map(({ workspace_id, permission }) => ({ workspace_id, permission }))
            .sort((a, b) => a.workspace_id.localeCompare(b.workspace_id)),
        }
  );
}

type Grant = Extract<KeyAuthorization, { mode: "selected" }>["workspaces"][number];

function PermissionSelect({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id?: string;
  label: string;
  value: KeyPermission;
  disabled: boolean;
  onChange: (value: KeyPermission) => void;
}) {
  const t = useTranslations("contextDB");
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as KeyPermission)}
    >
      <SelectTrigger id={id} aria-label={label} className="w-auto min-w-28">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="read_write">{t("readWrite")}</SelectItem>
        <SelectItem value="read">{t("readOnly")}</SelectItem>
      </SelectContent>
    </Select>
  );
}

/** Owns one immutable editing snapshot and its draft; the directory owns neither. */
export function ContextDBKeyEditorDialog({
  userId,
  userName,
  editingKey,
  onClose,
  onSaved,
  onCheckResult,
  onCloseAutoFocus,
}: {
  onCloseAutoFocus?: (event: Event) => void;
  userId: string;
  userName: string;
  editingKey: ContextDBKeyEditable | null;
  onClose: (issuedUnknown?: boolean) => void;
  onSaved: (issued?: ContextDBKeyIssued) => void;
  onCheckResult: (issued: boolean) => void;
}) {
  const t = useTranslations("contextDB");
  const [keyName, setKeyName] = useState(editingKey?.name ?? "");
  const [access, setAccess] = useState<"all" | "selected">(
    editingKey?.authorization.mode ?? "selected"
  );
  const [grants, setGrants] = useState<Record<string, Grant>>(() =>
    editingKey?.authorization.mode === "selected"
      ? Object.fromEntries(
          editingKey.authorization.workspaces.map((grant) => [grant.workspace_id, grant])
        )
      : {}
  );
  const [permission, setPermission] = useState<KeyPermission>(
    editingKey?.authorization.mode === "all"
      ? editingKey.authorization.permission
      : editingKey?.authorization.mode === "selected" &&
          editingKey.authorization.workspaces.some((item) => item.permission === "read")
        ? "read"
        : "read_write"
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [outcome, setOutcome] = useState<"unknown" | "conflict" | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const picker = useContextDBKeyWorkspaces();
  const blocked = outcome !== null;
  // Existing grants already carry immutable identity and display metadata. Directory
  // pages add choices; they never rebind an old grant to a same-name successor.
  const choices = new Map<string, Grant>(
    Object.values(grants).map((grant) => [grant.workspace_id, grant])
  );
  for (const workspace of picker.workspaces) {
    if (workspace.state === "active" && !choices.has(workspace.workspace_id))
      choices.set(workspace.workspace_id, {
        ...workspace,
        workspace_name: workspace.name,
        permission: "read_write",
      });
  }
  const currentIds = new Map(
    picker.workspaces.map((workspace) => [workspace.bank_id, workspace.workspace_id])
  );
  const authorization: KeyAuthorizationInput =
    access === "all"
      ? { mode: "all", permission }
      : {
          mode: "selected",
          workspaces: Object.values(grants).map(({ bank_id, workspace_id, permission }) => ({
            bank_id,
            workspace_id,
            permission,
          })),
        };
  const authorizationChanged =
    !editingKey ||
    keyAuthorizationSnapshot(authorization) !== keyAuthorizationSnapshot(editingKey.authorization);

  const save = async () => {
    if (busy || blocked) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    try {
      if (editingKey) {
        const body = {
          ...(keyName.trim() !== editingKey.name ? { name: keyName.trim() } : {}),
          ...(authorizationChanged ? { authorization } : {}),
        };
        if (Object.keys(body).length)
          await contextDBRequest<ContextDBKeyEditable>(
            `/users/${userId}/keys/${editingKey.key_id}`,
            { method: "PATCH", version: editingKey.version, body, signal: abort.signal }
          );
        if (!abort.signal.aborted) onSaved();
      } else {
        const issued = await createContextDBKey(
          userId,
          { name: keyName.trim(), authorization },
          abort.signal
        );
        if (!abort.signal.aborted) onSaved(issued);
      }
    } catch (err) {
      if (abort.signal.aborted) return;
      setError(err instanceof Error ? err.message : t("failed"));
      const result = contextDBWriteOutcome(err);
      if (result !== "failed") setOutcome(result);
    } finally {
      if (!abort.signal.aborted) setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose(!editingKey && outcome === "unknown");
      }}
    >
      <DialogContent className="w-[calc(100%-2rem)]" onCloseAutoFocus={onCloseAutoFocus}>
        <DialogHeader>
          <DialogTitle>{editingKey ? t("editKey") : t("createKey")}</DialogTitle>
          <DialogDescription>
            {userName}
            {editingKey
              ? ` · ${editingKey.display_key ?? t("historicalKey", { id: editingKey.key_id })}`
              : ""}
            . {t("grantHelp")}
          </DialogDescription>
        </DialogHeader>
        <Label htmlFor="key-name">{t("name")}</Label>
        <Input
          id="key-name"
          value={keyName}
          disabled={busy || blocked}
          maxLength={64}
          onChange={(event) => setKeyName(event.target.value)}
        />
        <Label htmlFor="key-access">{t("spaces")}</Label>
        <Select
          value={access}
          disabled={busy || blocked}
          onValueChange={(value) => {
            const mode = value as "all" | "selected";
            // Changing range must never upgrade an existing read-only choice.
            if (
              mode === "all" &&
              Object.values(grants).some((grant) => grant.permission === "read")
            )
              setPermission("read");
            setAccess(mode);
          }}
        >
          <SelectTrigger id="key-access" aria-label={t("spaces")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="selected">{t("selectedSpaces")}</SelectItem>
            <SelectItem value="all">{t("allSpaces")}</SelectItem>
          </SelectContent>
        </Select>
        {access === "selected" ? (
          <div className="space-y-2">
            <Input
              aria-label={t("searchWorkspaces")}
              placeholder={t("searchWorkspaces")}
              value={picker.query}
              maxLength={128}
              disabled={busy || blocked}
              onChange={(event) => picker.setQuery(event.target.value)}
            />
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {[...choices.values()].map((choice) => {
                const id = choice.workspace_id;
                const name = choice.workspace_name ?? choice.bank_id;
                return (
                  <div className="flex items-center gap-2" key={id}>
                    <label className="flex flex-1 items-center gap-2">
                      <Checkbox
                        checked={Object.hasOwn(grants, id)}
                        disabled={busy || blocked}
                        onCheckedChange={(checked) =>
                          setGrants((previous) => {
                            const next = { ...previous };
                            if (checked) next[id] = { ...choice, permission: "read_write" };
                            else delete next[id];
                            return next;
                          })
                        }
                      />
                      {name}
                      {currentIds.has(choice.bank_id) && currentIds.get(choice.bank_id) !== id
                        ? ` (${t("unavailable")})`
                        : ""}
                    </label>
                    {Object.hasOwn(grants, id) && (
                      <PermissionSelect
                        label={`${name} ${t("permission")}`}
                        value={grants[id].permission}
                        disabled={busy || blocked}
                        onChange={(value) =>
                          setGrants((previous) => ({
                            ...previous,
                            [id]: { ...previous[id], permission: value },
                          }))
                        }
                      />
                    )}
                  </div>
                );
              })}
              {picker.loading && <p>{t("loading")}</p>}
              {picker.hasMore && (
                <Button
                  variant="outline"
                  disabled={picker.loading}
                  onClick={() => void picker.loadMore()}
                >
                  {t("moreWorkspaces")}
                </Button>
              )}
              {!picker.loading && !picker.error && !picker.workspaces.length && (
                <p>{t(picker.query ? "noMatches" : "emptyWorkspaces")}</p>
              )}
              {picker.error && (
                <Button
                  variant="outline"
                  disabled={busy || blocked}
                  onClick={() => void picker.retry()}
                >
                  {t("refresh")}
                </Button>
              )}
            </div>
          </div>
        ) : (
          <>
            <Label htmlFor="key-permission">{t("permission")}</Label>
            <PermissionSelect
              id="key-permission"
              label={t("permission")}
              value={permission}
              disabled={busy || blocked}
              onChange={setPermission}
            />
          </>
        )}
        <div className="space-y-1 text-sm text-muted-foreground">
          <p>
            <strong>{t("readOnly")}: </strong>
            {t("readOnlyHelp")}
          </p>
          <p>
            <strong>{t("readWrite")}: </strong>
            {t("readWriteHelp")}
          </p>
          <p>{t("managementRestriction")}</p>
        </div>

        {(error || picker.error) && <p role="alert">{error || picker.error}</p>}
        {outcome && (
          <p role="status">
            {t(!editingKey && outcome === "unknown" ? "keyIssueUnknown" : "editNeedsCheck")}
          </p>
        )}
        <DialogFooter>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => onClose(!editingKey && outcome === "unknown")}
          >
            {t("cancel")}
          </Button>
          {blocked ? (
            <Button onClick={() => onCheckResult(!editingKey)}>{t("checkKeys")}</Button>
          ) : (
            <Button
              disabled={
                busy ||
                !keyName.trim() ||
                (authorizationChanged && access === "selected" && !Object.keys(grants).length)
              }
              onClick={() => void save()}
            >
              {busy ? t("saving") : t(editingKey ? "saveKeyChanges" : "createKeyAction")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
