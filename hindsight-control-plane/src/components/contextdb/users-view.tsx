"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ContextDBUserKeysPanel } from "@/components/contextdb/user-keys-panel";
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
  contextDBWriteOutcome,
  type ContextDBUser,
  type Page,
} from "@/lib/contextdb-api";

const LIMIT = 20;
const emptyPage = <T,>(): Page<T> => ({ items: [], total: 0, limit: LIMIT, offset: 0 });
const date = (value: string | null) => (value ? new Date(value).toLocaleString() : "—");

export function ContextDBUsersView() {
  const t = useTranslations("contextDB");
  const [users, setUsers] = useState<Page<ContextDBUser>>(emptyPage);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedUser, setSelectedUser] = useState<ContextDBUser | null>(null);
  const [userOpen, setUserOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<ContextDBUser | null>(null);
  const [name, setName] = useState("");
  const [deletingUser, setDeletingUser] = useState<ContextDBUser | null>(null);
  const [userOutcome, setUserOutcome] = useState<"unknown" | "conflict" | null>(null);
  const [attemptTarget, setAttemptTarget] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const userController = useRef<AbortController | null>(null);
  useEffect(() => () => userController.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setReadError("");
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
        if (!controller.signal.aborted) setReadError(err.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [offset, query, refresh]);
  const run = async (
    action: (signal: AbortSignal) => Promise<void>,
    target: string | null = null
  ) => {
    if (busy) return;
    userController.current?.abort();
    const controller = new AbortController();
    userController.current = controller;
    setAttemptTarget(target);
    setUserOutcome(null);
    setBusy(true);
    setError("");
    try {
      await action(controller.signal);
    } catch (err) {
      if (controller.signal.aborted) return;
      setError(err instanceof Error ? err.message : t("failed"));
      const result = contextDBWriteOutcome(err);
      if (result !== "failed") setUserOutcome(result);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  };
  const editUser = (user: ContextDBUser | null) => {
    userController.current?.abort();
    setError("");
    setUserOutcome(null);
    setEditingUser(user);
    setName(user?.name ?? "");
    setUserOpen(true);
  };
  const toggleUser = (user: ContextDBUser) => {
    setSelectedUser(selectedUser?.user_id === user.user_id ? null : user);
  };
  const refreshUserRecords = () => {
    // Refresh is observation, not a claim that an uncertain write finished.
    setNotice(
      t("userRecordsCheck") + (attemptTarget ? ` ${t("userCheckId", { id: attemptTarget })}` : "")
    );
    setQuery(attemptTarget ? "" : name.trim());
    setOffset(0);
    setUserOpen(false);
    setDeletingUser(null);
    setUserOutcome(null);
    setRefresh((value) => value + 1);
  };
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
      {readError && <p role="alert">{readError}</p>}
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
      {notice && <p role="status">{notice}</p>}
      {userOutcome && !userOpen && !deletingUser && (
        <Button disabled={busy} onClick={refreshUserRecords}>
          {t("checkUsers")}
        </Button>
      )}
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
                            <Button
                              variant="outline"
                              size="sm"
                              disabled={
                                busy || (userOutcome !== null && attemptTarget === user.user_id)
                              }
                            >
                              {t("more")}
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent>
                            <DropdownMenuItem onSelect={() => editUser(user)}>
                              {t("editUser")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() =>
                                void run(async (signal) => {
                                  const saved = await contextDBRequest<ContextDBUser>(
                                    `/users/${user.user_id}`,
                                    {
                                      method: "PATCH",
                                      version: user.version,
                                      signal,
                                      body: {
                                        status: user.status === "active" ? "disabled" : "active",
                                      },
                                    }
                                  );
                                  if (signal.aborted) return;
                                  setSelectedUser((current) =>
                                    current?.user_id === saved.user_id ? saved : current
                                  );
                                  setRefresh((value) => value + 1);
                                }, user.user_id)
                              }
                            >
                              {t(user.status === "active" ? "disableUser" : "enableUser")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              onSelect={() => {
                                userController.current?.abort();
                                setError("");
                                setUserOutcome(null);
                                setDeletingUser(user);
                              }}
                            >
                              {t("delete")}
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </td>
                  </tr>
                  {selectedUser?.user_id === user.user_id && (
                    <tr>
                      <td colSpan={5}>
                        <ContextDBUserKeysPanel key={user.user_id} user={user} />
                      </td>
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
          if (!busy) {
            if (!open) {
              userController.current?.abort();
            }
            setUserOpen(open);
          }
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
            disabled={busy || userOutcome !== null}
            onChange={(event) => setName(event.target.value)}
          />
          {error && <p role="alert">{error}</p>}
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                userController.current?.abort();
                setUserOpen(false);
              }}
            >
              {t("cancel")}
            </Button>
            {userOutcome ? (
              <Button disabled={busy} onClick={refreshUserRecords}>
                {t("checkUsers")}
              </Button>
            ) : (
              <Button
                disabled={busy || !name.trim()}
                onClick={() =>
                  void run(async (signal) => {
                    const saved = await contextDBRequest<ContextDBUser>(
                      editingUser ? `/users/${editingUser.user_id}` : "/users",
                      {
                        method: editingUser ? "PATCH" : "POST",
                        body: { name: name.trim() },
                        version: editingUser?.version,
                        signal,
                      }
                    );
                    if (signal.aborted) return;
                    setUserOpen(false);
                    setSelectedUser(null);
                    if (!editingUser) {
                      setQuery(saved.name);
                      setOffset(0);
                      setNotice(t("userCreated", { name: saved.name, id: saved.user_id }));
                    }
                    setRefresh((value) => value + 1);
                  }, editingUser?.user_id ?? null)
                }
              >
                {busy ? t("saving") : t("save")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <Dialog
        open={!!deletingUser}
        onOpenChange={(open) => {
          if (!open && !busy) {
            userController.current?.abort();
            setDeletingUser(null);
          }
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
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                userController.current?.abort();
                setDeletingUser(null);
              }}
            >
              {t("cancel")}
            </Button>
            {userOutcome ? (
              <Button disabled={busy} onClick={refreshUserRecords}>
                {t("checkUsers")}
              </Button>
            ) : (
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() =>
                  void run(async (signal) => {
                    if (!deletingUser) return;
                    await contextDBRequest(`/users/${deletingUser.user_id}`, {
                      method: "DELETE",
                      signal,
                    });
                    if (signal.aborted) return;
                    setSelectedUser((current) =>
                      current?.user_id === deletingUser.user_id ? null : current
                    );
                    setDeletingUser(null);
                    setRefresh((value) => value + 1);
                  }, deletingUser?.user_id ?? null)
                }
              >
                {t("delete")}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
