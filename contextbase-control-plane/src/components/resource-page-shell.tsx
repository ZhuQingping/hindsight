import type { ReactNode } from "react";
import { BankSelector } from "@/components/bank-selector";
import { ResourceBankSelection } from "@/components/resource-bank-selection";

export function ResourcePageShell({
  bankId,
  children,
}: {
  bankId: string | null;
  children: ReactNode;
}) {
  return (
    <div className="min-h-dvh bg-background">
      <ResourceBankSelection bankId={bankId} />
      <BankSelector />
      <main className="mx-auto w-full min-w-0 max-w-5xl space-y-8 px-4 py-8 md:px-8 md:py-12">
        {children}
      </main>
    </div>
  );
}
