"""Single-query ownership, no rereads, strict payloads and fail-closed boundaries."""

import asyncio
import json
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from hindsight_api.engine.db.base import DatabaseBackend
from hindsight_api.engine.memories.base import FullRecallRequest, FullRecallRuntime
from hindsight_api.engine.memories.pg import recall_pushdown
from hindsight_api.engine.memories.pg.recall_pushdown import PostgresRecallPushdownMemories
from hindsight_api.engine.response_models import RecallResult

BANK = "pushdown-test"


def request() -> FullRecallRequest:
    return FullRecallRequest(
        bank_id=BANK,
        fact_types=["world", "experience", "observation"],
        query_embedding="[1,0]",
        query_text="conference plans",
        limit=1000,
        reranker_max_candidates=300,
        runtime=FullRecallRuntime(backend=cast(DatabaseBackend, object()), finalize=AsyncMock()),
    )


def payload() -> str:
    return json.dumps(
        {
            "version": 1,
            "candidates": [
                {
                    "retrieval": {
                        "id": "00000000-0000-0000-0000-000000000001",
                        "text": "A meeting",
                        "fact_type": "world",
                        "attachment_ids": [],
                    },
                    "rrf_score": 1 / 61,
                    "rrf_rank": 1,
                    "source_ranks": {"semantic_rank": 1},
                    "arm_scores": {"semantic": 0.5, "keyword": None},
                }
            ],
            "chunks": {"chunk-1": {"chunk_text": "The original meeting notes", "chunk_index": 0, "document_id": "doc"}},
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("bank_id", "other"),
        ("tags", []),
        ("tags", ["private"]),
        ("include_entities", True),
        ("include_source_facts", True),
        ("reranking", "interleave"),
        ("per_source_cap", 1),
        ("min_keyword", 0.5),
        ("min_semantic", 0.9),
    ],
)
async def test_unsupported_request_declines_without_read(monkeypatch, field, value):
    req = request()
    setattr(req, field, value)
    reads = AsyncMock(side_effect=AssertionError("unsupported request touched PG"))
    monkeypatch.setattr(recall_pushdown, "acquire_with_retry", reads)
    assert await PostgresRecallPushdownMemories({"bank_id": BANK}).full_recall(req) is None
    reads.assert_not_called()
    assert req.runtime is not None
    req.runtime.finalize.assert_not_called()


@pytest.mark.asyncio
async def test_one_query_releases_connection_before_shared_finalizer(monkeypatch):
    req = request()
    connected = False
    conn = AsyncMock()
    conn.fetchrow.return_value = {"bundle": payload()}

    @asynccontextmanager
    async def acquire(backend):
        nonlocal connected
        assert req.runtime is not None and backend is req.runtime.backend
        connected = True
        try:
            yield conn
        finally:
            connected = False

    async def finalize(batch):
        assert not connected, "PG connection held across model inference"
        assert batch.fully_loaded
        assert len(batch.candidates) == 1
        assert batch.chunks["chunk-1"].chunk_text == "The original meeting notes"
        assert batch.candidates[0].retrieval.attachment_ids == []
        return RecallResult(results=[])

    monkeypatch.setattr(recall_pushdown, "acquire_with_retry", acquire)
    assert req.runtime is not None
    req.runtime.finalize = finalize
    result = await PostgresRecallPushdownMemories({"bank_id": BANK}).full_recall(req)
    assert result is not None and result.results == []
    conn.fetchrow.assert_awaited_once()
    sql, parameters, schema = conn.fetchrow.await_args.args
    assert sql == "SELECT recall_pushdown.candidates($1::jsonb, $2::name) AS bundle"
    assert json.loads(parameters)["bank_id"] == BANK
    assert schema
    conn.fetch.assert_not_called()
    conn.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("seed", [None, "random", "1"])
async def test_equivalent_adapter_declines_unknown_hash_contract(monkeypatch, seed):
    if seed is None:
        monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    else:
        monkeypatch.setenv("PYTHONHASHSEED", seed)
    reads = AsyncMock(side_effect=AssertionError("unsupported hash contract queried PG"))
    monkeypatch.setattr(recall_pushdown, "acquire_with_retry", reads)
    store = recall_pushdown.EquivalentPostgresRecallMemories({"bank_id": BANK})
    assert await store.full_recall(request()) is None
    reads.assert_not_called()


@pytest.mark.asyncio
async def test_equivalent_native_template_matches_original_query_builder(monkeypatch):
    from hindsight_api.engine.db.postgresql import PostgreSQLBackend
    from hindsight_api.engine.memories.pg.recall import retrieve_semantic_bm25_combined_sql

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    req = request()
    assert req.runtime is not None
    req.runtime.backend = PostgreSQLBackend()
    store = recall_pushdown.EquivalentPostgresRecallMemories({"bank_id": BANK})
    templates = store.legacy_queries(req)
    conn = AsyncMock()
    conn.backend_type = "postgresql"
    conn.fetch.return_value = []
    await retrieve_semantic_bm25_combined_sql(
        conn,
        req.query_embedding,
        req.query_text,
        req.bank_id,
        req.fact_types,
        req.limit,
        graph_seed_min_similarity=recall_pushdown.get_config().graph_seed_min_similarity,
    )
    original_sql = conn.fetch.await_args.args[0]
    assert " ".join(templates.native_sql.split()) == " ".join(original_sql.split())
    assert "ORDER BY score DESC, id" not in templates.graph_sql


