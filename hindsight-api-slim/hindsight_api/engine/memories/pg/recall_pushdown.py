"""Opt-in, frozen-world-bank candidate pushdown; model and budgets stay in ContextBase.

The historical control establishes explicit UUID ties for diagnosis only.
EquivalentPostgresRecallMemories instead preserves the frozen original arm order
and keeps C RRF in PG. See recall_equivalent.sql for its narrow runtime contract.
"""

import os
import sys
import time
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ....config import get_config
from ...db_utils import acquire_with_retry
from ...response_models import RecallResult
from ...retain.attachment_content import iter_placeholder_ids
from ...search.retrieval import tokenize_query
from ...search.types import MergedCandidate
from ..base import FullRecallRequest, RecallArms, RecallCandidateBatch, RecallCandidateChunk
from ..postgres import PostgresMemories


class CandidateQuery(BaseModel):
    """Only serializable resolved query values cross into PG."""

    model_config = ConfigDict(extra="forbid")
    bank_id: str
    fact_types: list[str]
    embedding: str
    tsquery: str
    limit: int
    candidate_cap: int
    window_start: datetime | None
    window_end: datetime | None
    semantic_min: float
    temporal_min: float
    graph_seed_min: float
    per_entity_limit: int
    native_sql: str | None = None
    graph_sql: str | None = None
    temporal_sql: str | None = None


class LegacyQueries(BaseModel):
    native_sql: str
    graph_sql: str
    temporal_sql: str


class CandidatePayload(BaseModel):
    """All required fields must be present: missing chunks cannot trigger a reread."""

    model_config = ConfigDict(extra="forbid")
    version: Literal[1]
    candidates: list[MergedCandidate]
    chunks: dict[str, RecallCandidateChunk]


class CanonicalPostgresMemories(PostgresMemories):
    """Same legacy queries, explicit ties for the paired feasibility baseline."""

    name = "postgres-canonical-control"
    resolve_temporal_before_full_recall = True

    async def recall_unified(self, **kwargs: Any) -> dict[str, RecallArms]:
        arms = await super().recall_unified(**kwargs)
        for lists in arms.values():
            lists.semantic.sort(key=lambda r: (-(r.similarity or 0.0), r.id))
            lists.bm25.sort(key=lambda r: (-(r.bm25_score or 0.0), r.id))
            lists.graph.sort(key=lambda r: (-(r.activation or 0.0), r.id))
            lists.temporal.sort(key=lambda r: (-(r.temporal_score or 0.0), r.id))
        return arms


class PostgresRecallPushdownMemories(CanonicalPostgresMemories):
    """One PG call, then the engine's original model/scoring/budget finalizer.

    BANK_ID is an explicit experimental allowlist, not a QA-type route. Other banks
    and unsupported request shapes decline before any query; a failure after the
    query propagates instead of silently performing a second, legacy retrieval.
    """

    name = "postgres-recall-pushdown-experimental"
    candidate_statement = "SELECT recall_pushdown.candidates($1::jsonb, $2::name) AS bundle"

    def legacy_queries(self, request: FullRecallRequest) -> LegacyQueries | None:
        return None

    def supports_query_terms(self, request: FullRecallRequest) -> bool:
        config = get_config()
        return (
            config.bm25_max_query_terms <= 0 or len(tokenize_query(request.query_text)) <= config.bm25_max_query_terms
        )

    def supports(self, request: FullRecallRequest) -> bool:
        config = get_config()
        return (
            bool(self.config.get("bank_id"))
            and request.bank_id == self.config["bank_id"]
            and request.runtime is not None
            and "world" in request.fact_types
            and set(request.fact_types) <= {"world", "experience", "observation"}
            and request.tags is None
            and request.tags_match == "any"
            and not request.tag_groups
            and request.created_after is None
            and request.created_before is None
            and request.min_keyword in {None, 0.0}
            and (
                (request.min_semantic if request.min_semantic is not None else config.semantic_min_similarity)
                <= config.graph_seed_min_similarity
            )
            and request.enable_text_search
            and request.enable_graph
            and request.reranking in {"rrf", "cross_encoder"}
            and request.per_source_cap == 0
            and not request.strategy_boosts
            and not request.include_entities
            and not request.include_source_facts
            and request.reranker_max_candidates > 0
            and 20 <= request.limit <= 2000
            and config.database_backend == "postgresql"
            and config.text_search_extension == "native"
            and config.text_search_extension_native_language == "english"
            and config.bm25_min_score == 0
            and config.graph_retriever == "link_expansion"
            and self.supports_query_terms(request)
        )

    def candidate_query(self, request: FullRecallRequest) -> CandidateQuery:
        config = get_config()
        window = request.temporal_window
        templates = self.legacy_queries(request)
        return CandidateQuery(
            bank_id=request.bank_id,
            fact_types=request.fact_types,
            embedding=request.query_embedding,
            tsquery=" | ".join(tokenize_query(request.query_text)),
            limit=request.limit,
            candidate_cap=request.reranker_max_candidates,
            window_start=window[0] if window else None,
            window_end=window[1] if window else None,
            semantic_min=request.min_semantic if request.min_semantic is not None else config.semantic_min_similarity,
            temporal_min=request.temporal_semantic_threshold,
            graph_seed_min=config.graph_seed_min_similarity,
            per_entity_limit=config.link_expansion_per_entity_limit,
            native_sql=templates.native_sql if templates else None,
            graph_sql=templates.graph_sql if templates else None,
            temporal_sql=templates.temporal_sql if templates else None,
        )

    async def full_recall(self, request: FullRecallRequest) -> RecallResult | None:
        if not self.supports(request):
            return None
        assert request.runtime is not None
        from ...memory_engine import get_current_schema

        query = self.candidate_query(request)
        # Returning the connection before model inference avoids holding a PG query
        # snapshot or pool slot across seconds of CPU inference. No post-query loader
        # is installed: the shared finalizer consumes only this complete bundle.
        started = time.perf_counter()
        async with acquire_with_retry(request.runtime.backend) as conn:
            row = await conn.fetchrow(
                self.candidate_statement,
                query.model_dump_json(),
                get_current_schema().strip('"'),
            )
        if row is None:
            raise RuntimeError("PG recall did not return a candidate bundle")
        raw = row["bundle"]
        payload = (
            CandidatePayload.model_validate_json(raw) if isinstance(raw, str) else CandidatePayload.model_validate(raw)
        )

        if any(candidate.retrieval.attachment_ids for candidate in payload.candidates) or any(
            any(iter_placeholder_ids(chunk.chunk_text)) for chunk in payload.chunks.values()
        ):
            raise RuntimeError("Attachment-bearing data is outside experimental single-call recall scope")
        return await request.runtime.finalize(
            RecallCandidateBatch(
                candidates=payload.candidates,
                chunks=payload.chunks,
                fully_loaded=True,
                stages={"pg_candidates_and_transfer": int((time.perf_counter() - started) * 1_000_000)},
            )
        )


