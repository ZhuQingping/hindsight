-- Compatibility baseline for actual BEAM world+experience facts; no scoring policy changes.
CREATE SCHEMA IF NOT EXISTS recall_beam_compatible;
CREATE OR REPLACE FUNCTION recall_beam_compatible.bm25_query(p jsonb, tenant_schema name)
RETURNS text LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public AS $fn$
DECLARE
 tokens text[]:=ARRAY(SELECT jsonb_array_elements_text(p->'tokens'));
 term_limit int:=coalesce((p->>'term_limit')::int,0); chosen text[];
BEGIN
 -- Historical parameter bundles have already-resolved text and no tokens field.
 IF NOT p ? 'tokens' THEN RETURN p->>'tsquery';END IF;
 IF term_limit<=0 OR cardinality(tokens)<=term_limit THEN RETURN array_to_string(tokens,' | ');END IF;
 chosen:=tokens[1:term_limit];
 IF coalesce((p->>'selective_terms')::bool,false) THEN
  BEGIN
   WITH toks AS (
    SELECT ord,tok FROM unnest(tokens) WITH ORDINALITY AS u(tok,ord)
   ), lex AS (
    SELECT t.ord,l.lexeme FROM toks t LEFT JOIN LATERAL
     unnest(tsvector_to_array(to_tsvector((p->>'language')::regconfig,t.tok))) AS l(lexeme) ON true
   ), stats AS (
    SELECT unnest(most_common_elems::text::text[]) AS lexeme,
     unnest((most_common_elem_freqs)[1:array_length(most_common_elems::text::text[],1)]) AS freq
    FROM pg_stats WHERE schemaname=tenant_schema::text AND tablename='memory_units' AND attname='search_vector'
   ), scored AS (
    SELECT lex.ord,bool_or(lex.lexeme IS NOT NULL) AS has_lexeme,coalesce(max(s.freq),0)::float8 AS df
    FROM lex LEFT JOIN stats s ON s.lexeme=lex.lexeme GROUP BY lex.ord
   ), kept AS (
    SELECT ord FROM scored WHERE has_lexeme ORDER BY df,ord LIMIT term_limit
   ) SELECT array_agg(tokens[ord] ORDER BY ord) INTO chosen FROM kept;
   IF cardinality(chosen) IS NULL OR cardinality(chosen)=0 THEN chosen:=tokens[1:term_limit];END IF;
  EXCEPTION WHEN OTHERS THEN
   -- Same best-effort stats lookup as the original Python selector. The nested
   -- block rolls back only the failed lookup before the first-N fallback.
   chosen:=tokens[1:term_limit];
  END;
 END IF;
 RETURN array_to_string(chosen,' | ');
END $fn$;

CREATE OR REPLACE FUNCTION recall_beam_compatible.temporal_candidates(p jsonb,tenant_schema name,v_fact_type text,input_pool jsonb)
RETURNS jsonb LANGUAGE plpgsql STABLE SET search_path=pg_catalog,public SET timezone='UTC' AS $fn$
DECLARE
 ws timestamptz:=(p->>'window_start')::timestamptz;
 we timestamptz:=(p->>'window_end')::timestamptz;
 v_pool jsonb:='[]'; v_entries jsonb; v_results jsonb:='[]'; v_parents jsonb:='{}';
 v_seen uuid[]:='{}'; v_frontier uuid[]:='{}'; v_batch uuid[]; v_best_order uuid[];
 v_best jsonb; v_ranked jsonb; v_row jsonb; v_record record; v_id uuid;
 v_remaining int:=(p->>'limit')::int; v_iteration int:=0;
 v_proximity float8; v_propagated float8; v_score float8;
