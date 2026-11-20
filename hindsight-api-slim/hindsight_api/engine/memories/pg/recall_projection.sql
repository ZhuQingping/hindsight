-- BEAM P1: compatible baseline, evaluate only used hydration distances.
CREATE SCHEMA IF NOT EXISTS recall_beam_projection;
CREATE OR REPLACE FUNCTION recall_beam_projection.candidates(p jsonb,tenant_schema name)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public SET timezone='UTC' AS $fn$
DECLARE
 rec record;v_row jsonb;v_sem jsonb:='[]';v_kw jsonb:='[]';v_graph jsonb:='[]';
 v_temporal jsonb:='[]';v_pool jsonb:='[]';v_arms jsonb;v_sql text;v_result jsonb;
 ftypes text[]:=ARRAY(SELECT jsonb_array_elements_text(p->'fact_types'));
 v_fact_type text;ft_ord int;seeds uuid[];legacy_ids uuid[];entity_ids uuid[];semantic_ids uuid[];causal_ids uuid[];
 e_scores jsonb;s_scores jsonb;c_scores jsonb;v_id uuid;v_score float8;v_other bool;
BEGIN
 p:=jsonb_set(p,'{tsquery}',to_jsonb(recall_beam_compatible.bm25_query(p,tenant_schema)));
 EXECUTE format('SELECT EXISTS(SELECT 1 FROM %I.memory_units WHERE bank_id=$1 AND fact_type NOT IN (''world'',''experience'') AND fact_type=ANY($2::text[]))',tenant_schema)
 INTO v_other USING p->>'bank_id',ftypes;
 IF v_other THEN RAISE EXCEPTION 'observation data is outside current BEAM compatibility scope';END IF;
 IF p->>'native_sql' IS NULL OR p->>'graph_sql' IS NULL OR p->>'temporal_sql' IS NULL THEN
  RAISE EXCEPTION 'original server-generated query templates are required';END IF;
 -- Keep the original complete native UNION and its row order.
 FOR rec IN EXECUTE p->>'native_sql' USING p->>'embedding',p->>'bank_id',(p->>'limit')::int,p->>'tsquery' LOOP
  ft_ord:=array_position(ftypes,rec.fact_type);
  IF rec.source='semantic' THEN
   v_sem:=v_sem||jsonb_build_array(jsonb_build_object('id',rec.id,'score',rec.similarity::float8,'ft',ft_ord));
  ELSE
   v_kw:=v_kw||jsonb_build_array(jsonb_build_object('id',rec.id,'score',rec.bm25_score::float8,'ft',ft_ord));
  END IF;
 END LOOP;
 -- Reuse one shared temporal pool, as the original multi-type retrieval does.
 IF p->>'window_start' IS NOT NULL AND p->>'window_end' IS NOT NULL THEN
  FOR rec IN EXECUTE p->>'temporal_sql' USING p->>'embedding',p->>'bank_id',
   (p->>'window_start')::timestamptz,(p->>'window_end')::timestamptz,(p->>'temporal_min')::float8 LOOP
   v_pool:=v_pool||jsonb_build_array(to_jsonb(rec));
  END LOOP;
 END IF;
 FOREACH v_fact_type IN ARRAY ftypes LOOP
  ft_ord:=array_position(ftypes,v_fact_type);seeds:='{}';entity_ids:='{}';semantic_ids:='{}';causal_ids:='{}';
  e_scores:='{}';s_scores:='{}';c_scores:='{}';
  FOR v_row IN SELECT value FROM jsonb_array_elements(v_sem) WITH ORDINALITY
   WHERE (value->>'ft')::int=ft_ord AND (value->>'score')::float8>=(p->>'graph_seed_min')::float8
   ORDER BY ordinality LIMIT 20 LOOP
   seeds:=array_append(seeds,(v_row->>'id')::uuid);
  END LOOP;
  seeds:=recall_equiv.legacy_set(seeds);
  IF cardinality(seeds)>0 THEN
   FOR rec IN EXECUTE p->>'graph_sql' USING seeds,v_fact_type,(p->>'limit')::int LOOP
    v_id:=rec.id;
    IF rec.source='entity' THEN
     entity_ids:=array_append(entity_ids,v_id);e_scores:=jsonb_set(e_scores,ARRAY[v_id::text],to_jsonb(tanh(rec.score::float8*0.5)));
    ELSIF rec.source='semantic' THEN
     semantic_ids:=array_append(semantic_ids,v_id);s_scores:=jsonb_set(s_scores,ARRAY[v_id::text],to_jsonb(greatest(coalesce((s_scores->>v_id::text)::float8,0),rec.score::float8)));
    ELSE
     causal_ids:=array_append(causal_ids,v_id);c_scores:=jsonb_set(c_scores,ARRAY[v_id::text],to_jsonb(greatest(coalesce((c_scores->>v_id::text)::float8,0),rec.score::float8)));
    END IF;
   END LOOP;
   legacy_ids:=recall_equiv.legacy_union(entity_ids,semantic_ids,causal_ids);
   FOREACH v_id IN ARRAY legacy_ids LOOP
    v_score:=(coalesce((e_scores->>v_id::text)::float8,0)+coalesce((s_scores->>v_id::text)::float8,0))+coalesce((c_scores->>v_id::text)::float8,0);
    v_graph:=v_graph||jsonb_build_array(jsonb_build_object('id',v_id,'score',v_score,'ft',ft_ord));
   END LOOP;
  END IF;
  SELECT v_temporal||coalesce(jsonb_agg(value||jsonb_build_object('ft',ft_ord) ORDER BY ordinality),'[]'::jsonb)
   INTO v_temporal FROM jsonb_array_elements(recall_beam_compatible.temporal_candidates(p,tenant_schema,v_fact_type,v_pool)) WITH ORDINALITY;
 END LOOP;
 -- Original: cap each type's graph at its budget, concatenate types, then stable score sort.
 SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'arm',arm,'rank',rank,'score',score,'proximity',proximity) ORDER BY arm,rank),'[]'::jsonb)
 INTO v_arms FROM (
  SELECT *,row_number() OVER(PARTITION BY arm ORDER BY score DESC,ft,ord)::int AS rank FROM (
   SELECT *,row_number() OVER(PARTITION BY arm,ft ORDER BY score DESC,ord)::int AS local_rank FROM (
    SELECT (value->>'id')::uuid AS id,0 AS arm,(value->>'score')::float8 AS score,
     NULL::float8 AS proximity,(value->>'ft')::int AS ft,ordinality AS ord FROM jsonb_array_elements(v_sem) WITH ORDINALITY
    UNION ALL SELECT (value->>'id')::uuid,1,(value->>'score')::float8,NULL::float8,(value->>'ft')::int,ordinality FROM jsonb_array_elements(v_kw) WITH ORDINALITY
    UNION ALL SELECT (value->>'id')::uuid,2,(value->>'score')::float8,NULL::float8,(value->>'ft')::int,ordinality FROM jsonb_array_elements(v_graph) WITH ORDINALITY
    UNION ALL SELECT (value->>'id')::uuid,3,(value->>'score')::float8,(value->>'proximity')::float8,(value->>'ft')::int,ordinality FROM jsonb_array_elements(v_temporal) WITH ORDINALITY
   ) raw
  ) by_type WHERE local_rank<=(p->>'limit')::int
 ) ranked;
 -- The common payload/fusion SQL is appended below from the tested implementation.
 v_sql:=replace($query$
WITH arms AS MATERIALIZED (
 SELECT * FROM jsonb_to_recordset($12) AS a(id uuid,arm int,rank int,score float8,proximity float8)
), temporal AS (SELECT id,score,proximity FROM arms WHERE arm=3)
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
 CASE WHEN p.first_arm=3 THEN 1-(m.embedding <=> $1::vector) END AS raw_similarity
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
  (p->>'graph_seed_min')::float8,(p->>'per_entity_limit')::int,v_arms;
 RETURN v_result;
END $fn$;
