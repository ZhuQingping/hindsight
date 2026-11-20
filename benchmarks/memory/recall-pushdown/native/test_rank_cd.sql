-- Run on the isolated test PG after registering recall_rank.rank_cd.
-- A nonzero mismatch count raises division-by-zero; no tolerance is used.
WITH vectors(value) AS (
    VALUES
        ('''a'':1 ''b'':1'::tsvector),
        ('''a'':1A,2B,3C,4 ''b'':1B,2C,3,4A'::tsvector),
        ('''a'' ''b'''::tsvector),
        ('''数据'':1A,2B ''存储'':1,5C'::tsvector),
        (''::tsvector),
        (NULL::tsvector)
), queries(value) AS (
    VALUES
        ('a'::tsquery),
        ('a | b'::tsquery),
        ('a | a | b'::tsquery),
        ('a & b'::tsquery),
        ('!a'::tsquery),
        ('a | !b'::tsquery),
        ('a <-> b'::tsquery),
        ('a:*'::tsquery),
        ('a:A'::tsquery),
        ('数据 | 存储'::tsquery),
        (''::tsquery),
        (NULL::tsquery)
), checks AS (
    SELECT float4send(ts_rank_cd(v.value, q.value)) IS DISTINCT FROM
           float4send(recall_rank.rank_cd(v.value, q.value)) AS different
    FROM vectors v CROSS JOIN queries q
)
SELECT count(*) AS comparisons,
       1 / CASE WHEN count(*) FILTER (WHERE different) = 0 THEN 1 ELSE 0 END AS exact
FROM checks;