BEGIN
 IF ws IS NULL OR we IS NULL THEN RETURN '[]'::jsonb; END IF;
 SELECT coalesce(jsonb_agg(value ORDER BY ordinality),'[]'::jsonb) INTO v_pool
 FROM jsonb_array_elements(input_pool) WITH ORDINALITY WHERE value->>'fact_type'=v_fact_type;
 -- Python's stable tier sort uses first bucket appearance for equal similarities.
 IF jsonb_array_length(v_pool)<=10 THEN v_entries:=v_pool;
 ELSE
  WITH rows AS (
   SELECT value,ordinality AS ord,CASE WHEN we<=ws THEN 0 ELSE greatest(0,least(7,
    trunc((extract(epoch FROM (coalesce((value->>'occurred_start')::timestamptz,
      (value->>'mentioned_at')::timestamptz,(value->>'occurred_end')::timestamptz)-ws))::float8
      /extract(epoch FROM (we-ws))::float8)*8)::int)) END AS bucket
   FROM jsonb_array_elements(v_pool) WITH ORDINALITY
  ), tiers AS (
   SELECT *,row_number() OVER(PARTITION BY bucket ORDER BY (value->>'similarity')::float8 DESC,ord) AS tier,
    min(ord) OVER(PARTITION BY bucket) AS bucket_ord FROM rows
  ), selected AS (
   SELECT * FROM tiers ORDER BY tier,(value->>'similarity')::float8 DESC,bucket_ord LIMIT 10
  ) SELECT coalesce(jsonb_agg(value ORDER BY tier,(value->>'similarity')::float8 DESC,bucket_ord),'[]'::jsonb)
    INTO v_entries FROM selected;
 END IF;
 FOR v_row IN SELECT value FROM jsonb_array_elements(v_entries) LOOP
  v_id:=(v_row->>'id')::uuid;
  v_proximity:=recall_equiv.proximity((v_row->>'occurred_start')::timestamptz,
   (v_row->>'occurred_end')::timestamptz,(v_row->>'mentioned_at')::timestamptz,ws,we,0.5);
  v_results:=v_results||jsonb_build_array(jsonb_build_object('id',v_id,'score',v_proximity,'proximity',v_proximity));
  v_parents:=jsonb_set(v_parents,ARRAY[v_id::text],to_jsonb(1::float8));
  v_seen:=array_append(v_seen,v_id);v_frontier:=array_append(v_frontier,v_id);v_remaining:=v_remaining-1;
 END LOOP;
 WHILE cardinality(v_frontier)>0 AND v_remaining>0 AND v_iteration<5 LOOP
  v_iteration:=v_iteration+1;v_batch:=v_frontier[1:20];
  v_frontier:=coalesce(v_frontier[21:cardinality(v_frontier)],'{}'::uuid[]);
  v_best:='{}';v_best_order:='{}';
  -- Same original neighbor query, including its natural row order and per-source LIMIT.
  FOR v_record IN EXECUTE format($q$
   SELECT src.from_unit_id,mu.id,mu.text,mu.context,mu.event_date,mu.occurred_start,
    mu.occurred_end,mu.mentioned_at,mu.fact_type,mu.document_id,mu.chunk_id,mu.tags,
    mu.metadata,mu.proof_count,l.weight,l.link_type,1-(mu.embedding<=>$1::vector) AS similarity
   FROM unnest($2::uuid[]) AS src(from_unit_id)
   CROSS JOIN LATERAL (
    SELECT ml.to_unit_id,ml.weight,ml.link_type FROM %I.memory_links ml
    WHERE ml.from_unit_id=src.from_unit_id
     AND ml.link_type IN ('temporal','causes','caused_by','enables','prevents') AND ml.weight>=0.1
    ORDER BY ml.weight DESC LIMIT $5
   ) l JOIN %I.memory_units mu ON mu.id=l.to_unit_id
   WHERE mu.bank_id=$6 AND mu.fact_type=$3 AND mu.embedding IS NOT NULL
    AND 1-(mu.embedding<=>$1::vector)>=$4
  $q$,tenant_schema,tenant_schema)
  USING p->>'embedding',v_batch,v_fact_type,(p->>'temporal_min')::float8,10,p->>'bank_id' LOOP
   v_id:=v_record.id;
   IF v_id=ANY(v_seen) THEN CONTINUE; END IF;
   -- Match Python's multiplication order: parent * weight * boost * decay.
   v_propagated:=coalesce((v_parents->>v_record.from_unit_id::text)::float8,0.5)*v_record.weight*
    CASE v_record.link_type WHEN 'causes' THEN 2.0 WHEN 'caused_by' THEN 2.0
     WHEN 'enables' THEN 1.5 WHEN 'prevents' THEN 1.5 ELSE 1.0 END*0.7;
   IF NOT v_best ? v_id::text THEN v_best_order:=array_append(v_best_order,v_id); END IF;
   IF NOT v_best ? v_id::text OR v_propagated>(v_best->v_id::text->>'propagated')::float8 THEN
    v_best:=jsonb_set(v_best,ARRAY[v_id::text],to_jsonb(v_record)||jsonb_build_object('propagated',v_propagated));
   END IF;
  END LOOP;
  SELECT coalesce(jsonb_agg(value ORDER BY (value->>'propagated')::float8 DESC,
    array_position(v_best_order,key::uuid)),'[]'::jsonb) INTO v_ranked FROM jsonb_each(v_best);
  FOR v_row IN SELECT value FROM jsonb_array_elements(v_ranked) LOOP
   v_id:=(v_row->>'id')::uuid;v_seen:=array_append(v_seen,v_id);v_remaining:=v_remaining-1;
   v_proximity:=recall_equiv.proximity((v_row->>'occurred_start')::timestamptz,
    (v_row->>'occurred_end')::timestamptz,(v_row->>'mentioned_at')::timestamptz,ws,we,0.3);
   v_score:=greatest(v_proximity,(v_row->>'propagated')::float8);
   v_results:=v_results||jsonb_build_array(jsonb_build_object('id',v_id,'score',v_score,'proximity',v_proximity));
   IF v_remaining>0 AND v_score>0.2 THEN
    v_parents:=jsonb_set(v_parents,ARRAY[v_id::text],to_jsonb(v_score));v_frontier:=array_append(v_frontier,v_id);
   END IF;
   IF v_remaining<=0 THEN EXIT; END IF;
  END LOOP;
 END LOOP;
 RETURN v_results;
END $fn$;

CREATE OR REPLACE FUNCTION recall_beam_compatible.candidates(p jsonb,tenant_schema name)
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
  (p->>'graph_seed_min')::float8,(p->>'per_entity_limit')::int,v_arms;
 RETURN v_result;
END $fn$;
