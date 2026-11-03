"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";

async function copyCode(code: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(code);
      return;
    } catch {
      // A browser may expose the API but deny clipboard permission.
    }
  }

  // HTTP origins outside localhost lack Clipboard API access. Keep the legacy
  // fallback in the click handler so browsers can use the user's activation.
  const previousFocus = document.activeElement;
  const textarea = document.createElement("textarea");
  textarea.value = code;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.top = "0";
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  try {
    textarea.focus({ preventScroll: true });
    textarea.select();
    if (!document.execCommand("copy")) throw new Error("Clipboard copy failed");
  } finally {
    textarea.remove();
    if (previousFocus instanceof HTMLElement) previousFocus.focus({ preventScroll: true });
  }
}

export function ConnectionCode({ code }: { code: string }) {
  const t = useTranslations("common");
  const [copied, setCopied] = useState(false);

  return (
    <div className="mt-4 flex min-w-0 max-w-full items-start rounded-xl border border-border bg-muted/40 shadow-sm">
      <pre className="m-0 min-w-0 flex-1 overflow-x-auto p-4 font-mono text-xs leading-6 text-foreground sm:text-sm">
        <code>{code}</code>
      </pre>
      <button
        type="button"
        onClick={async () => {
          setCopied(false);
          try {
            await copyCode(code);
            setCopied(true);
          } catch {
            toast.error(t("copyFailed"));
          }
        }}
        className="m-2 inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border bg-background px-2.5 py-2 text-xs font-medium text-muted-foreground shadow-sm transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
      >
        {copied ? <Check aria-hidden="true" size={14} /> : <Copy aria-hidden="true" size={14} />}
        {copied ? t("copied") : t("copy")}
      </button>
    </div>
  );
}