@pytest.mark.asyncio
async def test_missing_required_chunks_fails_without_retry_or_finalization(monkeypatch):
    req = request()
    conn = AsyncMock()
    incomplete = json.loads(payload())
    del incomplete["chunks"]
    conn.fetchrow.return_value = {"bundle": json.dumps(incomplete)}

    @asynccontextmanager
    async def acquire(_backend):
        yield conn

    monkeypatch.setattr(recall_pushdown, "acquire_with_retry", acquire)
    with pytest.raises(ValidationError):
        await PostgresRecallPushdownMemories({"bank_id": BANK}).full_recall(req)
    conn.fetchrow.assert_awaited_once()
    assert req.runtime is not None
    req.runtime.finalize.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_propagates_and_connection_is_released(monkeypatch):
    req = request()
    released = False
    conn = AsyncMock()
    conn.fetchrow.side_effect = asyncio.CancelledError()

    @asynccontextmanager
    async def acquire(_backend):
        nonlocal released
        try:
            yield conn
        finally:
            released = True

    monkeypatch.setattr(recall_pushdown, "acquire_with_retry", acquire)
    with pytest.raises(asyncio.CancelledError):
        await PostgresRecallPushdownMemories({"bank_id": BANK}).full_recall(req)
    assert released
    conn.fetchrow.assert_awaited_once()
    assert req.runtime is not None
    req.runtime.finalize.assert_not_called()


def test_extension_loader_uses_the_standard_lowercase_config(monkeypatch):
    from hindsight_api.engine.memories import create_memories

    monkeypatch.setenv(
        "HINDSIGHT_API_MEMORIES_EXTENSION",
        "hindsight_api.engine.memories.pg.recall_pushdown:PostgresRecallPushdownMemories",
    )
    monkeypatch.setenv("HINDSIGHT_API_MEMORIES_BANK_ID", BANK)
    store = create_memories()
    assert isinstance(store, PostgresRecallPushdownMemories)
    assert store.config["bank_id"] == BANK
    assert store.supports(request())


@pytest.mark.asyncio
async def test_complete_empty_attachment_refs_do_not_read_pg(monkeypatch):
    from hindsight_api.engine.memories import postgres
    from hindsight_api.engine.memory_engine import MemoryEngine
    from hindsight_api.models import RequestContext

    monkeypatch.setattr("hindsight_api.engine.memories.get_memories", lambda: postgres.PostgresMemories({}))
    engine = MemoryEngine.__new__(MemoryEngine)
    engine.get_bank_profile = AsyncMock(side_effect=AssertionError("complete empty refs must not read"))
    result = await engine.attachments_for_memories(BANK, ["unit"], RequestContext(), carried={"unit": (None, [])})
    assert result == {}
    engine.get_bank_profile.assert_not_called()


@pytest.mark.asyncio
async def test_partial_attachment_refs_still_authorize_and_load(monkeypatch):
    from hindsight_api.engine.memories import postgres
    from hindsight_api.engine.memory_engine import MemoryEngine
    from hindsight_api.models import RequestContext

    monkeypatch.setattr("hindsight_api.engine.memories.get_memories", lambda: postgres.PostgresMemories({}))
    engine = MemoryEngine.__new__(MemoryEngine)
    engine.get_bank_profile = AsyncMock(return_value=None)
    result = await engine.attachments_for_memories(
        BANK, ["unit", "missing"], RequestContext(), carried={"unit": (None, [])}
    )
    assert result == {}
    engine.get_bank_profile.assert_awaited_once()


@pytest.mark.asyncio
async def test_equivalent_fallback_preserves_original_arm_order(monkeypatch):
    from hindsight_api.engine.memories.base import RecallArms
    from hindsight_api.engine.search.types import RetrievalResult

    # Intentionally reverse UUID order among equal-score results. Calling the
    # historical Canonical fallback would silently reorder these candidates.
    original = RecallArms(
        semantic=[
            RetrievalResult(id="z", text="first", fact_type="world", similarity=0.5),
            RetrievalResult(id="a", text="second", fact_type="world", similarity=0.5),
        ]
    )
    fallback = AsyncMock(return_value={"world": original})
    monkeypatch.setattr(recall_pushdown.PostgresMemories, "recall_unified", fallback)
    store = recall_pushdown.EquivalentPostgresRecallMemories({"bank_id": BANK})
    result = await store.recall_unified(bank_id=BANK)
    assert result["world"] is original
    assert [item.id for item in result["world"].semantic] == ["z", "a"]
    fallback.assert_awaited_once_with(store, bank_id=BANK)
