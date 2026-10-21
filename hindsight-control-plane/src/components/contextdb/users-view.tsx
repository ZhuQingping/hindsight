"use client";

import { Fragment, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
import { DirectoryPagination } from "./directory-pagination";
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
  createContextDBUser,
  contextDBWriteOutcome,
  type ContextDBUser,
  type Page,
} from "@/lib/contextdb-api";

import { restoreDialogFocus } from "./dialog-focus";

const LIMIT = 20;
const emptyPage = <T,>(): Page<T> => ({ items: [], total: 0, limit: LIMIT, offset: 0 });

export function ContextDBUsersView() {
  const t = useTranslations("contextDB");
  const locale = useLocale();
  const date = (value: string | null) => (value ? new Date(value).toLocaleString(locale) : "—");
  const [users, setUsers] = useState<Page<ContextDBUser>>(emptyPage);
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [readError, setReadError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const createButton = useRef<HTMLButtonElement>(null);
  const dialogTrigger = useRef<HTMLButtonElement | null>(null);
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
        setLoaded(true);
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
    setSelectedUserId(selectedUserId === user.user_id ? null : user.user_id);
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
  return (
    <div className="w-full min-w-0 space-y-5 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{t("title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("subtitle")}</p>
        </div>
        <Button
          ref={createButton}
          disabled={busy}
          onClick={(event) => {
            dialogTrigger.current = event.currentTarget;
            editUser(null);
          }}
        >
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
          placeholder={t("searchUsers")}
          value={query}
          maxLength={128}
          onChange={(event) => {
            setQuery(event.target.value);
            setOffset(0);
            setSelectedUserId(null);
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
        {t("users")} ({!loading && !readError ? users.total : "—"})
      </h2>
      {notice && <p role="status">{notice}</p>}
      {userOutcome && !userOpen && !deletingUser && (
        <Button disabled={busy} onClick={refreshUserRecords}>
          {t("checkUsers")}
        </Button>
      )}
      {loading ? (
        <p>{t("loading")}</p>
      ) : readError ? (
        <p>{t(loaded ? "staleResults" : "readUnavailable")}</p>
      ) : (
        <div className="overflow-x-auto">
          <Table className="w-full text-sm">
            <TableHeader>
              <TableRow>
                <TableHead>{t("name")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("status")}</TableHead>
                <TableHead className="hidden md:table-cell">{t("createdAt")}</TableHead>
                <TableHead className="w-[180px] md:w-auto">{t("actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.items.map((user) => (
                <Fragment key={user.user_id}>
                  <TableRow>
                    <TableCell
                      className="min-w-[100px] break-words py-3 font-medium [overflow-wrap:anywhere]"
                      title={user.user_id}
                    >
                      {user.name}
                      <span className="mt-1 block text-xs font-normal text-muted-foreground md:hidden">
                        {t(user.status)}
                      </span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">{t(user.status)}</TableCell>
                    <TableCell className="hidden md:table-cell">{date(user.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="px-2"
                          aria-label={t("keys")}
                          aria-expanded={selectedUserId === user.user_id}
                          onClick={() => toggleUser(user)}
                        >
                          {selectedUserId === user.user_id ? (
                            <ChevronDown className="h-4 w-4" />
                          ) : (
                            <ChevronRight className="h-4 w-4" />
                          )}
                          {t("keyListTitle")}
                        </Button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              onFocus={(event) => {
                                dialogTrigger.current = event.currentTarget;
                              }}
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
                                  await contextDBRequest<ContextDBUser>(`/users/${user.user_id}`, {
                                    method: "PATCH",
                                    version: user.version,
                                    signal,
                                    body: {
                                      status: user.status === "active" ? "disabled" : "active",
                                    },
                                  });
                                  if (signal.aborted) return;
                                  setRefresh((value) => value + 1);
                                }, user.user_id)
                              }
                            >
                              {t(user.status === "active" ? "disableUser" : "enableUser")}
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-destructive focus:text-destructive"
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
                    </TableCell>
                  </TableRow>
                  {selectedUserId === user.user_id && (
                    <TableRow>
                      <TableCell colSpan={4}>
                        <ContextDBUserKeysPanel key={user.user_id} user={user} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
          {!users.items.length && <p>{t(query ? "noMatches" : "empty")}</p>}
        </div>
      )}
      {!loading && !readError && (
        <DirectoryPagination
          total={users.total}
          count={users.items.length}
          offset={offset}
          limit={LIMIT}
          loading={loading}
          onChange={(value) => {
            setOffset(value);
            setSelectedUserId(null);
          }}
        />
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
        <DialogContent
          className="w-[calc(100%-2rem)]"
          onCloseAutoFocus={(event) =>
            restoreDialogFocus(event, dialogTrigger.current, createButton.current)
          }
        >
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
                    const saved = editingUser
                      ? await contextDBRequest<ContextDBUser>(`/users/${editingUser.user_id}`, {
                          method: "PATCH",
                          body: { name: name.trim() },
                          version: editingUser.version,
                          signal,
                        })
                      : await createContextDBUser({ name: name.trim() }, signal);
                    if (signal.aborted) return;
                    setUserOpen(false);
                    setSelectedUserId(null);
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
        <DialogContent
          className="w-[calc(100%-2rem)]"
          onCloseAutoFocus={(event) =>
            restoreDialogFocus(event, dialogTrigger.current, createButton.current)
          }
        >
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
                    setSelectedUserId((current) =>
                      current === deletingUser.user_id ? null : current
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
