"use client";

import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  contextDBRequest,
  type ContextDBUser,
  type ContextDBKey,
  type ContextDBWorkspace,
  type KeyAuthorization,
  type KeyAuthorizationInput,
  type KeyPermission,
  type Page,
} from "@/lib/contextdb-api";

const LIMIT = 20;
const emptyPage = <T,>(): Page<T> => ({ items: [], total: 0, limit: LIMIT, offset: 0 });
const date = (value: string | null) => (value ? new Date(value).toLocaleString() : "—");

function authorizationSnapshot(value: KeyAuthorization): string {
  // Read-only display names do not participate in an authorization edit.
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

export function ContextDBUsersView() {
  const t = useTranslations("contextDB");
  const [users, setUsers] = useState<Page<ContextDBUser>>(emptyPage);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [keyRefresh, setKeyRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedUser, setSelectedUser] = useState<ContextDBUser | null>(null);
  const [keys, setKeys] = useState<Page<ContextDBKey>>(emptyPage);
  const [keyOffset, setKeyOffset] = useState(0);
  const [keysLoading, setKeysLoading] = useState(false);
  const [keysLoaded, setKeysLoaded] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<ContextDBUser | null>(null);
  const [name, setName] = useState("");
  const [deletingUser, setDeletingUser] = useState<ContextDBUser | null>(null);
  const [revokingKey, setRevokingKey] = useState<ContextDBKey | null>(null);
  const [keyOpen, setKeyOpen] = useState(false);
  const [editingKey, setEditingKey] = useState<ContextDBKey | null>(null);
  const [keyName, setKeyName] = useState("");
  const [access, setAccess] = useState<"all" | "selected">("selected");
  const [grants, setGrants] = useState<Record<string, KeyPermission>>({});
  const [permission, setPermission] = useState<KeyPermission>("read_write");
  const [secret, setSecret] = useState("");
  const [workspaceMap, setWorkspaceMap] = useState<Record<string, ContextDBWorkspace | null>>({});
  const workspaceCache = useRef<Record<string, ContextDBWorkspace | null>>({});
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [workspaceTotal, setWorkspaceTotal] = useState(0);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const workspaceOffset = useRef(0);
  const workspaceGeneration = useRef(0);

  const loadWorkspaces = useCallback(
    async (append = false) => {
      const generation = ++workspaceGeneration.current;
      setWorkspaceLoading(true);
      try {
        const start = append ? workspaceOffset.current : 0;
        const page = await contextDBRequest<Page<ContextDBWorkspace>>(
          `/workspaces?limit=50&offset=${start}`
        );
        if (generation !== workspaceGeneration.current) return;
        workspaceCache.current = {
          ...workspaceCache.current,
          ...Object.fromEntries(page.items.map((item) => [item.workspace_id, item])),
        };
        setWorkspaceMap(workspaceCache.current);
        setWorkspaceIds((previous) => [
          ...new Set([...(append ? previous : []), ...page.items.map((item) => item.workspace_id)]),
        ]);
        workspaceOffset.current = start + page.items.length;
        setWorkspaceTotal(page.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : t("failed"));
      } finally {
        if (generation === workspaceGeneration.current) setWorkspaceLoading(false);
      }
    },
    [t]
  );
  useEffect(() => {
    void loadWorkspaces();
  }, [loadWorkspaces]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    contextDBRequest<Page<ContextDBUser>>(
      `/users?limit=${LIMIT}&offset=${offset}${query ? `&q=${encodeURIComponent(query)}` : ""}`,
      { signal: controller.signal }
    )
      .then((page) => {
        if (controller.signal.aborted) return;
        if (offset > 0 && offset >= page.total) {
          setOffset(Math.max(0, Math.ceil(page.total / LIMIT) * LIMIT - LIMIT));
          return;
        }
        setUsers(page);
        setSelectedUser((previous) =>
          previous
            ? (page.items.find((item) => item.user_id === previous.user_id) ?? previous)
            : null
        );
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset, query, refresh]);
  useEffect(() => {
    if (!selectedUser) return;
    const controller = new AbortController();
    setKeysLoading(true);
    contextDBRequest<Page<ContextDBKey>>(
      `/users/${selectedUser.user_id}/keys?limit=${LIMIT}&offset=${keyOffset}`,
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
        if (!controller.signal.aborted) setError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setKeysLoading(false);
      });
    return () => controller.abort();
  }, [selectedUser, keyOffset, keyRefresh]);
  // Resolve selected IDs independently of the first picker page. An unloaded ID
  // is not a deleted space. Bound lookups to four concurrent requests.
  useEffect(() => {
    const ids = [
      ...new Set([
        ...Object.keys(grants),
        ...keys.items.flatMap((key) =>
          key.authorization.mode === "selected"
            ? key.authorization.workspaces.map((space) => space.workspace_id)
            : []
        ),
      ]),
    ].filter((id) => workspaceCache.current[id] === undefined);
    if (!ids.length) return;
    const controller = new AbortController();
    let next = 0;
    const resolve = async () => {
      while (next < ids.length && !controller.signal.aborted) {
        const id = ids[next++];
        try {
          const reference = keys.items
            .flatMap((key) =>
              key.authorization.mode === "selected" ? key.authorization.workspaces : []
            )
            .find((grant) => grant.workspace_id === id);
          if (!reference?.bank_id) continue;
          const workspace = await contextDBRequest<ContextDBWorkspace>(
            `/workspaces/${encodeURIComponent(reference.bank_id)}`,
            { signal: controller.signal }
          );
          if (!controller.signal.aborted) {
            // A reused name must never make the editor select a successor bank.
            workspaceCache.current = {
              ...workspaceCache.current,
              [id]: workspace.workspace_id === id ? workspace : null,
            };
            setWorkspaceMap(workspaceCache.current);
          }
        } catch (err) {
          if (controller.signal.aborted) return;
          // Only a 404 establishes absence. Network errors leave grants intact.
          if (err && typeof err === "object" && "status" in err && err.status === 404) {
            workspaceCache.current = { ...workspaceCache.current, [id]: null };
            setWorkspaceMap(workspaceCache.current);
          } else setError(err instanceof Error ? err.message : t("failed"));
        }
      }
    };
    void Promise.all(Array.from({ length: Math.min(4, ids.length) }, resolve));
    return () => controller.abort();
  }, [grants, keys, t]);
  useEffect(() => {
    if (!secret) return;
    const clear = () => setSecret("");
    const hidden = () => {
      if (document.hidden) clear();
    };
    const timer = setTimeout(clear, 60000);
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("pagehide", clear);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("pagehide", clear);
    };
  }, [secret]);
  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("failed"));
    } finally {
      setBusy(false);
    }
  };
  const editUser = (user: ContextDBUser | null) => {
    setError("");
    setEditingUser(user);
    setName(user?.name ?? "");
    setUserOpen(true);
  };
  const toggleUser = (user: ContextDBUser) => {
    setSelectedUser(selectedUser?.user_id === user.user_id ? null : user);
    setKeyOffset(0);
    setKeys(emptyPage());
    setKeysLoaded(false);
  };
  const editKey = (key: ContextDBKey | null) => {
    setError("");
    // Refresh existing grants independently of cached picker pages: a space may
    // have been deleted since this member's keys were first expanded.
    if (key?.authorization.mode === "selected") {
      const current = { ...workspaceCache.current };
      for (const grant of key.authorization.workspaces) delete current[grant.workspace_id];
      workspaceCache.current = current;
      setWorkspaceMap(current);
    }
    setEditingKey(key);
    setKeyName(key?.name ?? "");
    setAccess(key?.authorization.mode ?? "selected");
    setGrants(
      key?.authorization.mode === "selected"
        ? Object.fromEntries(
            key.authorization.workspaces.map((item) => [item.workspace_id, item.permission])
          )
        : {}
    );
    setPermission(
      key?.authorization.mode === "all"
        ? key.authorization.permission
        : key?.authorization.mode === "selected" &&
            key.authorization.workspaces.some((item) => item.permission === "read")
          ? "read"
          : "read_write"
    );
    setKeyOpen(true);
    void loadWorkspaces();
  };
  const workspaceName = (id: string) => workspaceMap[id]?.name ?? id;
  const displayKey = (key: ContextDBKey) =>
    key.display_key ?? t("historicalKey", { id: key.key_id });
  const draftAuthorization: KeyAuthorization =
    access === "all"
      ? { mode: "all", permission }
      : {
          mode: "selected",
          workspaces: Object.entries(grants).map(([workspace_id, permission]) => ({
            workspace_id,
            bank_id:
              workspaceMap[workspace_id]?.bank_id ??
              (editingKey?.authorization.mode === "selected"
                ? editingKey.authorization.workspaces.find(
                    (item) => item.workspace_id === workspace_id
                  )?.bank_id
                : undefined) ??
              "",
            permission,
          })),
        };
  const authorization: KeyAuthorizationInput =
    draftAuthorization.mode === "all"
      ? draftAuthorization
      : {
          mode: "selected",
          workspaces: draftAuthorization.workspaces.map(
            ({ bank_id, workspace_id, permission }) => ({
              bank_id,
              workspace_id,
              permission,
            })
          ),
        };
  // Compare immutable identities locally; converting to wire names first would
  // hide an explicit selection of a successor with the same name and permission.
  const authorizationChanged =
    !editingKey ||
    authorizationSnapshot(draftAuthorization) !== authorizationSnapshot(editingKey.authorization);
  const pickerIds = [
    ...new Set([
      ...workspaceIds.filter((id) => workspaceMap[id]?.state === "active"),
      ...Object.keys(grants),
    ]),
  ];
  const unavailableGrant = Object.keys(grants).some(
    (id) => !workspaceMap[id] || workspaceMap[id]?.state !== "active"
  );
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
  const keyTable = (user: ContextDBUser) => (
    <div className="space-y-3 rounded bg-muted/20 p-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{t("userKeys", { name: user.name })}</h2>
        <div className="flex gap-2">
          <Button
            variant="outline"
            disabled={keysLoading || busy}
            onClick={() => setKeyRefresh((value) => value + 1)}
          >
            {t("refresh")}
          </Button>
          <Button disabled={busy || user.status !== "active"} onClick={() => editKey(null)}>
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
                <td className="py-3">{key.name}</td>
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
                          {workspaceName(space.workspace_id)} ·{" "}
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
                      onClick={() => editKey(key)}
                    >
                      {t("edit")}
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      disabled={busy}
                      onClick={() => setRevokingKey(key)}
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
    </div>
  );
  return (
    <div className="mx-auto max-w-7xl space-y-5 p-6">
      <div className="flex justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
        <Button disabled={busy} onClick={() => editUser(null)}>
          {t("createUser")}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Input
          aria-label={t("searchUsers")}
          value={query}
          maxLength={128}
          onChange={(event) => {
            setQuery(event.target.value);
            setOffset(0);
            setSelectedUser(null);
          }}
        />
        <Button
          variant="outline"
          disabled={loading}
          onClick={() => setRefresh((value) => value + 1)}
        >
          {t("refresh")}
        </Button>
      </div>
      <h2>
        {t("users")} ({users.total})
      </h2>
      {loading ? (
        <p>{t("loading")}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left">
                <th></th>
                <th>{t("name")}</th>
                <th>{t("status")}</th>
                <th>{t("createdAt")}</th>
                <th>{t("actions")}</th>
              </tr>
            </thead>
            <tbody>
              {users.items.map((user) => (
                <Fragment key={user.user_id}>
                  <tr className="border-b">
                    <td>
                      <Button
                        variant="ghost"
                        aria-label={t("keys")}
                        aria-expanded={selectedUser?.user_id === user.user_id}
                        onClick={() => toggleUser(user)}
                      >
                        {selectedUser?.user_id === user.user_id ? "▾" : "▸"}
                      </Button>
                    </td>
                    <td className="py-3 font-medium" title={user.user_id}>
                      {user.name}
                    </td>
                    <td>{t(user.status)}</td>
                    <td>{date(user.created_at)}</td>
                    <td>
                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" onClick={() => toggleUser(user)}>
                          {t("keys")}
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button variant="outline" size="sm" disabled={busy}>
                              {t("more")}
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent>
                            <DropdownMenuItem onSelect={() => editUser(user)}>
                              {t("editUser")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() =>
                                void run(async () => {
                                  const saved = await contextDBRequest<ContextDBUser>(
                                    `/users/${user.user_id}`,
                                    {
                                      method: "PATCH",
                                      version: user.version,
                                      body: {
                                        status: user.status === "active" ? "disabled" : "active",
                                      },
                                    }
                                  );
                                  if (selectedUser?.user_id === saved.user_id)
                                    setSelectedUser(saved);
                                  setRefresh((value) => value + 1);
                                })
                              }
                            >
                              {t(user.status === "active" ? "disableUser" : "enableUser")}
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => setDeletingUser(user)}>
                              {t("delete")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                  {selectedUser?.user_id === user.user_id && (
                    <tr>
                      <td colSpan={5}>{keyTable(user)}</td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          {!users.items.length && <p>{t("empty")}</p>}
        </div>
      )}
      {pager(
        users,
        offset,
        (value) => {
          setOffset(value);
          setSelectedUser(null);
        },
        loading
      )}
      <Dialog
        open={userOpen}
        onOpenChange={(open) => {
          if (!busy) setUserOpen(open);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingUser ? t("editUser") : t("createUser")}</DialogTitle>
            <DialogDescription>{t("userHelp")}</DialogDescription>
          </DialogHeader>
          <Label htmlFor="user-name">{t("name")}</Label>
          <Input
            id="user-name"
            value={name}
            maxLength={64}
            onChange={(event) => setName(event.target.value)}
          />
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setUserOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={busy || !name.trim()}
              onClick={() =>
                void run(async () => {
                  const saved = await contextDBRequest<ContextDBUser>(
                    editingUser ? `/users/${editingUser.user_id}` : "/users",
                    {
                      method: editingUser ? "PATCH" : "POST",
                      body: { name: name.trim() },
                      version: editingUser?.version,
                    }
                  );
                  setUserOpen(false);
                  setSelectedUser(saved);
                  setKeyOffset(0);
                  setKeys(emptyPage());
                  setKeysLoaded(false);
                  if (!editingUser) {
                    /* Search the name and locate the exact ID; creation order is not a pagination contract. */ setQuery(
                      saved.name
                    );
                    const page = await contextDBRequest<Page<ContextDBUser>>(
                      `/users?limit=100&offset=0&q=${encodeURIComponent(saved.name)}`
                    );
                    let items = page.items;
                    let start = 0;
                    let index = items.findIndex((item) => item.user_id === saved.user_id);
                    while (index < 0 && start + items.length < page.total) {
                      start += items.length;
                      const next = await contextDBRequest<Page<ContextDBUser>>(
                        `/users?limit=100&offset=${start}&q=${encodeURIComponent(saved.name)}`
                      );
                      if (!next.items.length) break;
                      items = next.items;
                      index = items.findIndex((item) => item.user_id === saved.user_id);
                    }
                    setOffset(index < 0 ? 0 : Math.floor((start + index) / LIMIT) * LIMIT);
                  }
                  setRefresh((value) => value + 1);
                })
              }
            >
              {busy ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={keyOpen}
        onOpenChange={(open) => {
          if (!busy) setKeyOpen(open);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingKey ? t("editKey") : t("createKey")}</DialogTitle>
            <DialogDescription>
              {selectedUser?.name}
              {editingKey ? ` · ${displayKey(editingKey)}` : ""}. {t("grantHelp")}
            </DialogDescription>
          </DialogHeader>
          <Label htmlFor="key-name">{t("name")}</Label>
          <Input
            id="key-name"
            value={keyName}
            maxLength={64}
            onChange={(event) => setKeyName(event.target.value)}
          />
          <Label htmlFor="key-access">{t("spaces")}</Label>
          <select
            id="key-access"
            className="rounded border bg-background p-2"
            value={access}
            onChange={(event) => {
              const mode = event.target.value as "all" | "selected";
              // Carry a deliberately selected read-only permission into the
              // uniform range instead of silently applying creation defaults.
              if (mode === "all" && Object.values(grants).includes("read")) setPermission("read");
              setAccess(mode);
            }}
          >
            <option value="selected">{t("selectedSpaces")}</option>
            <option value="all">{t("allSpaces")}</option>
          </select>
          {access === "selected" ? (
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {pickerIds.map((id) => (
                <div className="flex items-center gap-2" key={id}>
                  <label className="flex flex-1 items-center gap-2">
                    <Checkbox
                      checked={Object.hasOwn(grants, id)}
                      onCheckedChange={(checked) =>
                        setGrants((previous) => {
                          const next = { ...previous };
                          if (checked) next[id] = "read_write";
                          else delete next[id];
                          return next;
                        })
                      }
                    />
                    {workspaceName(id)}
                    {workspaceMap[id] === null ||
                    (workspaceMap[id] && workspaceMap[id]?.state !== "active")
                      ? ` (${t("unavailable")})`
                      : ""}
                  </label>
                  {Object.hasOwn(grants, id) && (
                    <select
                      aria-label={`${workspaceName(id)} ${t("permission")}`}
                      className="rounded border bg-background p-1"
                      value={grants[id]}
                      onChange={(event) =>
                        setGrants((previous) => ({
                          ...previous,
                          [id]: event.target.value as KeyPermission,
                        }))
                      }
                    >
                      <option value="read_write">{t("readWrite")}</option>
                      <option value="read">{t("readOnly")}</option>
                    </select>
                  )}
                </div>
              ))}
              {workspaceLoading && <p>{t("loading")}</p>}
              {workspaceOffset.current < workspaceTotal && (
                <Button
                  variant="outline"
                  disabled={workspaceLoading}
                  onClick={() => void loadWorkspaces(true)}
                >
                  {t("moreWorkspaces")}
                </Button>
              )}
              {!workspaceLoading && !pickerIds.length && <p>{t("createWorkspaceFirst")}</p>}
              {unavailableGrant && <p>{t("unavailableHelp")}</p>}
            </div>
          ) : (
            <>
              <Label htmlFor="key-permission">{t("permission")}</Label>
              <select
                id="key-permission"
                value={permission}
                className="rounded border bg-background p-2"
                onChange={(event) => setPermission(event.target.value as KeyPermission)}
              >
                <option value="read_write">{t("readWrite")}</option>
                <option value="read">{t("readOnly")}</option>
              </select>
            </>
          )}
          <p className="text-sm text-muted-foreground">
            {t("readOnlyHelp")} {t("readWriteHelp")}
          </p>
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setKeyOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={
                busy ||
                !selectedUser ||
                !keyName.trim() ||
                (authorizationChanged &&
                  access === "selected" &&
                  (!Object.keys(grants).length || unavailableGrant))
              }
              onClick={() =>
                void run(async () => {
                  if (!selectedUser) return;
                  const body = editingKey
                    ? {
                        ...(keyName.trim() !== editingKey.name ? { name: keyName.trim() } : {}),
                        ...(authorizationChanged ? { authorization } : {}),
                      }
                    : { name: keyName.trim(), authorization };
                  if (!Object.keys(body).length) {
                    setKeyOpen(false);
                    return;
                  }
                  const result = await contextDBRequest<ContextDBKey & { secret?: string }>(
                    `/users/${selectedUser.user_id}/keys${editingKey ? `/${editingKey.key_id}` : ""}`,
                    { method: editingKey ? "PATCH" : "POST", version: editingKey?.version, body }
                  );
                  setKeyOpen(false);
                  setKeyRefresh((value) => value + 1);
                  if (result.secret) setSecret(result.secret);
                })
              }
            >
              {busy ? t("saving") : t("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!deletingUser}
        onOpenChange={(open) => {
          if (!open && !busy) setDeletingUser(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("deleteUserTitle")}</DialogTitle>
            <DialogDescription>
              {t("deleteUserWarning", { name: deletingUser?.name ?? "" })}
            </DialogDescription>
          </DialogHeader>
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setDeletingUser(null)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  if (!deletingUser) return;
                  await contextDBRequest(`/users/${deletingUser.user_id}`, { method: "DELETE" });
                  if (selectedUser?.user_id === deletingUser.user_id) setSelectedUser(null);
                  setDeletingUser(null);
                  setRefresh((value) => value + 1);
                })
              }
            >
              {t("delete")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!revokingKey}
        onOpenChange={(open) => {
          if (!open && !busy) setRevokingKey(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("revokeTitle")}</DialogTitle>
            <DialogDescription>
              {selectedUser?.name} · {revokingKey?.name} ·{" "}
              {revokingKey ? displayKey(revokingKey) : ""}. {t("revokeWarning")}
            </DialogDescription>
          </DialogHeader>
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setRevokingKey(null)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  if (!selectedUser || !revokingKey) return;
                  await contextDBRequest(
                    `/users/${selectedUser.user_id}/keys/${revokingKey.key_id}`,
                    { method: "DELETE" }
                  );
                  setRevokingKey(null);
                  setKeyRefresh((value) => value + 1);
                })
              }
            >
              {t("revoke")}
            </Button>
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
