import { getTranslations } from "next-intl/server";
import { headers } from "next/headers";
import { Link } from "@/i18n/navigation";
import { ConnectBankChooser } from "@/components/connect-bank-chooser";
import { ClientConnectionSetup } from "@/components/client-connection-setup";
import { ResourcePageShell } from "@/components/resource-page-shell";
import { customerConnection } from "@/lib/customer-connection";
import { requestUiOrigin } from "@/lib/public-origin";

export default async function ConnectPage({
  searchParams,
}: {
  searchParams: Promise<{ bank_id?: string | string[] }>;
}) {
  const t = await getTranslations("resourcePages");
  const rawBankId = (await searchParams).bank_id;
  const bankId = typeof rawBankId === "string" && rawBankId ? rawBankId : null;
  // Resolve per request: different EIPs/aliases must never share a cached endpoint.
  const uiOrigin = requestUiOrigin(await headers());
  const connection = customerConnection(bankId ?? "", { uiOrigin });

  return (
    <ResourcePageShell bankId={bankId}>
      <header className="space-y-3">
        <Link href="/dashboard" className="text-sm text-primary hover:underline">
          {t("backToBanks")}
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight">{t("connectTitle")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("connectIntro")}</p>
      </header>

      {!bankId ? (
        <ConnectBankChooser />
      ) : (
        <>
          <section className="rounded-xl border border-border bg-card p-5 md:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t("selectedBank")}
                </p>
                <p className="mt-1 break-all font-mono text-sm">{bankId}</p>
              </div>
              <Link href="/connect" className="text-sm font-medium text-primary hover:underline">
                {t("changeBank")}
              </Link>
            </div>
          </section>

          <ClientConnectionSetup key={bankId} bankId={bankId} connection={connection} />
        </>
      )}

      <Link
        href={bankId ? `/guide?bank_id=${encodeURIComponent(bankId)}` : "/guide"}
        className="text-sm font-medium text-primary hover:underline"
      >
        {t("guideTitle")} →
      </Link>
    </ResourcePageShell>
  );
}
