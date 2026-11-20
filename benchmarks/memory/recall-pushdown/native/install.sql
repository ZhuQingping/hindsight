-- Explicit DBA install in an isolated experiment database only.
-- psql -v rrf_library=/absolute/versioned/contextbase_recall \
--      -v legacy_library=/absolute/versioned/contextbase_legacy_order \
--      -v rank_library=/absolute/versioned/contextbase_rank_cd_or \
--      -v memory_role=experiment_reader -f native/install.sql
-- All libraries must already exist on the database host. No table initialization.
\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA IF NOT EXISTS recall_probe;
CREATE SCHEMA IF NOT EXISTS recall_equiv;
CREATE SCHEMA IF NOT EXISTS recall_rank;
CREATE OR REPLACE FUNCTION recall_probe.rrf_topk(uuid[],int[],int,float8)
RETURNS TABLE(id uuid,rrf_score float8,rrf_rank int,first_ordinal int)
AS :'rrf_library','contextbase_rrf_topk'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE;
CREATE OR REPLACE FUNCTION recall_equiv.legacy_set(uuid[]) RETURNS uuid[]
AS :'legacy_library','contextbase_cpython311_set_seed0'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE;
CREATE OR REPLACE FUNCTION recall_equiv.legacy_union(uuid[],uuid[],uuid[]) RETURNS uuid[]
AS :'legacy_library','contextbase_cpython311_union_seed0'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE;
CREATE OR REPLACE FUNCTION recall_rank.rank_cd(tsvector,tsquery) RETURNS real
AS :'rank_library','contextbase_rank_cd_or'
LANGUAGE C IMMUTABLE STRICT PARALLEL SAFE COST 1;

-- Runtime SQL remains the single source in the ContextBase store.
\ir ../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_equivalent.sql
\ir ../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_beam.sql
\ir ../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_arrays.sql
\ir ../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank.sql
\ir ../../../../hindsight-api-slim/hindsight_api/engine/memories/pg/recall_rank_json.sql

-- Invoker rights throughout. Do not grant these raw-template functions to clients.
REVOKE ALL ON SCHEMA recall_probe, recall_equiv, recall_rank,
    recall_beam_compatible, recall_beam_arrays, recall_beam_rank, recall_beam_rank_json FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA recall_probe, recall_equiv, recall_rank,
    recall_beam_compatible, recall_beam_arrays, recall_beam_rank, recall_beam_rank_json FROM PUBLIC;
GRANT USAGE ON SCHEMA recall_probe, recall_equiv, recall_rank,
    recall_beam_compatible, recall_beam_arrays, recall_beam_rank, recall_beam_rank_json TO :"memory_role";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA recall_probe, recall_equiv, recall_rank,
    recall_beam_compatible, recall_beam_arrays, recall_beam_rank, recall_beam_rank_json TO :"memory_role";
COMMIT;
