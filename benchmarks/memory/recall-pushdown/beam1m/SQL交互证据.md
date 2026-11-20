# BEAM Recall 实际 SQL 与交互次数

采集自完整冻结 Bank 的正确性核对，参数值不公开。这里的单次抓取包含驱动首次类型发现，不能用它代替多轮性能统计。

| 问题 ID | 原路径业务 SQL 次数 | 时间路径 | 下推候选入口 |
| --- | ---: | --- | ---: |
| 1_abstention_0 | 6 | 无 | 1 |
| 1_abstention_1 | 6 | 无 | 1 |
| 1_contradiction_resolution_0 | 5 | 无 | 1 |
| 1_contradiction_resolution_1 | 7 | 有 | 1 |
| 1_event_ordering_0 | 6 | 无 | 1 |
| 1_event_ordering_1 | 6 | 无 | 1 |
| 1_information_extraction_0 | 6 | 无 | 1 |
| 1_information_extraction_1 | 6 | 无 | 1 |
| 1_instruction_following_0 | 5 | 无 | 1 |
| 1_instruction_following_1 | 5 | 无 | 1 |
| 1_knowledge_update_0 | 5 | 无 | 1 |
| 1_knowledge_update_1 | 5 | 无 | 1 |
| 1_multi_session_reasoning_0 | 6 | 无 | 1 |
| 1_multi_session_reasoning_1 | 5 | 无 | 1 |
| 1_preference_following_0 | 6 | 无 | 1 |
| 1_preference_following_1 | 6 | 无 | 1 |
| 1_summarization_0 | 6 | 无 | 1 |
| 1_summarization_1 | 6 | 无 | 1 |
| 1_temporal_reasoning_0 | 6 | 无 | 1 |
| 1_temporal_reasoning_1 | 6 | 无 | 1 |

业务计数包含选词、向量/全文、关系扩展和最终补查；不含 Bank/config 与驱动初始化。原路径的异步任务有依赖，表中次数不能累加成总耗时。下推入口内部仍执行多条 SQL，鉴权等固定交互没有消失。

## term_selection

沿用原有词项选择：查询词较多时，查 PG 词频统计，保留原规则选出的词。

```sql
WITH toks AS (
    SELECT ord, tok
    FROM unnest($1::text[]) WITH ORDINALITY AS u(tok, ord)
),
lex AS (
    SELECT t.ord, l.lexeme
    FROM toks t
    LEFT JOIN LATERAL unnest(tsvector_to_array(to_tsvector($4::regconfig, t.tok))) AS l(lexeme) ON true
),
stats AS (
    SELECT unnest(most_common_elems::text::text[]) AS lexeme,
           unnest((most_common_elem_freqs)[1:array_length(most_common_elems::text::text[], 1)]) AS freq
    FROM pg_stats
    WHERE schemaname = $2 AND tablename = $3 AND attname = 'search_vector'
)
SELECT lex.ord AS ord,
       bool_or(lex.lexeme IS NOT NULL) AS has_lexeme,
       COALESCE(MAX(s.freq), 0)::float8 AS df
FROM lex
LEFT JOIN stats s ON s.lexeme = lex.lexeme
GROUP BY lex.ord
ORDER BY lex.ord
```

## native_vector_and_fts

原始 UNION 一次取各事实类型的向量与全文候选；全文为原生 tsvector/ts_rank，不是 BM25。

```sql
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        1 - (embedding <=> $1::vector) AS similarity,        NULL::float AS bm25_score,        'semantic' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'experience'   AND embedding IS NOT NULL   AND (1 - (embedding <=> $1::vector)) >= 0.3          ORDER BY embedding <=> $1::vector LIMIT 1000)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        1 - (embedding <=> $1::vector) AS similarity,        NULL::float AS bm25_score,        'semantic' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'world'   AND embedding IS NOT NULL   AND (1 - (embedding <=> $1::vector)) >= 0.3          ORDER BY embedding <=> $1::vector LIMIT 1000)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        1 - (embedding <=> $1::vector) AS similarity,        NULL::float AS bm25_score,        'semantic' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'observation'   AND embedding IS NOT NULL   AND (1 - (embedding <=> $1::vector)) >= 0.3          ORDER BY embedding <=> $1::vector LIMIT 1000)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        NULL::float AS similarity,        ts_rank_cd(search_vector, to_tsquery('english', $4)) AS bm25_score,        'bm25' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'experience'   AND search_vector @@ to_tsquery('english', $4)          ORDER BY ts_rank_cd(search_vector, to_tsquery('english', $4)) DESC LIMIT $3)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        NULL::float AS similarity,        ts_rank_cd(search_vector, to_tsquery('english', $4)) AS bm25_score,        'bm25' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'world'   AND search_vector @@ to_tsquery('english', $4)          ORDER BY ts_rank_cd(search_vector, to_tsquery('english', $4)) DESC LIMIT $3)
UNION ALL
(SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, document_id, chunk_id, tags, metadata, proof_count,        NULL::float AS similarity,        ts_rank_cd(search_vector, to_tsquery('english', $4)) AS bm25_score,        'bm25' AS source FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $2   AND fact_type = 'observation'   AND search_vector @@ to_tsquery('english', $4)          ORDER BY ts_rank_cd(search_vector, to_tsquery('english', $4)) DESC LIMIT $3)
```

