CREATE TABLE IF NOT EXISTS {schema}.ctxdb_usage_stats (
    bank_id varchar(54) NOT NULL,
    object_type text NOT NULL,
    object_id varchar(64) NOT NULL,
    recall_count bigint NOT NULL,
    last_recalled_at timestamptz NOT NULL,
    CONSTRAINT ctxdb_usage_stats_pkey PRIMARY KEY (bank_id,object_type,object_id),
    CONSTRAINT usage_object_type CHECK (object_type IN ('memory','knowledge_page')),
    CONSTRAINT usage_object_identity CHECK (length(object_id)>0),
    CONSTRAINT usage_positive_count CHECK (recall_count>0)
);
COMMENT ON TABLE {schema}.ctxdb_usage_stats IS 'Eventually consistent usage of final memory and knowledge search results.';
COMMENT ON COLUMN {schema}.ctxdb_usage_stats.bank_id IS 'Registered Bank owning this usage record.';
COMMENT ON COLUMN {schema}.ctxdb_usage_stats.object_type IS 'Memory or knowledge page, not a folder or Mental Model.';
COMMENT ON COLUMN {schema}.ctxdb_usage_stats.object_id IS 'Canonical memory UUID or knowledge_pages.id.';
COMMENT ON COLUMN {schema}.ctxdb_usage_stats.recall_count IS 'Recorded final-result occurrences since usage initialization or reset.';
COMMENT ON COLUMN {schema}.ctxdb_usage_stats.last_recalled_at IS 'Latest recorded event time, not the asynchronous write time.';
COMMENT ON CONSTRAINT ctxdb_usage_stats_pkey ON {schema}.ctxdb_usage_stats IS 'Usage is scoped to its workspace schema, Bank and object.';
COMMENT ON INDEX {schema}.ctxdb_usage_stats_pkey IS 'Lookup and bounded cleanup by Bank and object identity.';
COMMENT ON CONSTRAINT usage_object_type ON {schema}.ctxdb_usage_stats IS 'Only supported final-result object types are recorded.';
COMMENT ON CONSTRAINT usage_object_identity ON {schema}.ctxdb_usage_stats IS 'Object identity must not be empty.';
COMMENT ON CONSTRAINT usage_positive_count ON {schema}.ctxdb_usage_stats IS 'Persisted usage rows contain at least one recorded occurrence.';
