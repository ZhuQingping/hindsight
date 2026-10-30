"use client";

import { useProductName } from "./product-runtime";
import { cn } from "@/lib/utils";

/** A typographic identity keeps the product distinct without implying a supplied logo. */
export function Brand({ className }: { className?: string }) {
  const name = useProductName();
  return (
    <span
      aria-label={name}
      className={cn(
        "inline-flex items-baseline text-xl font-semibold tracking-[-0.055em]",
        className
      )}
    >
      <span>{name}</span>
    </span>
  );
}
