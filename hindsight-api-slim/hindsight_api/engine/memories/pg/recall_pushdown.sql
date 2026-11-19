-- Experimental PG candidate pipeline. Install only in the isolated test database.
-- SECURITY INVOKER: schema is resolved by ContextBase authentication, identifiers are quoted.
CREATE SCHEMA IF NOT EXISTS recall_pushdown;

CREATE OR REPLACE FUNCTION recall_pushdown.proximity(
 s timestamptz,e timestamptz,m timestamptz,ws timestamptz,we timestamptz,fallback float8)
RETURNS float8 LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $fn$
 SELECT CASE WHEN coalesce(s,e,m) IS NULL THEN fallback
 WHEN we <= ws THEN 1::float8
 ELSE 1-least(abs(extract(epoch FROM
 ((CASE WHEN s IS NOT NULL AND e IS NOT NULL THEN s+(e-s)/2 ELSE coalesce(s,e,m) END)
 -(ws+(we-ws)/2)))) / (extract(epoch FROM (we-ws))/2),1)::float8 END
$fn$;

CREATE OR REPLACE FUNCTION recall_pushdown.temporal_candidates(p jsonb, tenant_schema name)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public SET timezone='UTC' AS $fn$
DECLARE
 ws timestamptz := (p->>'window_start')::timestamptz;
 we timestamptz := (p->>'window_end')::timestamptz;
 v_entries jsonb; v_neighbors jsonb; v_row jsonb;
 v_results jsonb := '[]'; v_parents jsonb := '{}';
 v_seen uuid[] := '{}'; v_frontier uuid[] := '{}'; v_batch uuid[];
 v_id uuid; v_remaining int := (p->>'limit')::int; v_iteration int := 0;
 v_proximity float8; v_score float8;
