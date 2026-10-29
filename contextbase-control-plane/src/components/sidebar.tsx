"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useBank } from "@/lib/bank-context";
import { bankRoute } from "@/lib/bank-url";
import {
  Home,
  Search,
  Sparkles,
  Database,
  FileText,
  Users,
  Network,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Menu,
  Settings,
  LayoutGrid,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Link } from "@/i18n/navigation";

type NavItem =
  | "home"
  | "recall"
  | "reflect"
  | "data"
  | "documents"
  | "entities"
  | "knowledge"
  | "profile";

interface SidebarProps {
  currentTab: NavItem;
  onTabChange: (tab: NavItem) => void;
}

export function Sidebar({ currentTab, onTabChange }: SidebarProps) {
  const t = useTranslations("bank.sidebar");
  const tBank = useTranslations("bank");
  const tBrand = useTranslations("brand");
  const tNav = useTranslations("nav.bank");
  const { currentBank, currentBankName } = useBank();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  if (!currentBank) return null;

  const navItems = [
    { id: "home" as NavItem, label: t("home"), icon: Home },
    { id: "data" as NavItem, label: t("memories"), icon: Database, group: tBrand("assets") },
    { id: "documents" as NavItem, label: t("documents"), icon: FileText },
    { id: "knowledge" as NavItem, label: t("knowledge"), icon: Network },
    { id: "entities" as NavItem, label: t("entities"), icon: Users },
    { id: "recall" as NavItem, label: t("recall"), icon: Search, group: tBrand("explore") },
    { id: "reflect" as NavItem, label: t("reflect"), icon: Sparkles },
    {
      id: "profile" as NavItem,
      label: tBank("bankConfiguration"),
      icon: Settings,
    },
  ];
  const activeLabel = navItems.find((item) => item.id === currentTab)?.label ?? t("home");

  return (
    <aside
      className={cn(
        "relative flex shrink-0 flex-col border-b border-border bg-card md:border-b-0 md:border-r",
        isCollapsed ? "md:w-16" : "md:w-56"
      )}
    >
      <div className="hidden border-b border-border px-4 py-5 md:block">
        <Link
          href="/dashboard"
          className="flex items-center gap-2 text-xs font-medium text-muted-foreground hover:text-primary"
          title={tNav("allBanks")}
        >
          <LayoutGrid className="h-4 w-4 shrink-0" />
          {!isCollapsed && <span>{tNav("allBanks")}</span>}
        </Link>
        {!isCollapsed && (
          <p className="mt-4 truncate text-sm font-semibold" title={currentBank}>
            {currentBankName || currentBank}
          </p>
        )}
      </div>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-sm font-medium md:hidden"
        aria-label={`${tBrand("navigation")}: ${activeLabel}`}
        aria-expanded={mobileOpen}
        aria-controls="bank-feature-navigation"
        onClick={() => setMobileOpen((open) => !open)}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Menu className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="truncate">{activeLabel}</span>
        </span>
        <ChevronDown
          className={cn("h-4 w-4 shrink-0 transition-transform", mobileOpen && "rotate-180")}
          aria-hidden="true"
        />
      </button>
      <nav
        id="bank-feature-navigation"
        aria-label={tBrand("navigation")}
        className={cn(
          "min-h-0 flex-1 p-3 md:static md:block md:max-h-none md:overflow-y-auto md:border-b-0 md:shadow-none",
          mobileOpen
            ? "absolute inset-x-0 top-full z-30 max-h-[70dvh] overflow-y-auto border-b border-border bg-card shadow-lg"
            : "hidden"
        )}
      >
        <ul className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = currentTab === item.id;
            return (
              <li
                key={item.id}
                className={item.id === "profile" ? "mt-4 border-t border-border pt-3" : undefined}
              >
                {item.group && (!isCollapsed || mobileOpen) && (
                  <p className="px-3 pb-2 pt-4 text-[11px] font-medium tracking-wide text-muted-foreground">
                    {item.group}
                  </p>
                )}
                <Link
                  href={bankRoute(currentBank, `?view=${item.id}`)}
                  aria-current={isActive ? "page" : undefined}
                  title={item.label}
                  onClick={(e) => {
                    if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) {
                      e.preventDefault();
                      onTabChange(item.id);
                      setMobileOpen(false);
                    }
                  }}
                  className={cn(
                    "flex items-center gap-2.5 whitespace-nowrap rounded-md border border-transparent px-3 py-2.5 text-sm transition-colors focus-visible:outline-2 focus-visible:outline-ring",
                    isActive
                      ? "border-primary/15 bg-primary/8 font-semibold text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                    isCollapsed && "md:justify-center md:px-0"
                  )}
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden="true" />
                  <span className={cn(isCollapsed && "md:hidden")}>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="hidden border-t border-border p-3 md:block">
        <button
          type="button"
          onClick={() => setIsCollapsed((value) => !value)}
          aria-expanded={!isCollapsed}
          aria-label={isCollapsed ? t("expandSidebar") : t("collapseSidebar")}
          className={cn(
            "flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-muted-foreground hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
            isCollapsed && "justify-center px-0"
          )}
        >
          {isCollapsed ? (
            <ChevronRight className="h-4 w-4" />
          ) : (
            <>
              <ChevronLeft className="h-4 w-4" />
              <span>{t("collapse")}</span>
            </>
          )}
        </button>
      </div>
    </aside>
  );
}
