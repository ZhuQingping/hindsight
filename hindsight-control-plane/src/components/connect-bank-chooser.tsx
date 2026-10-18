"use client";

import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useBank } from "@/lib/bank-context";
import { Button } from "@/components/ui/button";

export function ConnectBankChooser() {
  const t = useTranslations("resourcePages");
  const tCommon = useTranslations("common");
  const {
    bankInfos,
    banksLoading,
    banksLoadingMore,
    bankSearch,
    totalBanks,
    hasMoreBanks,
    searchBanks,
    loadMoreBanks,
  } = useBank();

  return (
    <section className="rounded-xl border border-border bg-card p-5 md:p-6">
      <h2 className="text-lg font-semibold">{t("chooseBank")}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{t("chooseBankDescription")}</p>
      <input
        type="search"
        value={bankSearch}
        onChange={(event) => {
          void searchBanks(event.target.value);
        }}
        placeholder={t("searchBanks")}
        aria-label={t("searchBanks")}
        className="mt-4 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <div className="mt-4 grid gap-2 sm:grid-cols-2">
        {bankInfos.map((bank) => (
          <Link
            key={bank.bank_id}
            href={`/connect?bank_id=${encodeURIComponent(bank.bank_id)}`}
            className="rounded-lg border border-border p-3 text-sm transition-colors hover:border-primary/40 hover:bg-accent"
          >
            <span className="block font-medium">
              {bank.display_alias || bank.name || bank.bank_id}
            </span>
            <span className="block truncate font-mono text-xs text-muted-foreground">
              {bank.bank_id}
            </span>
          </Link>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p role="status" className="text-sm text-muted-foreground">
          {t("showingWorkspaces", { shown: bankInfos.length, total: totalBanks })}
        </p>
        {hasMoreBanks && (
          <Button
            variant="outline"
            onClick={() => void loadMoreBanks()}
            disabled={banksLoading || banksLoadingMore}
          >
            {banksLoadingMore ? tCommon("loading") : t("loadMore")}
          </Button>
        )}
      </div>
      {!banksLoading && bankInfos.length === 0 && (
        <p className="mt-4 text-sm text-muted-foreground">{t("noBanks")}</p>
      )}
    </section>
  );
}
