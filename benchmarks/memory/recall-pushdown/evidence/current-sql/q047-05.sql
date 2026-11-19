
            WITH
            seed_entities AS (
                SELECT DISTINCT ue.entity_id
                FROM ctxdb_ws_locomo_conv30_20261118_200523.unit_entities ue
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
                    FROM ctxdb_ws_locomo_conv30_20261118_200523.unit_entities ue_target
                    WHERE ue_target.entity_id = se.entity_id
                      AND ue_target.unit_id != ALL($1::uuid[])
                      -- Filter before applying the cap: candidates from other fact
                      -- types, or outside the recall window, must not consume this
                      -- entity's bounded fan-out.
                      AND EXISTS (
                          SELECT 1
                          FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu_target
                          WHERE mu_target.id = ue_target.unit_id
                            AND mu_target.fact_type = $2

                      )
                    ORDER BY ue_target.unit_id DESC
                    LIMIT 200
                ) t
                JOIN ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu ON mu.id = t.unit_id
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
                    FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_links ml
                    JOIN ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu ON mu.id = ml.to_unit_id
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
                    FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_links ml
                    JOIN ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu ON mu.id = ml.from_unit_id
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
                FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_links ml
                JOIN ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu ON ml.to_unit_id = mu.id
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
