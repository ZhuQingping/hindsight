"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
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
    <div className="relative mt-4 min-w-0 max-w-full">
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
