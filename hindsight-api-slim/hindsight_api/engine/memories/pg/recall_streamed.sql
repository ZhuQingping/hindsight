-- BEAM P4: built-in scalar row stream avoids JSON serialization of full chunk texts; batch graph-score reduction and typed graph candidates; same source cursors/ordinals, typed arrays instead of JSON candidate assembly.
CREATE SCHEMA IF NOT EXISTS recall_beam_streamed;
CREATE OR REPLACE FUNCTION recall_beam_streamed.candidates(p jsonb,tenant_schema name)
RETURNS TABLE(version int,part int,ordinal int,payload jsonb,chunk_id text,chunk_text text,chunk_index int,document_id text) LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public SET timezone='UTC' AS $fn$
DECLARE
 rec record;v_row jsonb;
 v_temporal jsonb:='[]';v_pool jsonb:='[]';v_sql text;
 ftypes text[]:=ARRAY(SELECT jsonb_array_elements_text(p->'fact_types'));
 v_fact_type text;ft_ord int;seeds uuid[];legacy_ids uuid[];entity_ids uuid[];semantic_ids uuid[];causal_ids uuid[];
 e_scores float8[];s_scores float8[];c_scores float8[];v_id uuid;v_score float8;v_other bool;
 sem_ids uuid[]:='{}';sem_scores float8[]:='{}';sem_ft int[]:='{}';
 kw_ids uuid[]:='{}';kw_scores float8[]:='{}';kw_ft int[]:='{}';
 graph_ids uuid[]:='{}';graph_scores float8[]:='{}';graph_ft int[]:='{}';
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
   sem_ids:=array_append(sem_ids,rec.id);sem_scores:=array_append(sem_scores,rec.similarity::float8);sem_ft:=array_append(sem_ft,ft_ord);
  ELSE
   kw_ids:=array_append(kw_ids,rec.id);kw_scores:=array_append(kw_scores,rec.bm25_score::float8);kw_ft:=array_append(kw_ft,ft_ord);
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
  e_scores:='{}'::float8[];s_scores:='{}'::float8[];c_scores:='{}'::float8[];
  FOR rec IN SELECT a.id FROM unnest(sem_ids,sem_scores,sem_ft) WITH ORDINALITY AS a(id,score,fact_ordinal,ord)
   WHERE a.fact_ordinal=ft_ord AND a.score>=(p->>'graph_seed_min')::float8 ORDER BY a.ord LIMIT 20 LOOP
   seeds:=array_append(seeds,rec.id);
  END LOOP;
  seeds:=recall_equiv.legacy_set(seeds);
  IF cardinality(seeds)>0 THEN
   FOR rec IN EXECUTE p->>'graph_sql' USING seeds,v_fact_type,(p->>'limit')::int LOOP
    v_id:=rec.id;
    IF rec.source='entity' THEN
     entity_ids:=array_append(entity_ids,v_id);e_scores:=array_append(e_scores,tanh(rec.score::float8*0.5));
    ELSIF rec.source='semantic' THEN
     semantic_ids:=array_append(semantic_ids,v_id);s_scores:=array_append(s_scores,rec.score::float8);
    ELSE
     causal_ids:=array_append(causal_ids,v_id);c_scores:=array_append(c_scores,rec.score::float8);
    END IF;
   END LOOP;
   legacy_ids:=recall_equiv.legacy_union(entity_ids,semantic_ids,causal_ids);
   -- Preserve the legacy union order and exact (entity + semantic) + causal
   -- reduction. Batch relation operations avoid copying three growing JSONB maps.
   FOR rec IN
    WITH e AS (
     SELECT a.id,(array_agg(a.score ORDER BY a.ord DESC))[1] AS score
     FROM unnest(entity_ids,e_scores) WITH ORDINALITY AS a(id,score,ord) GROUP BY a.id
    ), s AS (
     SELECT a.id,greatest(max(a.score),0::float8) AS score
     FROM unnest(semantic_ids,s_scores) AS a(id,score) GROUP BY a.id
    ), c AS (
     SELECT a.id,greatest(max(a.score),0::float8) AS score
     FROM unnest(causal_ids,c_scores) AS a(id,score) GROUP BY a.id
    ) SELECT k.id,(coalesce(e.score,0::float8)+coalesce(s.score,0::float8))+coalesce(c.score,0::float8) AS score
     FROM unnest(legacy_ids) WITH ORDINALITY AS k(id,ord)
     LEFT JOIN e ON e.id=k.id LEFT JOIN s ON s.id=k.id LEFT JOIN c ON c.id=k.id ORDER BY k.ord
   LOOP
    graph_ids:=array_append(graph_ids,rec.id);graph_scores:=array_append(graph_scores,rec.score);graph_ft:=array_append(graph_ft,ft_ord);
   END LOOP;
  END IF;
  SELECT v_temporal||coalesce(jsonb_agg(value||jsonb_build_object('ft',ft_ord) ORDER BY ordinality),'[]'::jsonb)
   INTO v_temporal FROM jsonb_array_elements(recall_beam_compatible.temporal_candidates(p,tenant_schema,v_fact_type,v_pool)) WITH ORDINALITY;
 END LOOP;
 -- The common payload/fusion SQL is appended below from the tested implementation.
 v_sql:=replace($query$
WITH arms AS MATERIALIZED (
 SELECT id,arm,rank,score,proximity FROM (
  SELECT *,row_number() OVER(PARTITION BY arm ORDER BY score DESC,ft,ord)::int AS rank FROM (
   SELECT *,row_number() OVER(PARTITION BY arm,ft ORDER BY score DESC,ord)::int AS local_rank FROM (
    SELECT a.id,0 AS arm,a.score,NULL::float8 AS proximity,a.ft,a.ord
     FROM unnest($12::uuid[],$13::float8[],$14::int[]) WITH ORDINALITY AS a(id,score,ft,ord)
    UNION ALL SELECT a.id,1,a.score,NULL::float8,a.ft,a.ord
     FROM unnest($15::uuid[],$16::float8[],$17::int[]) WITH ORDINALITY AS a(id,score,ft,ord)
    UNION ALL SELECT a.id,2,a.score,NULL::float8,a.ft,a.ord
     FROM unnest($18::uuid[],$19::float8[],$20::int[]) WITH ORDINALITY AS a(id,score,ft,ord)
    UNION ALL SELECT (value->>'id')::uuid,3,(value->>'score')::float8,(value->>'proximity')::float8,(value->>'ft')::int,ordinality
     FROM jsonb_array_elements($21::jsonb) WITH ORDINALITY
   ) raw
  ) by_type WHERE local_rank<=$3
 ) ranked
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
)
SELECT 1::int,0::int,0::int,candidates,NULL::text,NULL::text,NULL::int,NULL::text FROM candidate_json
UNION ALL
SELECT 1::int,1::int,row_number() OVER(ORDER BY octet_length(c.chunk_id),c.chunk_id COLLATE "C")::int,
 NULL::jsonb,c.chunk_id,c.chunk_text,c.chunk_index,c.document_id
FROM "__RECALL_SCHEMA__".chunks c
WHERE c.bank_id=$2 AND c.chunk_id IN (SELECT chunk_id FROM hydrated WHERE chunk_id IS NOT NULL)
ORDER BY 2,3

$query$, '"__RECALL_SCHEMA__"',format('%I',tenant_schema));
 RETURN QUERY EXECUTE v_sql USING p->>'embedding',p->>'bank_id',(p->>'limit')::int,
  p->>'tsquery',(p->>'candidate_cap')::int,(p->>'window_start')::timestamptz,
  (p->>'window_end')::timestamptz,(p->>'semantic_min')::float8,(p->>'temporal_min')::float8,
  (p->>'graph_seed_min')::float8,(p->>'per_entity_limit')::int,sem_ids,sem_scores,sem_ft,kw_ids,kw_scores,kw_ft,graph_ids,graph_scores,graph_ft,v_temporal;

END $fn$;
