-- Load ONLY in the private experimental cluster; :library is an absolute path.
CREATE SCHEMA IF NOT EXISTS recall_probe;
CREATE OR REPLACE FUNCTION recall_probe.rrf_topk(uuid[],int[],int,float8)
RETURNS TABLE(id uuid,rrf_score float8,rrf_rank int,first_ordinal int)
AS :'library','contextbase_rrf_topk' LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE;
CREATE OR REPLACE FUNCTION recall_probe.budget_select(uuid[],int[],int,bool)
RETURNS uuid[] AS :'library','contextbase_budget_select'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE;