## graph_expansion

使用向量种子做实体、语义和因果关系扩展；world/experience 各执行一次，保留原游标顺序。

```sql
WITH
            seed_entities AS (
                SELECT DISTINCT ue.entity_id
                FROM ctxdb_ws_beam1m_1_20261120.unit_entities ue
                WHERE ue.unit_id = ANY($1::uuid[])
            ),
            entity_expanded AS (
                SELECT mu.id, mu.text, mu.context, mu.event_date,
                       mu.occurred_start, mu.occurred_end, mu.mentioned_at, mu.fact_type,
                       mu.document_id, mu.chunk_id, mu.tags, mu.proof_count,
                       COUNT(DISTINCT se.entity_id)::float AS score,
                       'entity'::text AS source
                FROM seed_entities se
                CROSS JOIN LATERAL (
                    SELECT ue_target.unit_id
                    FROM ctxdb_ws_beam1m_1_20261120.unit_entities ue_target
                    WHERE ue_target.entity_id = se.entity_id
                      AND ue_target.unit_id != ALL($1::uuid[])
                      -- Filter before applying the cap: candidates from other fact
                      -- types, or outside the recall window, must not consume this
                      -- entity's bounded fan-out.
                      AND EXISTS (
                          SELECT 1
                          FROM ctxdb_ws_beam1m_1_20261120.memory_units mu_target
                          WHERE mu_target.id = ue_target.unit_id
                            AND mu_target.fact_type = $2

                      )
                    ORDER BY ue_target.unit_id DESC
                    LIMIT 200
                ) t
                JOIN ctxdb_ws_beam1m_1_20261120.memory_units mu ON mu.id = t.unit_id
                GROUP BY mu.id
                ORDER BY score DESC
                LIMIT $3
            ),

            semantic_expanded AS (
                SELECT
                    id, text, context, event_date,
                    occurred_start, occurred_end, mentioned_at, fact_type,
                    document_id, chunk_id, tags, proof_count,
                    MAX(weight) AS score,
                    'semantic'::text AS source
                FROM (
                    SELECT
                        mu.id, mu.text, mu.context, mu.event_date,
                        mu.occurred_start, mu.occurred_end, mu.mentioned_at, mu.fact_type,
                        mu.document_id, mu.chunk_id, mu.tags, mu.proof_count,
                        ml.weight
                    FROM ctxdb_ws_beam1m_1_20261120.memory_links ml
                    JOIN ctxdb_ws_beam1m_1_20261120.memory_units mu ON mu.id = ml.to_unit_id
                    WHERE ml.from_unit_id = ANY($1::uuid[])
                      AND ml.link_type = 'semantic'
                      AND mu.fact_type = $2
                      AND mu.id != ALL($1::uuid[])

                    UNION ALL
                    SELECT
                        mu.id, mu.text, mu.context, mu.event_date,
                        mu.occurred_start, mu.occurred_end, mu.mentioned_at, mu.fact_type,
                        mu.document_id, mu.chunk_id, mu.tags, mu.proof_count,
                        ml.weight
                    FROM ctxdb_ws_beam1m_1_20261120.memory_links ml
                    JOIN ctxdb_ws_beam1m_1_20261120.memory_units mu ON mu.id = ml.from_unit_id
                    WHERE ml.to_unit_id = ANY($1::uuid[])
                      AND ml.link_type = 'semantic'
                      AND mu.fact_type = $2
                      AND mu.id != ALL($1::uuid[])

                ) sem_raw
                GROUP BY id, text, context, event_date,
                         occurred_start, occurred_end, mentioned_at, fact_type,
                         document_id, chunk_id, tags, proof_count
                ORDER BY score DESC
                LIMIT $3
            ),
            causal_expanded AS (
                SELECT DISTINCT ON (mu.id)
                    mu.id, mu.text, mu.context, mu.event_date,
                    mu.occurred_start, mu.occurred_end, mu.mentioned_at, mu.fact_type,
                    mu.document_id, mu.chunk_id, mu.tags, mu.proof_count,
                    ml.weight AS score,
                    'causal'::text AS source
                FROM ctxdb_ws_beam1m_1_20261120.memory_links ml
                JOIN ctxdb_ws_beam1m_1_20261120.memory_units mu ON ml.to_unit_id = mu.id
                WHERE ml.from_unit_id = ANY($1::uuid[])
                  AND ml.link_type IN ('causes', 'caused_by', 'enables', 'prevents')
                  AND mu.fact_type = $2

                ORDER BY mu.id, ml.weight DESC
                LIMIT $3
            )
            SELECT * FROM entity_expanded
            UNION ALL
            SELECT * FROM semantic_expanded
            UNION ALL
            SELECT * FROM causal_expanded
```

