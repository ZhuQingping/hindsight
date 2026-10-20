"use client";
import { createContext, useContext } from "react";

const ContextDBMode = createContext(false);
export function ContextDBModeProvider({
  enabled,
  children,
}: {
  enabled: boolean;
  children: React.ReactNode;
}) {
  return <ContextDBMode.Provider value={enabled}>{children}</ContextDBMode.Provider>;
}
export function useContextDBMode() {
  return useContext(ContextDBMode);
}
