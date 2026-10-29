import { LoaderCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const SIZES = {
  xs: "w-3.5 h-3.5",
  sm: "w-4 h-4",
  md: "w-6 h-6",
  lg: "w-8 h-8",
  xl: "w-14 h-14",
} as const;

export type SpinnerSize = keyof typeof SIZES;

export function Spinner({
  size = "md",
  variant = "flip",
  className,
}: {
  size?: SpinnerSize;
  variant?: "flip" | "jump";
  className?: string;
}) {
  return (
    <LoaderCircle
      role="status"
      aria-label="Loading"
      className={cn(
        SIZES[size],
        "inline-block animate-spin text-primary motion-reduce:animate-none",
        variant === "jump" && "[animation-duration:1.4s]",
        className
      )}
    />
  );
}
