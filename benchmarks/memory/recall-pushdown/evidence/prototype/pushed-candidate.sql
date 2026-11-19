-- $1 vector string; $2 bank; $3 arm limit; $4 native tsquery text; $5 fusion Top-K

WITH semantic AS MATERIALIZED (
 SELECT id, 1 - (embedding <=> $1::vector) AS score
 FROM "ctxdb_ws_locomo_conv30_20261118_200523".memory_units
 WHERE bank_id=$2 AND fact_type='world' AND embedding IS NOT NULL
   AND 1 - (embedding <=> $1::vector) >= 0.3
 ORDER BY embedding <=> $1::vector LIMIT $3
), keyword AS MATERIALIZED (
 SELECT id, ts_rank_cd(search_vector, to_tsquery('english', $4))::float8 AS score
 FROM "ctxdb_ws_locomo_conv30_20261118_200523".memory_units
 WHERE bank_id=$2 AND fact_type='world'
   AND search_vector @@ to_tsquery('english', $4)
 ORDER BY score DESC, id LIMIT $3
), seeds AS MATERIALIZED (
 SELECT id FROM semantic ORDER BY score DESC, id LIMIT 20
), seed_entities AS MATERIALIZED (
 SELECT DISTINCT ue.entity_id FROM "ctxdb_ws_locomo_conv30_20261118_200523".unit_entities ue JOIN seeds s ON s.id=ue.unit_id
), entity_expanded AS (
 SELECT t.unit_id AS id, tanh(count(DISTINCT se.entity_id)::float8*0.5) AS score
 FROM seed_entities se CROSS JOIN LATERAL (
   SELECT ut.unit_id FROM "ctxdb_ws_locomo_conv30_20261118_200523".unit_entities ut JOIN "ctxdb_ws_locomo_conv30_20261118_200523".memory_units m ON m.id=ut.unit_id
   WHERE ut.entity_id=se.entity_id AND m.bank_id=$2 AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=ut.unit_id)
   ORDER BY ut.unit_id DESC LIMIT 200
 ) t GROUP BY t.unit_id ORDER BY score DESC, t.unit_id LIMIT $3
), semantic_expanded AS (
 SELECT id, max(weight) AS score FROM (
   SELECT m.id, l.weight FROM "ctxdb_ws_locomo_conv30_20261118_200523".memory_links l JOIN seeds s ON s.id=l.from_unit_id
   JOIN "ctxdb_ws_locomo_conv30_20261118_200523".memory_units m ON m.id=l.to_unit_id
   WHERE l.bank_id=$2 AND m.bank_id=$2 AND l.link_type='semantic' AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=m.id)
   UNION ALL
   SELECT m.id, l.weight FROM "ctxdb_ws_locomo_conv30_20261118_200523".memory_links l JOIN seeds s ON s.id=l.to_unit_id
   JOIN "ctxdb_ws_locomo_conv30_20261118_200523".memory_units m ON m.id=l.from_unit_id
   WHERE l.bank_id=$2 AND m.bank_id=$2 AND l.link_type='semantic' AND m.fact_type='world'
     AND NOT EXISTS (SELECT 1 FROM seeds WHERE seeds.id=m.id)
 ) linked GROUP BY id ORDER BY score DESC, id LIMIT $3
), causal_expanded AS (
 SELECT DISTINCT ON (m.id) m.id, l.weight AS score
 FROM "ctxdb_ws_locomo_conv30_20261118_200523".memory_links l JOIN seeds s ON s.id=l.from_unit_id JOIN "ctxdb_ws_locomo_conv30_20261118_200523".memory_units m ON m.id=l.to_unit_id
 WHERE l.bank_id=$2 AND m.bank_id=$2 AND m.fact_type='world'
   AND l.link_type IN ('causes','caused_by','enables','prevents')
 ORDER BY m.id, l.weight DESC LIMIT $3
), graph AS MATERIALIZED (
 SELECT id, sum(score ORDER BY signal) AS score FROM (
   SELECT id,score,0 AS signal FROM entity_expanded
   UNION ALL SELECT id,score,1 FROM semantic_expanded
   UNION ALL SELECT id,score,2 FROM causal_expanded
 ) signals GROUP BY id ORDER BY score DESC,id LIMIT $3
), arms AS MATERIALIZED (
 SELECT id,0 AS arm,row_number() OVER(ORDER BY score DESC,id)::int AS rank,score FROM semantic
 UNION ALL
 SELECT id,1,row_number() OVER(ORDER BY score DESC,id)::int,score FROM keyword
 UNION ALL
 SELECT id,2,row_number() OVER(ORDER BY score DESC,id)::int,score FROM graph
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
   max(score) FILTER(WHERE arm=0) AS semantic_score,
   max(score) FILTER(WHERE arm=1) AS keyword_score,
   max(score) FILTER(WHERE arm=2) AS graph_score,
   min(arm) AS first_arm
 FROM arms a JOIN fused f ON f.id=a.id GROUP BY a.id
)
SELECT f.*,p.semantic_rank,p.bm25_rank,p.graph_rank,p.semantic_score,p.keyword_score,
 p.graph_score,p.first_arm,m.text,m.fact_type,m.context,m.occurred_start,m.occurred_end,
 m.mentioned_at,m.event_date,m.document_id,m.chunk_id,m.metadata,m.tags,m.proof_count,m.attachment_ids
FROM fused f JOIN positions p ON p.id=f.id
JOIN "ctxdb_ws_locomo_conv30_20261118_200523".memory_units m ON m.id=f.id AND m.bank_id=$2
ORDER BY f.rrf_rank
