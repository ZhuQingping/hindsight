"use client";

import { createContext, useContext, type ReactNode } from "react";

const AdvancedSettings = createContext(false);

export function SettingsVisibilityProvider({
  showAdvanced,
  children,
}: {
  showAdvanced: boolean;
  children: ReactNode;
}) {
  return <AdvancedSettings.Provider value={showAdvanced}>{children}</AdvancedSettings.Provider>;
}

export function useAdvancedSettings() {
  return useContext(AdvancedSettings);
}
