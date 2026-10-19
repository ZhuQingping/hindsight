import { getTranslations } from "next-intl/server";
import { Link } from "@/i18n/navigation";
import { ConnectBankChooser } from "@/components/connect-bank-chooser";
import { ConnectionCode } from "@/components/connection-code";
import { ResourcePageShell } from "@/components/resource-page-shell";

export default async function ConnectPage({
  searchParams,
}: {
  searchParams: Promise<{ bank_id?: string | string[] }>;
}) {
  const t = await getTranslations("resourcePages");
  const rawBankId = (await searchParams).bank_id;
  const bankId = typeof rawBankId === "string" && rawBankId ? rawBankId : null;
  const python = bankId
    ? `from hindsight_client import Hindsight\nimport os\n\nclient = Hindsight(\n    base_url=os.environ["CONTEXTBASE_API_URL"],\n    api_key=os.environ["CONTEXTBASE_API_KEY"],\n)\nresult = client.recall(${JSON.stringify(bankId)}, "your question")`
    : "";
  const encodedBankId = bankId ? encodeURIComponent(bankId) : "";
  const rest = `curl -H "Authorization: Bearer $CONTEXTBASE_API_KEY" "$CONTEXTBASE_API_URL/v1/default/banks/${encodedBankId}/stats"`;
  const mcp = JSON.stringify(
    {
      mcpServers: {
        contextbase: {
          type: "http",
          url: "<MCP_ENDPOINT>",
          headers: { Authorization: "Bearer <API_KEY>" },
        },
      },
    },
    null,
    2
  );

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

          <section className="rounded-xl border border-border bg-muted/30 p-5 md:p-6">
            <h2 className="text-lg font-semibold">{t("credentialsTitle")}</h2>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{t("credentialsBody")}</p>
            <ConnectionCode
              code={`export CONTEXTBASE_API_URL="<API_BASE_URL>"\nexport CONTEXTBASE_API_KEY="<API_KEY>"`}
            />
          </section>

          <div className="grid min-w-0 gap-4 lg:grid-cols-2">
            <section className="min-w-0 self-start rounded-xl border border-border bg-card p-5 md:p-6">
              <h2 className="text-lg font-semibold">{t("pythonTitle")}</h2>
              <p className="mt-2 text-sm text-muted-foreground">{t("pythonBody")}</p>
              <ConnectionCode code="pip install hindsight-client" />
              <ConnectionCode code={python} />
            </section>
            <div className="min-w-0 space-y-4">
              <section className="min-w-0 rounded-xl border border-border bg-card p-5 md:p-6">
                <h2 className="text-lg font-semibold">{t("restTitle")}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{t("restBody")}</p>
                <ConnectionCode code={rest} />
              </section>
              <section className="min-w-0 rounded-xl border border-border bg-card p-5 md:p-6">
                <h2 className="text-lg font-semibold">{t("mcpTitle")}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{t("mcpEndpointHelp")}</p>
                <p className="mt-2 text-sm text-muted-foreground">{t("mcpBody")}</p>
                <ConnectionCode code={mcp} />
                <p className="mt-3 text-xs text-muted-foreground">{t("mcpAuth")}</p>
              </section>
            </div>
          </div>
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
