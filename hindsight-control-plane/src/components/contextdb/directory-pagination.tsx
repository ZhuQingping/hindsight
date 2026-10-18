"use client";

import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export function DirectoryPagination({
  total,
  count,
  offset,
  limit,
  loading,
  onChange,
}: {
  total: number;
  count: number;
  offset: number;
  limit: number;
  loading: boolean;
  onChange: (offset: number) => void;
}) {
  const t = useTranslations("contextDB");
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
      {total > limit && (
        <Button
          variant="outline"
          disabled={loading || !offset}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          {t("previous")}
        </Button>
      )}
      <span>
        {total ? offset + 1 : 0}–{offset + count} / {total}
      </span>
      {total > limit && (
        <Button
          variant="outline"
          disabled={loading || offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          {t("next")}
        </Button>
      )}
    </div>
  );
}