BEGIN
 IF ws IS NULL OR we IS NULL THEN RETURN '[]'::jsonb; END IF;
 EXECUTE format($q$
 WITH pool AS MATERIALIZED (
  SELECT id,occurred_start,occurred_end,mentioned_at,
  1-(embedding <=> $1::vector) AS similarity
  FROM %I.memory_units WHERE bank_id=$2 AND fact_type='world' AND embedding IS NOT NULL
  AND ((occurred_start IS NOT NULL AND occurred_end IS NOT NULL AND occurred_start<=$4 AND occurred_end>=$3)
    OR mentioned_at BETWEEN $3 AND $4 OR occurred_start BETWEEN $3 AND $4 OR occurred_end BETWEEN $3 AND $4)
  AND 1-(embedding <=> $1::vector)>=$5
  ORDER BY embedding <=> $1::vector,id LIMIT 60
 ), buckets AS (
  SELECT *,CASE WHEN $4 <= $3 THEN 0 ELSE greatest(0,least(7,
   floor(extract(epoch FROM (coalesce(occurred_start,mentioned_at,occurred_end)-$3))
         /extract(epoch FROM ($4-$3))*8)::int)) END AS bucket
  FROM pool
 ), tiers AS (
  SELECT *,row_number() OVER(PARTITION BY bucket ORDER BY similarity DESC,id) AS tier
  FROM buckets
 ), selected AS (
  SELECT * FROM tiers
  ORDER BY CASE WHEN (SELECT count(*) FROM pool)<=10 THEN 0 ELSE tier END,similarity DESC,id LIMIT 10
 ) SELECT coalesce(jsonb_agg(to_jsonb(selected)),'[]'::jsonb) FROM selected
 $q$,tenant_schema)
 INTO v_entries USING p->>'embedding',p->>'bank_id',ws,we,(p->>'temporal_min')::float8;
 FOR v_row IN SELECT value FROM jsonb_array_elements(v_entries) LOOP
  v_id := (v_row->>'id')::uuid;
  v_proximity := recall_pushdown.proximity((v_row->>'occurred_start')::timestamptz,
   (v_row->>'occurred_end')::timestamptz,(v_row->>'mentioned_at')::timestamptz,ws,we,0.5);
  v_results := v_results || jsonb_build_array(jsonb_build_object('id',v_id,'score',v_proximity,'proximity',v_proximity));
  v_parents := jsonb_set(v_parents,ARRAY[v_id::text],to_jsonb(1::float8));
  v_seen := array_append(v_seen,v_id); v_frontier := array_append(v_frontier,v_id);
  v_remaining := v_remaining-1;
 END LOOP;
 WHILE cardinality(v_frontier)>0 AND v_remaining>0 AND v_iteration<5 LOOP
  v_iteration := v_iteration+1;
  v_batch := v_frontier[1:20]; v_frontier := coalesce(v_frontier[21:cardinality(v_frontier)],'{}'::uuid[]);
  EXECUTE format($q$
  WITH neighbors AS (
   SELECT m.id,m.occurred_start,m.occurred_end,m.mentioned_at,
    coalesce(($7->>src.id::text)::float8,0.5)*l.weight*0.7*
    CASE l.link_type WHEN 'causes' THEN 2 WHEN 'caused_by' THEN 2
     WHEN 'enables' THEN 1.5 WHEN 'prevents' THEN 1.5 ELSE 1 END AS propagated
   FROM unnest($2::uuid[]) src(id)
   CROSS JOIN LATERAL (
    SELECT ml.to_unit_id,ml.weight,ml.link_type FROM %I.memory_links ml
    WHERE ml.bank_id=$3 AND ml.from_unit_id=src.id
     AND ml.link_type IN ('temporal','causes','caused_by','enables','prevents') AND ml.weight>=0.1
    ORDER BY ml.weight DESC LIMIT 10
   ) l JOIN %I.memory_units m ON m.id=l.to_unit_id
   WHERE m.bank_id=$3 AND m.fact_type='world' AND m.embedding IS NOT NULL
    AND 1-(m.embedding <=> $1::vector)>=$4 AND m.id<>ALL($5::uuid[])
  ), best AS (
   SELECT DISTINCT ON(id) * FROM neighbors ORDER BY id,propagated DESC
  ), ordered AS (
   SELECT * FROM best ORDER BY propagated DESC,id LIMIT $6
  ) SELECT coalesce(jsonb_agg(to_jsonb(ordered) ORDER BY propagated DESC,id),'[]'::jsonb) FROM ordered
  $q$,tenant_schema,tenant_schema)
  INTO v_neighbors USING p->>'embedding',v_batch,p->>'bank_id',
   (p->>'temporal_min')::float8,v_seen,v_remaining,v_parents;
  FOR v_row IN SELECT value FROM jsonb_array_elements(v_neighbors) LOOP
   v_id := (v_row->>'id')::uuid;
   v_proximity := recall_pushdown.proximity((v_row->>'occurred_start')::timestamptz,
    (v_row->>'occurred_end')::timestamptz,(v_row->>'mentioned_at')::timestamptz,ws,we,0.3);
   v_score := greatest(v_proximity,(v_row->>'propagated')::float8);
   v_results := v_results || jsonb_build_array(jsonb_build_object('id',v_id,'score',v_score,'proximity',v_proximity));
   v_seen := array_append(v_seen,v_id); v_remaining := v_remaining-1;
   IF v_remaining>0 AND v_score>0.2 THEN
    v_parents := jsonb_set(v_parents,ARRAY[v_id::text],to_jsonb(v_score));
    v_frontier := array_append(v_frontier,v_id);
   END IF;
  END LOOP;
 END LOOP;
 RETURN v_results;
END $fn$;

CREATE OR REPLACE FUNCTION recall_pushdown.candidates(p jsonb, tenant_schema name)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public SET timezone='UTC' AS $fn$
DECLARE
 v_temporal jsonb; v_sql text; v_result jsonb; v_other bool;
