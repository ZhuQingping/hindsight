import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ResourcePageShell } from "@/components/resource-page-shell";
import { bankRoute } from "@/lib/bank-url";

export default async function GuidePage({
  searchParams,
}: {
  searchParams: Promise<{ bank_id?: string | string[] }>;
}) {
  const t = await getTranslations("resourcePages");
  const rawBankId = (await searchParams).bank_id;
  const bankId = typeof rawBankId === "string" && rawBankId ? rawBankId : null;
  const bankHref = (view: string) => (bankId ? bankRoute(bankId, `?view=${view}`) : "/dashboard");

  const sections = [
    { title: t("guideSourcesTitle"), body: t("guideSourcesBody"), href: bankHref("documents") },
    { title: t("guideMemoriesTitle"), body: t("guideMemoriesBody"), href: bankHref("data") },
    { title: t("guideRecallTitle"), body: t("guideRecallBody"), href: bankHref("recall") },
    { title: t("guideReflectTitle"), body: t("guideReflectBody"), href: bankHref("reflect") },
    { title: t("guideKnowledgeTitle"), body: t("guideKnowledgeBody"), href: bankHref("knowledge") },
    { title: t("guideSettingsTitle"), body: t("guideSettingsBody"), href: bankHref("profile") },
  ];

  return (
    <ResourcePageShell bankId={bankId}>
      <header className="space-y-3">
        <Link href="/dashboard" className="text-sm text-primary hover:underline">
          {t("backToBanks")}
        </Link>
        <h1 className="text-3xl font-semibold tracking-tight">{t("guideTitle")}</h1>
        <p className="max-w-2xl text-muted-foreground">{t("guideIntro")}</p>
      </header>
      <div className="grid gap-4 md:grid-cols-2">
        {sections.map((section) => (
          <Link
            key={section.title}
            href={section.href}
            className="rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40 hover:bg-accent"
          >
            <h2 className="font-semibold">{section.title}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{section.body}</p>
            <span className="mt-4 inline-block text-sm font-medium text-primary">
              {bankId ? t("openSection") : t("chooseBank")}
            </span>
          </Link>
        ))}
      </div>
      <section className="rounded-xl border border-border bg-muted/30 p-5">
        <h2 className="font-semibold">{t("guideConnectTitle")}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{t("guideConnectBody")}</p>
        <Link
          href={bankId ? `/connect?bank_id=${encodeURIComponent(bankId)}` : "/connect"}
          className="mt-3 inline-block text-sm font-medium text-primary hover:underline"
        >
          {t("connectTitle")} →
        </Link>
      </section>
    </ResourcePageShell>
  );
}
