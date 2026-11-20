"""The BEAM opt-in adapter must keep legacy guards and avoid preparation I/O."""

from unittest.mock import AsyncMock

import pytest

from hindsight_api.engine.db.postgresql import PostgreSQLBackend
from hindsight_api.engine.memories.base import FullRecallRequest, FullRecallRuntime
from hindsight_api.engine.memories.pg.recall_beam import BeamPostgresRecallMemories
from hindsight_api.engine.memories.pg.recall_pushdown import EquivalentPostgresRecallMemories
from hindsight_api.engine.search.retrieval import tokenize_query


def make_request() -> FullRecallRequest:
    return FullRecallRequest(
        bank_id="beam-test",
        fact_types=["experience", "world", "observation"],
        query_embedding="[1,0]",
        query_text=" ".join(f"term{i}" for i in range(32)),
        limit=1000,
        reranker_max_candidates=300,
        runtime=FullRecallRuntime(backend=PostgreSQLBackend(), finalize=AsyncMock()),
    )


def test_long_query_preserves_original_text_and_server_term_policy(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("HINDSIGHT_API_BM25_MAX_QUERY_TERMS", "16")
    req = make_request()
    original_text = req.query_text
    base = EquivalentPostgresRecallMemories({"bank_id": "beam-test"})
    beam = BeamPostgresRecallMemories({"bank_id": "beam-test"})
    assert not base.supports(req), "First-stage scope must remain unchanged"
    assert beam.supports(req)
    query = beam.candidate_query(req)
    assert query.tokens == tokenize_query(original_text)
    assert query.term_limit == 16
    assert query.fact_types == req.fact_types
    assert query.native_sql == base.legacy_queries(req).native_sql
    assert req.query_text == original_text
    # A backend that exposes a query method here would make an accidental
    # preparatory I/O possible. This backend is deliberately uninitialized.
    assert req.runtime is not None
    with pytest.raises(RuntimeError, match="not initialized"):
        req.runtime.backend.get_pool()


@pytest.mark.parametrize("field,value", [("tags", ["private"]), ("include_entities", True), ("per_source_cap", 10)])
def test_long_query_support_does_not_relax_other_guards(monkeypatch, field, value):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    req = make_request()
    setattr(req, field, value)
    assert not BeamPostgresRecallMemories({"bank_id": "beam-test"}).supports(req)


def test_default_adapter_still_serializes_the_same_short_query(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    req = make_request()
    req.query_text = "conference plans"
    base = EquivalentPostgresRecallMemories({"bank_id": "beam-test"})
    assert base.supports(req)
    query = base.candidate_query(req)
    assert query.tsquery == "conference | plans"
    assert "tokens" not in query.model_dump()
    assert query.candidate_cap == 300
    assert query.window_start is None
