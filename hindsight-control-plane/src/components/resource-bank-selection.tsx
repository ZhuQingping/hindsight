"use client";

import { useEffect } from "react";
import { useBank } from "@/lib/bank-context";

export function ResourceBankSelection({ bankId }: { bankId: string | null }) {
  const { setCurrentBank } = useBank();

  useEffect(() => {
    setCurrentBank(bankId);
  }, [bankId, setCurrentBank]);

  return null;
}
