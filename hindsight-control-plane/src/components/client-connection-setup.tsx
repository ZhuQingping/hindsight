"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ConnectionCode } from "@/components/connection-code";
import type { CustomerConnection } from "@/lib/customer-connection";
import {
  codingClients,
  connectionExample,
  type ConnectionClient,
  type ConnectionTerminal,
} from "@/lib/connection-examples";

const agentClients = [
  ...codingClients,
  { id: "openclaw", name: "OpenClaw" },
  { id: "hermes", name: "Hermes Agent" },
] as const;
const developerClients = [
  { id: "python", name: "Python SDK" },
  { id: "node", name: "Node.js SDK" },
  { id: "rest", name: "REST API" },
  { id: "mcp", name: "MCP" },
] as const;
const terminals = [
  { id: "powershell", name: "PowerShell" },
  { id: "cmd", name: "CMD" },
  { id: "bash", name: "macOS / Linux" },
] as const;

export function ClientConnectionSetup({
  bankId,
  connection,
}: {
  bankId: string;
  connection: CustomerConnection;
}) {
  const t = useTranslations("connectionSetup");
  const [group, setGroup] = useState<"agents" | "development">("agents");
  const [agentClient, setAgentClient] = useState<ConnectionClient>("claude-code");
  const [developerClient, setDeveloperClient] = useState<ConnectionClient>("python");
  const [terminal, setTerminal] = useState<ConnectionTerminal>("powershell");
  const client = group === "agents" ? agentClient : developerClient;
  const clients = group === "agents" ? agentClients : developerClients;
  const name = clients.find((item) => item.id === client)!.name;
  const isCoding = codingClients.some((item) => item.id === client);
  const isSdk = client === "python" || client === "node";
  const example = connectionExample(client, terminal, bankId, connection, t("exampleQuery"));
  const stepClass = "min-w-0 space-y-2 border-t border-border pt-5";
  const choiceClass =
    "rounded-md px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring";

  return (
    <section
      aria-label={t("setupLabel")}
      className="min-w-0 rounded-xl border border-border bg-card p-5 md:p-6"
    >
      <div className="flex flex-wrap gap-2" aria-label={t("categoryLabel")} role="group">
        {(["agents", "development"] as const).map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={group === value}
            onClick={() => setGroup(value)}
            className={`${choiceClass} ${group === value ? "bg-primary text-primary-foreground" : "bg-muted/50 text-muted-foreground hover:bg-accent"}`}
          >
            {t(value)}
          </button>
        ))}
      </div>

      <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
        <div className="w-full sm:max-w-xs">
          <label htmlFor="connection-client" className="mb-2 block text-sm font-medium">
            {t("clientLabel")}
          </label>
          <select
            id="connection-client"
            value={client}
            onChange={(event) => {
              const selected = clients.find((item) => item.id === event.target.value);
              if (selected) (group === "agents" ? setAgentClient : setDeveloperClient)(selected.id);
            }}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {clients.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
        {client !== "mcp" && (
          <div>
            <p className="mb-2 text-sm font-medium">{t("terminalLabel")}</p>
            <div
              role="group"
              aria-label={t("terminalLabel")}
              className="flex flex-wrap gap-1 rounded-lg bg-muted/50 p-1"
            >
              {terminals.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={terminal === item.id}
                  onClick={() => setTerminal(item.id)}
                  className={`${choiceClass} ${terminal === item.id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                >
                  {item.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="mt-6 space-y-5">
        <div>
          <h2 className="text-xl font-semibold">{name}</h2>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            {t(`descriptions.${isCoding ? "coding" : client}`)}
          </p>
          {client !== "mcp" && (
            <p className="mt-2 text-sm text-muted-foreground">{t("credentials")}</p>
          )}
          {(isCoding || isSdk) && (
            <p className="mt-2 text-sm text-muted-foreground">
              {t(`requirements.${isCoding ? "coding" : client}`)}
            </p>
          )}
          {(client === "openclaw" || client === "hermes") && (
            <p className="mt-2 text-sm text-muted-foreground">{t(`requirements.${client}`)}</p>
          )}
        </div>

        {example.unavailable ? (
          <p
            role="status"
            className="rounded-lg border border-border bg-muted/40 p-4 text-sm leading-6"
          >
            {t(example.unavailable)}
          </p>
        ) : (
          <>
            {example.install && (
              <div className={stepClass}>
                <h3 className="font-medium">
                  {t(
                    client === "hermes"
                      ? "hermesInstallTitle"
                      : isCoding
                        ? "npmInstallTitle"
                        : "installTitle"
                  )}
                </h3>
                {isCoding && (
                  <p className="text-sm leading-6 text-muted-foreground">{t("npmHelp")}</p>
                )}
                {isCoding && (
                  <details className="text-sm text-muted-foreground">
                    <summary className="cursor-pointer">{t("installScopeTitle")}</summary>
                    <p className="mt-2 leading-6">{t("installScope")}</p>
                  </details>
                )}
                {client === "hermes" && (
                  <p className="text-sm leading-6 text-muted-foreground">{t("hermesExtract")}</p>
                )}
                {example.downloadUrl && (
                  <a
                    href={example.downloadUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block text-sm font-medium text-primary hover:underline"
                  >
                    {t("downloadPackage")}
                  </a>
                )}
                <ConnectionCode key={example.install} code={example.install} />
                {isCoding && (
                  <div className="mt-4 space-y-2 text-sm leading-6 text-muted-foreground">
                    <p>
                      {t("endpointHelp", { endpoint: connection.apiUrl ?? t("apiUnavailable") })}
                    </p>
                    <p>{t("bankHelp", { bankId })}</p>
                    <p>{t("projectHelp")}</p>
                  </div>
                )}
              </div>
            )}

            {example.configuration && (
              <div className={stepClass}>
                <h3 className="font-medium">
                  {t(client === "mcp" ? "mcpConfigTitle" : "configureTitle")}
                </h3>
                <p className="text-sm leading-6 text-muted-foreground">
                  {t(
                    client === "mcp"
                      ? "mcpConfigHelp"
                      : client === "hermes"
                        ? "hermesConfigHelp"
                        : "openclawConfigHelp"
                  )}
                </p>
                <ConnectionCode key={example.configuration} code={example.configuration} />
              </div>
            )}

            {example.code && (
              <div className={stepClass}>
                <h3 className="font-medium">{t(isSdk ? "codeTitle" : "readonlyTitle")}</h3>
                {isSdk && (
                  <p className="text-sm text-muted-foreground">
                    {t("saveExample", {
                      filename:
                        client === "python" ? "contextbase-example.py" : "contextbase-example.mjs",
                    })}
                  </p>
                )}
                <ConnectionCode key={example.code} code={example.code} />
                {example.run && <ConnectionCode key={example.run} code={example.run} />}
              </div>
            )}

            <div className={stepClass}>
              <h3 className="font-medium">{t("verifyTitle")}</h3>
              {isCoding ? (
                <>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {t(
                      client === "claude-code" || client === "codex"
                        ? "verifyMcpAgent"
                        : "verifyAgent"
                    )}
                  </p>
                  <ConnectionCode code={t("diagnosePrompt")} />
                  <p className="text-sm leading-6 text-muted-foreground">
                    {t("diagnoseExpected", { bankId, harness: client })}
                  </p>
                  {(client === "opencode" || client === "opencode2") && (
                    <p className="text-sm text-muted-foreground">{t("openCodeShared")}</p>
                  )}
                </>
              ) : (
                <p className="text-sm leading-6 text-muted-foreground">
                  {t(`verify.${isSdk ? "sdk" : client}`)}
                </p>
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