BEGIN
 -- A frozen world-only bank may request empty experience/observation arms.
 -- Reject a populated unsupported type instead of silently dropping it or retrying.
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.memory_units WHERE bank_id=$1 AND fact_type<>''world'' AND fact_type=ANY($2::text[]))',tenant_schema)
 INTO v_other USING p->>'bank_id',ARRAY(SELECT jsonb_array_elements_text(p->'fact_types'));
 IF v_other THEN RAISE EXCEPTION 'non-world data is outside experimental recall scope'; END IF;
 v_temporal := recall_pushdown.temporal_candidates(p,tenant_schema);
 v_sql := replace($query$

WITH semantic AS MATERIALIZED (
 SELECT id, 1 - (embedding <=> $1::vector) AS score
 FROM "__RECALL_SCHEMA__".memory_units
 WHERE bank_id=$2 AND fact_type='world' AND embedding IS NOT NULL
   AND 1 - (embedding <=> $1::vector) >= $8
 ORDER BY embedding <=> $1::vector LIMIT $3
), keyword AS MATERIALIZED (
 SELECT id, ts_rank_cd(search_vector, to_tsquery('english', $4))::float8 AS score
 FROM "__RECALL_SCHEMA__".memory_units
 WHERE bank_id=$2 AND fact_type='world'
   AND search_vector @@ to_tsquery('english', $4)
 ORDER BY score DESC, id LIMIT $3
), seeds AS MATERIALIZED (
 SELECT id FROM semantic WHERE score >= $10 ORDER BY score DESC, id LIMIT 20
), seed_entities AS MATERIALIZED (
 SELECT DISTINCT ue.entity_id FROM "__RECALL_SCHEMA__".unit_entities ue JOIN seeds s ON s.id=ue.unit_id
), entity_expanded AS (
 SELECT t.unit_id AS id, tanh(count(DISTINCT se.entity_id)::float8*0.5) AS score
 FROM seed_entities se CROSS JOIN LATERAL (
   SELECT ut.unit_id FROM "__RECALL_SCHEMA__".unit_entities ut JOIN "__RECALL_SCHEMA__".memory_units m ON m.id=ut.unit_id
   WHERE ut.entity_id=se.entity_id AND m.bank_id=$2 AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=ut.unit_id)
   ORDER BY ut.unit_id DESC LIMIT $11
 ) t GROUP BY t.unit_id ORDER BY score DESC, t.unit_id LIMIT $3
), semantic_expanded AS (
 SELECT id, max(weight) AS score FROM (
   SELECT m.id, l.weight FROM "__RECALL_SCHEMA__".memory_links l JOIN seeds s ON s.id=l.from_unit_id
   JOIN "__RECALL_SCHEMA__".memory_units m ON m.id=l.to_unit_id
   WHERE l.bank_id=$2 AND m.bank_id=$2 AND l.link_type='semantic' AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=m.id)
   UNION ALL
   SELECT m.id, l.weight FROM "__RECALL_SCHEMA__".memory_links l JOIN seeds s ON s.id=l.to_unit_id
   JOIN "__RECALL_SCHEMA__".memory_units m ON m.id=l.from_unit_id
   WHERE l.bank_id=$2 AND m.bank_id=$2 AND l.link_type='semantic' AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=m.id)
 ) linked GROUP BY id ORDER BY score DESC, id LIMIT $3
), causal_expanded AS (
 SELECT DISTINCT ON (m.id) m.id, l.weight AS score
 FROM "__RECALL_SCHEMA__".memory_links l JOIN seeds s ON s.id=l.from_unit_id JOIN "__RECALL_SCHEMA__".memory_units m ON m.id=l.to_unit_id
 WHERE l.bank_id=$2 AND m.bank_id=$2 AND m.fact_type='world'
   AND l.link_type IN ('causes','caused_by','enables','prevents')
 ORDER BY m.id, l.weight DESC LIMIT $3
), graph AS MATERIALIZED (
 SELECT id, sum(score ORDER BY signal) AS score FROM (
   SELECT id,score,0 AS signal FROM entity_expanded
   UNION ALL SELECT id,score,1 FROM semantic_expanded
   UNION ALL SELECT id,score,2 FROM causal_expanded
 ) signals GROUP BY id ORDER BY score DESC,id LIMIT $3
), temporal AS MATERIALIZED (
 SELECT * FROM jsonb_to_recordset($12) AS t(id uuid, score float8, proximity float8)
), arms AS MATERIALIZED (
 SELECT id,0 AS arm,row_number() OVER(ORDER BY score DESC,id)::int AS rank,score FROM semantic
 UNION ALL
 SELECT id,1,row_number() OVER(ORDER BY score DESC,id)::int,score FROM keyword
 UNION ALL
 SELECT id,2,row_number() OVER(ORDER BY score DESC,id)::int,score FROM graph
 UNION ALL
 SELECT id,3,row_number() OVER(ORDER BY score DESC,id)::int,score FROM temporal
)

, packed AS (
 SELECT coalesce(array_agg(id ORDER BY arm,rank),'{}'::uuid[]) AS ids,
        coalesce(array_agg(rank ORDER BY arm,rank),'{}'::int[]) AS ranks FROM arms
), fused AS MATERIALIZED (
 SELECT f.* FROM packed CROSS JOIN LATERAL
 recall_probe.rrf_topk(packed.ids,packed.ranks,$5,60::float8) f
)