class EquivalentPostgresRecallMemories(PostgresRecallPushdownMemories):
    """Preserve the frozen CPython legacy ranking contract before optimizing it.

    The compatibility functions are an experimental adapter, not a database-wide
    ranking policy. Unknown interpreter/hash configurations decline before I/O.
    No SQL or request supplied by an HTTP caller is executed as a template.
    """

    name = "postgres-recall-legacy-equivalent-experimental"
    candidate_statement = "SELECT recall_equiv.candidates($1::jsonb, $2::name) AS bundle"

    def supports(self, request: FullRecallRequest) -> bool:
        return (
            super().supports(request)
            and sys.version_info[:2] == (3, 11)
            and sys.hash_info.algorithm == "siphash13"
            and sys.hash_info.width == 64
            and os.environ.get("PYTHONHASHSEED") == "0"
        )

    async def recall_unified(self, **kwargs: Any) -> dict[str, RecallArms]:
        # A declined experimental request must use the original fallback; the
        # historical Canonical control must not normalize its candidate ties.
        return await PostgresMemories.recall_unified(self, **kwargs)

    def legacy_queries(self, request: FullRecallRequest) -> LegacyQueries:
        # These are the same dialect/ops builders used by the original store.
        # Keep the entire UNION and the graph query, not separate rewritten arms:
        # even adding a UUID key to an equal-score sort changes the RRF contract.
        from ...db.ops import UpdatedWindow
        from ...schema import fq_store_table
        from ...sql import create_sql_dialect

        assert request.runtime is not None
        cfg = get_config()
        dialect = create_sql_dialect("postgresql")
        cols = (
            "id, text, context, event_date, occurred_start, occurred_end, mentioned_at, "
            "fact_type, document_id, chunk_id, tags, metadata, proof_count"
        )
        table = fq_store_table("memory_units")
        minimum = request.min_semantic if request.min_semantic is not None else cfg.semantic_min_similarity
        arms = [
            dialect.build_semantic_arm(
                table=table,
                cols=cols,
                fact_type=ft,
                embedding_param="$1",
                bank_id_param="$2",
                fetch_limit=max(request.limit, 20),
                min_similarity=minimum,
                tags_clause="",
                groups_clause="",
                extra_where="",
            )
            for ft in request.fact_types
        ]
        for index, ft in enumerate(request.fact_types):
            arms.append(
                dialect.build_bm25_arm(
                    table=table,
                    cols=cols,
                    fact_type=ft,
                    bank_id_param="$2",
                    limit_param="$3",
                    text_param="$4",
                    tags_clause="",
                    groups_clause="",
                    arm_index=index,
                    text_search_extension="native",
                    bm25_language="english",
                    bm25_min_score=0,
                    pg_search_function_schema=cfg.text_search_extension_pg_search_function_schema,
                    pg_search_tokenizer=cfg.text_search_extension_pg_search_tokenizer,
                    max_query_terms=cfg.bm25_max_query_terms,
                    extra_where="",
                )
            )
        ops = request.runtime.backend.ops
        window = UpdatedWindow(after=None, before=None, first_param_index=4)
        entity_cte = ops.build_entity_expansion_cte(
            table, fq_store_table("unit_entities"), cfg.link_expansion_per_entity_limit, window
        )
        linked_cte = ops.build_semantic_causal_cte(fq_store_table("memory_links"), table, window)
        graph_sql = f"""
            WITH {entity_cte},
            {linked_cte}
            SELECT * FROM entity_expanded
            UNION ALL
            SELECT * FROM semantic_expanded
            UNION ALL
            SELECT * FROM causal_expanded
            """
        pool_cols = (
            "id, text, context, event_date, occurred_start, occurred_end, mentioned_at, "
            "fact_type, proof_count, document_id, chunk_id, tags, metadata"
        )
        temporal_arms = [
            f"""(
        SELECT {pool_cols}, 1 - (embedding <=> $1::vector) AS similarity
        FROM {table}
        WHERE bank_id = $2
          AND fact_type = '{ft}'
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
        )"""
            for ft in request.fact_types
        ]
        return LegacyQueries(
            native_sql="\nUNION ALL\n".join(arms),
            graph_sql=graph_sql,
            temporal_sql="\nUNION ALL\n".join(temporal_arms),
        )
