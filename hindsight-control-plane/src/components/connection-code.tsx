"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

export function ConnectionCode({ code }: { code: string }) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);

  return (
    <div className="relative mt-4 min-w-0 max-w-full">
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
          } catch {
            toast.error(t("error"));
          }
        }}
        className="absolute right-2 top-2 rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
      >
        {copied ? t("copied") : t("copy")}
      </button>
      <pre className="max-w-full overflow-x-auto rounded-lg border border-border bg-muted/50 px-4 pb-4 pt-12 text-xs leading-6 text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}
