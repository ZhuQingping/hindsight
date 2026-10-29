import { notFound } from "next/navigation";
import { contextDBEnabled } from "@/lib/contextdb";
import { BankSelector } from "@/components/bank-selector";
import { ContextDBUsersView } from "@/components/contextdb/users-view";

export const dynamic = "force-dynamic";
export default async function UsersPage() {
  if (!contextDBEnabled()) notFound();
  return (
    <div className="min-h-screen bg-background">
      <BankSelector />
      <ContextDBUsersView />
    </div>
  );
}
