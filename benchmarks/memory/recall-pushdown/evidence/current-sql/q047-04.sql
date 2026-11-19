
                SELECT src.from_unit_id, mu.id, mu.text, mu.context, mu.event_date, mu.occurred_start, mu.occurred_end, mu.mentioned_at, mu.fact_type, mu.document_id, mu.chunk_id, mu.tags, mu.metadata, mu.proof_count,
                       l.weight, l.link_type,
                       1 - (mu.embedding <=> $1::vector) AS similarity
                FROM unnest($2::uuid[]) AS src(from_unit_id)
                CROSS JOIN LATERAL (
                    SELECT ml.to_unit_id, ml.weight, ml.link_type
                    FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_links ml
                    WHERE ml.from_unit_id = src.from_unit_id
                      AND ml.link_type IN ('temporal', 'causes', 'caused_by', 'enables', 'prevents')
                      AND ml.weight >= 0.1
                    ORDER BY ml.weight DESC
                    LIMIT $5
                ) l
                JOIN ctxdb_ws_locomo_conv30_20261118_200523.memory_units mu ON mu.id = l.to_unit_id
                WHERE mu.bank_id = $6
                  AND mu.fact_type = $3
                  AND mu.embedding IS NOT NULL
                  AND (1 - (mu.embedding <=> $1::vector)) >= $4
