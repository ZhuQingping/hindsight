-- The native builder uses the two-argument, normalization=0 ts_rank_cd form.
-- Its OR specialization returns the same float4; other query shapes delegate
-- to PostgreSQL's original implementation.  Preserve the complete branch
-- projections, sort keys, LIMITs and P3 collector instead of changing plans.
-- Prerequisite: recall_rank.rank_cd(tsvector, tsquery), registered to the
-- independently versioned contextbase_rank_cd_or C module, and baseline P3.
CREATE SCHEMA IF NOT EXISTS recall_beam_rank;

CREATE OR REPLACE FUNCTION recall_beam_rank.candidates(p jsonb, tenant_schema name)
RETURNS jsonb
LANGUAGE sql STABLE
SET search_path = pg_catalog, public
AS $function$
    SELECT recall_beam_arrays.candidates(
        jsonb_set(
            p,
            '{native_sql}',
            to_jsonb(replace(p->>'native_sql', 'ts_rank_cd(', 'recall_rank.rank_cd('))
        ),
        tenant_schema
    )
$function$;