## temporal

出现解析出的时间窗口时，共用时间候选池，再按事实类型继续有界扩展。

```sql
(
        SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, proof_count, document_id, chunk_id, tags, metadata, 1 - (embedding <=> $1::vector) AS similarity
        FROM ctxdb_ws_beam1m_1_20261120.memory_units
        WHERE bank_id = $2
          AND fact_type = 'experience'
          AND embedding IS NOT NULL
          AND (
              (occurred_start IS NOT NULL AND occurred_end IS NOT NULL
               AND occurred_start <= $4 AND occurred_end >= $3)
              OR
              (mentioned_at IS NOT NULL AND mentioned_at BETWEEN $3 AND $4)
              OR
              (occurred_start IS NOT NULL AND occurred_start BETWEEN $3 AND $4)
              OR
              (occurred_end IS NOT NULL AND occurred_end BETWEEN $3 AND $4)
          )
          AND (1 - (embedding <=> $1::vector)) >= $5



        ORDER BY embedding <=> $1::vector
        LIMIT 60
        )
UNION ALL
(
        SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, proof_count, document_id, chunk_id, tags, metadata, 1 - (embedding <=> $1::vector) AS similarity
        FROM ctxdb_ws_beam1m_1_20261120.memory_units
        WHERE bank_id = $2
          AND fact_type = 'world'
          AND embedding IS NOT NULL
          AND (
              (occurred_start IS NOT NULL AND occurred_end IS NOT NULL
               AND occurred_start <= $4 AND occurred_end >= $3)
              OR
              (mentioned_at IS NOT NULL AND mentioned_at BETWEEN $3 AND $4)
              OR
              (occurred_start IS NOT NULL AND occurred_start BETWEEN $3 AND $4)
              OR
              (occurred_end IS NOT NULL AND occurred_end BETWEEN $3 AND $4)
          )
          AND (1 - (embedding <=> $1::vector)) >= $5



        ORDER BY embedding <=> $1::vector
        LIMIT 60
        )
UNION ALL
(
        SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, proof_count, document_id, chunk_id, tags, metadata, 1 - (embedding <=> $1::vector) AS similarity
        FROM ctxdb_ws_beam1m_1_20261120.memory_units
        WHERE bank_id = $2
          AND fact_type = 'observation'
          AND embedding IS NOT NULL
          AND (
              (occurred_start IS NOT NULL AND occurred_end IS NOT NULL
               AND occurred_start <= $4 AND occurred_end >= $3)
              OR
              (mentioned_at IS NOT NULL AND mentioned_at BETWEEN $3 AND $4)
              OR
              (occurred_start IS NOT NULL AND occurred_start BETWEEN $3 AND $4)
              OR
              (occurred_end IS NOT NULL AND occurred_end BETWEEN $3 AND $4)
          )
          AND (1 - (embedding <=> $1::vector)) >= $5



        ORDER BY embedding <=> $1::vector
        LIMIT 60
        )
```

## chunks

原始流程在筛选之后补读原文；下推版预先返回可能需要的原文，模型之后不再补查。

```sql
SELECT chunk_id, chunk_text, chunk_index, document_id
            FROM ctxdb_ws_beam1m_1_20261120.chunks
            WHERE chunk_id = ANY($1::text[])
```

## attachment_metadata

原始流程补查 document/attachment 元数据。本数据没有附件；下推版已携带需要的字段。

```sql
SELECT id::text AS id, document_id, attachment_ids FROM ctxdb_ws_beam1m_1_20261120.memory_units WHERE bank_id = $1 AND id = ANY($2::uuid[])
```

## 优化下推入口

```sql
SELECT recall_beam_arrays.candidates($1::jsonb, $2::name) AS bundle;
```

参数一为服务端生成的候选请求 JSON，包含查询向量、Bank、类型预算、时间范围和原始 SQL 模板；参数二为认证解析出的租户 schema。它是内部候选协议，不接受 HTTP 调用方任意提交 SQL。具体实现见开发工作区 `hindsight-api-slim/hindsight_api/engine/memories/pg/recall_arrays.sql`。