, positions AS (
 SELECT a.id,
   max(rank) FILTER(WHERE arm=0) AS semantic_rank,
   max(rank) FILTER(WHERE arm=1) AS bm25_rank,
   max(rank) FILTER(WHERE arm=2) AS graph_rank,
   max(rank) FILTER(WHERE arm=3) AS temporal_rank,
   max(score) FILTER(WHERE arm=0) AS semantic_score,
   max(score) FILTER(WHERE arm=1) AS keyword_score,
   max(score) FILTER(WHERE arm=2) AS graph_score,
   max(score) FILTER(WHERE arm=3) AS temporal_score,
   min(arm) AS first_arm
 FROM arms a JOIN fused f ON f.id=a.id GROUP BY a.id
)
, hydrated AS MATERIALIZED (
 SELECT f.id,f.rrf_score,f.rrf_rank,p.semantic_rank,p.bm25_rank,p.graph_rank,
 p.temporal_rank,p.semantic_score,p.keyword_score,p.graph_score,p.temporal_score,p.first_arm,m.text,m.fact_type,m.context,m.occurred_start,m.occurred_end,
 m.mentioned_at,m.event_date,m.document_id,m.chunk_id,m.metadata,m.tags,m.proof_count,m.attachment_ids,
 1-(m.embedding <=> $1::vector) AS raw_similarity
 FROM fused f JOIN positions p USING(id)
 JOIN "__RECALL_SCHEMA__".memory_units m ON m.id=f.id AND m.bank_id=$2
), candidate_json AS (
 SELECT coalesce(jsonb_agg(jsonb_build_object(
 'retrieval',jsonb_build_object('id',h.id,'text',h.text,'fact_type',h.fact_type,
 'context',h.context,'occurred_start',h.occurred_start,'occurred_end',h.occurred_end,
 'mentioned_at',h.mentioned_at,'event_date',h.event_date,'document_id',h.document_id,
 'chunk_id',h.chunk_id,'tags',h.tags,'proof_count',h.proof_count,
 'metadata',CASE WHEN h.first_arm=2 THEN NULL ELSE h.metadata END,
 'attachment_ids',coalesce(h.attachment_ids,'{}'::text[]),
 'similarity',CASE WHEN h.first_arm=0 THEN h.semantic_score WHEN h.first_arm=3 THEN h.raw_similarity END,
 'bm25_score',CASE WHEN h.first_arm=1 THEN h.keyword_score END,
 'activation',CASE WHEN h.first_arm=2 THEN h.graph_score END,
 'temporal_score',CASE WHEN h.first_arm=3 THEN h.temporal_score END,
 'temporal_proximity',CASE WHEN h.first_arm=3 THEN t.proximity END),
 'rrf_score',h.rrf_score,'rrf_rank',h.rrf_rank,
 'source_ranks',jsonb_strip_nulls(jsonb_build_object('semantic_rank',h.semantic_rank,
 'bm25_rank',h.bm25_rank,'graph_rank',h.graph_rank,'temporal_rank',h.temporal_rank)),
 'arm_scores',jsonb_build_object('semantic',h.semantic_score,'keyword',h.keyword_score)
 ) ORDER BY h.rrf_rank),'[]'::jsonb) AS candidates
 FROM hydrated h LEFT JOIN temporal t ON t.id=h.id
), chunk_json AS (
 SELECT coalesce(jsonb_object_agg(c.chunk_id,jsonb_build_object(
 'chunk_text',c.chunk_text,'chunk_index',c.chunk_index,'document_id',c.document_id)),
 '{}'::jsonb) AS chunks
 FROM "__RECALL_SCHEMA__".chunks c
 WHERE c.bank_id=$2 AND c.chunk_id IN (SELECT chunk_id FROM hydrated WHERE chunk_id IS NOT NULL)
)
SELECT jsonb_build_object('version',1,'candidates',candidates,'chunks',chunks)
FROM candidate_json CROSS JOIN chunk_json

$query$, '"__RECALL_SCHEMA__"',format('%I',tenant_schema));
 EXECUTE v_sql INTO v_result USING p->>'embedding',p->>'bank_id',(p->>'limit')::int,
  p->>'tsquery',(p->>'candidate_cap')::int,(p->>'window_start')::timestamptz,
  (p->>'window_end')::timestamptz,(p->>'semantic_min')::float8,(p->>'temporal_min')::float8,
  (p->>'graph_seed_min')::float8,(p->>'per_entity_limit')::int,v_temporal;
 RETURN v_result;
END $fn$;
