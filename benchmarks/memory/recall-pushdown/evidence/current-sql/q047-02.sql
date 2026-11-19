(
        SELECT id, text, context, event_date, occurred_start, occurred_end, mentioned_at, fact_type, proof_count, document_id, chunk_id, tags, metadata, 1 - (embedding <=> $1::vector) AS similarity
        FROM ctxdb_ws_locomo_conv30_20261118_200523.memory_units
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
